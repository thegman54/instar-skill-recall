"""
recall_write — jot an ephemeral note for the CURRENT conversation only.

This is your short-term scratchpad. Notes written here are readable via recall_read for the
rest of THIS conversation and then disappear — they are never approved, never permanent, and
never visible to other speakers or future sessions. For anything that should outlive the chat,
use recall_propose instead.
"""

import structlog

from ..base import BaseTool, ToolResult
from ..registry import register_tool
from ._speaker import resolve_speaker

log = structlog.get_logger()


@register_tool
class RecallWriteTool(BaseTool):
    """Write an ephemeral, session-scoped note (no approval, gone when the conversation ends)."""

    @property
    def name(self) -> str:
        return "recall_write"

    @property
    def description(self) -> str:
        return (
            "Jot a quick note to yourself for the CURRENT conversation only. "
            "Use this to hold context you'll want a few turns from now — a decision the user "
            "made, a value they gave you, a thread to pick back up. "
            "It is readable via recall_read for the rest of this conversation, then it vanishes. "
            "This is ephemeral: it is NOT approved, NOT permanent, and NOT shared with other "
            "people or future sessions. "
            "If something should be remembered permanently — a lasting fact about the owner, or "
            "something a person asks you to remember about them for next time — use recall_propose "
            "instead, which routes it to the owner for approval."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The note. Be specific and self-contained — write it so it makes sense to you later without the surrounding conversation.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags to find it again (e.g., ['booking', 'preference']).",
                },
            },
            "required": ["content"],
        }

    def credential_keys(self) -> list[str]:
        return []

    async def execute(self, content: str, tags: list[str] = None, **kwargs) -> ToolResult:
        from ...db import get_pool

        pool = get_pool()
        if not pool:
            return ToolResult.fail("Database not available — recall skill requires database configuration")

        tags = tags or []
        who = await resolve_speaker(self)

        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO recall_entries
                        (content, source, reason, tags, scope, status,
                         speaker_id, speaker_label, source_interface, session_id, expires_at)
                    VALUES ($1, $2, $3, $4, 'session', 'session', $5, $6, $7, $8, now() + INTERVAL '12 hours')
                    RETURNING id
                    """,
                    content, "session note", "", tags,
                    who["speaker_id"], who["speaker_label"], who["source_interface"], who["session_id"],
                )
            log.info("recall_session_note", id=row["id"], session=who["session_id"])
            return ToolResult.ok({
                "id": row["id"],
                "scope": "session",
                "message": "Noted for this conversation. It will be available via recall_read until the chat ends, then it's gone. Use recall_propose to remember something permanently.",
            })
        except Exception as e:
            log.error("recall_write_error", error=str(e))
            return ToolResult.fail(f"Failed to write session note: {e}")
