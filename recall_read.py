"""
recall_read — recall what you know: the owner's memories, this speaker's memories, and the
notes you jotted in the current conversation.

Returns three kinds of memory, each tagged with its scope so you know what you're looking at:
  - owner:   approved facts/preferences about the owner (apply in every conversation)
  - speaker: approved things about the PERSON you're currently talking to (from their past
             visits) — resolved from the authenticated session, so it's really them
  - session: ephemeral notes you wrote this conversation via recall_write

Call this at the START of every conversation, before the first substantive reply — the speaker is
resolved server-side, so you never need to identify them first. Call again only when the topic
moves somewhere the first read did not cover.
"""

import structlog

from ..base import BaseTool, ToolResult
from ..registry import register_tool
from ._speaker import resolve_speaker

log = structlog.get_logger()

# word_similarity() floor. Measured against real entries: a one-character typo in a name
# scores ~0.75 and an unrelated query ~0.07, so 0.35 sits in a wide empty gap between hit
# and noise.
#
# This must be word_similarity(), NOT similarity(). similarity() scores the query against
# the WHOLE field, so any short query against a normal-length memory scores near zero —
# the same typo above scores 0.101 that way and is missed entirely. word_similarity()
# scores the query against the best-matching run of words inside the field, which is what
# "find this in that memory" actually means.
TRGM_THRESHOLD = 0.35

# Whether pg_trgm is installed. Probed once per process; None = not yet probed.
# Migration 003 tries to install it but succeeds without it on an unprivileged role,
# so this cannot be assumed and is checked rather than declared.
_TRGM_AVAILABLE: bool | None = None


async def _trgm_available(conn) -> bool:
    """True if pg_trgm is installed, so similarity() can be used. Cached per process."""
    global _TRGM_AVAILABLE
    if _TRGM_AVAILABLE is None:
        try:
            _TRGM_AVAILABLE = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')"
            )
        except Exception as e:
            log.warning("trgm_probe_failed", error=str(e))
            _TRGM_AVAILABLE = False
        log.info("recall_search_mode", fuzzy=_TRGM_AVAILABLE)
    return _TRGM_AVAILABLE


