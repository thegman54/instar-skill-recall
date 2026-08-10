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

        where = "(" + " OR ".join(scope_clauses) + ")"
        if query:
            where += f" AND (content ILIKE {_p(f'%{query}%')} OR source ILIKE ${len(params)} OR reason ILIKE ${len(params)})"
        if tags:
            where += f" AND tags && {_p(tags)}"

        sql = (
            "SELECT id, content, source, reason, tags, scope, speaker_label, created_at "
            f"FROM recall_entries WHERE {where} "
            f"ORDER BY (scope = 'session') DESC, created_at DESC LIMIT {_p(limit)}"
        )

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
            entries = [
                {
                    "id": r["id"],
                    "scope": r["scope"],
                    "content": r["content"],
                    "reason": r["reason"],
                    "tags": r["tags"],
                    "speaker": r["speaker_label"],
                    "created_at": r["created_at"].isoformat(),
                }
                for r in rows
            ]
            return ToolResult.ok({
                "count": len(entries),
                "speaker": who["speaker_label"],
                "entries": entries,
            })
        except Exception as e:
            log.error("recall_read_error", error=str(e))
            return ToolResult.fail(f"Failed to read memories: {e}")
