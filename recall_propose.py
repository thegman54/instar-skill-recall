"""
recall_propose — ask to remember something PERMANENTLY.

Unlike recall_write (ephemeral, this-conversation-only), a proposal is meant to last. It does
NOT take effect immediately: it goes into a pending queue and the bot owner approves or rejects
it. Once approved, it's readable via recall_read in every future conversation in its scope.

Two scopes:
  - owner:   a lasting fact/preference about the OWNER (global to you, applies in every chat).
  - speaker: something about, or requested by, the PERSON currently talking to you — so that
             next time THEY come back, you remember it. Stored against their authenticated
             identity (resolved server-side; the caller cannot claim to be someone else).
"""

import structlog

from ..base import BaseTool, ToolResult
from ..registry import register_tool
from ._speaker import resolve_speaker

log = structlog.get_logger()


@register_tool
class RecallProposeTool(BaseTool):
    """Propose a permanent memory (owner- or speaker-scoped). Requires owner approval."""

    @property
    def name(self) -> str:
        return "recall_propose"

    @property
    def description(self) -> str:
        return (
            "Propose something to remember PERMANENTLY. This does not take effect right away — "
            "it goes to the bot owner for approval, and once approved it's available via "
            "recall_read in future conversations. Use it in two cases:\n"
            "- scope='owner': a durable fact or preference about the OWNER that should apply in "
            "every conversation (e.g. 'the owner prefers metric units').\n"
            "- scope='speaker': something about — or that was requested by — the PERSON you're "
            "talking to right now, so you remember it next time they return (e.g. 'Ross is "
            "allergic to shellfish', or Ross saying 'remember that I run the Tuesday standup'). "
            "You do NOT provide who the speaker is — their identity is taken from the "
            "authenticated session automatically.\n"
            "Do not use this for throwaway, in-the-moment context — that's recall_write. "
            "Always include a clear reason; the owner sees it when deciding whether to approve."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "What to remember. Specific and self-contained — it must make sense on its own in a future conversation.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["owner", "speaker"],
                    "description": "'owner' = a lasting fact about the owner (global). 'speaker' = about/for the person currently talking (remembered for their future visits).",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this is worth remembering permanently. The owner reads this when approving.",
                },
                "source": {
                    "type": "string",
                    "description": "Where this came from (this conversation, a tool result, a URL). Optional.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for later search (e.g., ['preference', 'allergy']).",
                },
            },
            "required": ["content", "scope", "reason"],
        }

    def credential_keys(self) -> list[str]:
        return []

    async def execute(self, content: str, scope: str, reason: str, source: str = "", tags: list[str] = None, **kwargs) -> ToolResult:
        from ...db import get_pool

        pool = get_pool()
        if not pool:
            return ToolResult.fail("Database not available — recall skill requires database configuration")

        scope = scope if scope in ("owner", "speaker") else "owner"
        tags = tags or []
        who = await resolve_speaker(self)

        if scope == "speaker" and not who["speaker_id"]:
            return ToolResult.fail(
                "Can't propose a speaker-scoped memory: the current speaker couldn't be identified. "
                "Use scope='owner' if this is a fact about the owner instead."
            )

        speaker_id = who["speaker_id"] if scope == "speaker" else None
        speaker_label = who["speaker_label"] if scope == "speaker" else None

        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO recall_entries
                        (content, source, reason, tags, scope, status,
                         speaker_id, speaker_label, source_interface, session_id)
                    VALUES ($1, $2, $3, $4, $5, 'pending', $6, $7, $8, $9)
                    RETURNING id, status, expires_at
                    """,
                    content, source, reason, tags, scope,
                    speaker_id, speaker_label, who["source_interface"], who["session_id"],
                )
            log.info("recall_proposed", id=row["id"], scope=scope, speaker=speaker_id)
            target = "for you (owner-scoped)" if scope == "owner" else f"about {speaker_label or 'this person'} (speaker-scoped)"
            return ToolResult.ok({
                "id": row["id"],
                "scope": scope,
                "status": row["status"],
                "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
                "message": (
                    f"Proposed {target}. It's pending the owner's approval and is NOT remembered yet — "
                    "once approved it will surface via recall_read in future conversations."
                ),
            })
        except Exception as e:
            log.error("recall_propose_error", error=str(e))
            return ToolResult.fail(f"Failed to propose memory: {e}")