@register_tool
class RecallReadTool(BaseTool):
    """Query memory in scope: owner (approved) + this speaker (approved) + this session (notes)."""

    @property
    def name(self) -> str:
        return "recall_read"

    @property
    def description(self) -> str:
        return (
            "Recall what you know. CALL THIS AT THE START OF EVERY CONVERSATION, before your "
            "first substantive reply — not only when you think you need it. You cannot know "
            "whether you have relevant memory about someone until you look. "
            "You do NOT need to work out who you are talking to first: the speaker is resolved "
            "server-side from the authenticated session, so results come back already scoped to "
            "the real person on the other end. "
            "Returns your memories in three scopes, each labelled: 'owner' (approved facts about "
            "the owner, which apply in every conversation), 'speaker' (approved memories about the "
            "specific person you're talking to right now — so you can pick up where you left off "
            "with them), and 'session' (the ephemeral notes you made this conversation via "
            "recall_write). "
            "Call it once up front; call it again only when the topic moves somewhere your first "
            "read did not cover. Never announce the call. Optionally filter by search text or tags."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text search across content, source, and reason. Optional.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter to entries matching ANY of these tags. Optional.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["all", "owner", "speaker", "session"],
                    "description": "Limit to one scope. Default 'all' (owner + this speaker + this session).",
                    "default": "all",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max entries to return. Default 20, max 100.",
                    "default": 20,
                },
            },
            "required": [],
        }

    def credential_keys(self) -> list[str]:
        return []

    async def execute(self, query: str = "", tags: list[str] = None, scope: str = "all", limit: int = 20, **kwargs) -> ToolResult:
        from ...db import get_pool

        pool = get_pool()
        if not pool:
            return ToolResult.fail("Database not available — recall skill requires database configuration")

        limit = min(max(1, limit), 100)
        tags = tags or []
        scope = scope if scope in ("all", "owner", "speaker", "session") else "all"
        who = await resolve_speaker(self)

        # Which scopes to include, and their visibility predicates.
        scope_clauses = []
        params = []

        def _p(v):
            params.append(v)
            return f"${len(params)}"

        if scope in ("all", "owner"):
            scope_clauses.append("(scope = 'owner' AND status = 'approved')")
        if scope in ("all", "speaker") and who["speaker_id"]:
            scope_clauses.append(f"(scope = 'speaker' AND status = 'approved' AND speaker_id = {_p(who['speaker_id'])})")
        if scope in ("all", "session") and who["session_id"]:
            scope_clauses.append(f"(scope = 'session' AND status = 'session' AND session_id = {_p(who['session_id'])})")

        if not scope_clauses:
            return ToolResult.ok({"count": 0, "entries": [], "speaker": who["speaker_label"]})

        try:
            async with pool.acquire() as conn:
                fuzzy = bool(query) and await _trgm_available(conn)

                # Scope predicates are applied first and are never relaxed by search —
                # matching only filters within what this caller could already see.
                where = "(" + " OR ".join(scope_clauses) + ")"
                score_expr = "NULL::real"
                order_by = "(scope = 'session') DESC, created_at DESC"

                if query:
                    like = _p(f"%{query}%")
                    if fuzzy:
                        q = _p(query)
                        thresh = _p(TRGM_THRESHOLD)
                        # Best score across the three text fields. Note the argument order:
                        # word_similarity(needle, haystack) — the query goes first.
                        #
                        # Uses a seq scan rather than the GIN index, because the indexable
                        # form is the <% operator, which reads its threshold from a GUC
                        # instead of taking one explicitly. Recall corpora are small
                        # (hundreds of rows), so an explicit, deterministic threshold is
                        # worth more here than index usage. Revisit if this table grows.
                        score_expr = (
                            f"GREATEST(word_similarity({q}, content), "
                            f"word_similarity({q}, coalesce(reason, '')), "
                            f"word_similarity({q}, coalesce(source, '')))"
                        )
                        where += (
                            f" AND ({score_expr} >= {thresh}"
                            f" OR content ILIKE {like} OR source ILIKE {like} OR reason ILIKE {like})"
                        )
                        order_by = f"(scope = 'session') DESC, {score_expr} DESC, created_at DESC"
                    else:
                        where += (
                            f" AND (content ILIKE {like} OR source ILIKE {like} OR reason ILIKE {like})"
                        )

                if tags:
                    where += f" AND tags && {_p(tags)}"

                sql = (
                    f"SELECT id, content, source, reason, tags, scope, speaker_label, created_at, "
                    f"{score_expr} AS match_score "
                    f"FROM recall_entries WHERE {where} "
                    f"ORDER BY {order_by} LIMIT {_p(limit)}"
                )

                rows = await conn.fetch(sql, *params)
            entries = []
            for r in rows:
                entry = {
                    "id": r["id"],
                    "scope": r["scope"],
                    "content": r["content"],
                    "reason": r["reason"],
                    "tags": r["tags"],
                    "speaker": r["speaker_label"],
                    "created_at": r["created_at"].isoformat(),
                }
                if r["match_score"] is not None:
                    entry["match_score"] = round(float(r["match_score"]), 3)
                entries.append(entry)

            result = {
                "count": len(entries),
                "speaker": who["speaker_label"],
                "entries": entries,
            }
            if query:
                # Tell the model how the search behaved: a fuzzy miss means nothing was
                # close, not that nothing exists. It should re-read without the query.
                result["search"] = {"query": query, "mode": "fuzzy" if fuzzy else "substring"}
            return ToolResult.ok(result)
        except Exception as e:
            log.error("recall_read_error", error=str(e))
            return ToolResult.fail(f"Failed to read memories: {e}")
