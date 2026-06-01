"""
recall_write — bot submits something it wants to remember.

Entry goes into 'pending' state. The bot owner must approve it
through the Admin UI before it becomes queryable via recall_read.
Unapproved entries expire after 7 days by default.
"""

import structlog

from ..base import BaseTool, ToolResult
from ..registry import register_tool

log = structlog.get_logger()


@register_tool
class RecallWriteTool(BaseTool):
    """Submit a memory entry for owner approval."""

    @property
    def name(self) -> str:
        return "recall_write"

    @property
    def description(self) -> str:
        return (
            "Store something you want to remember long-term. "
            "The entry goes into a pending state — the bot owner must approve it "
            "before it becomes available via recall_read. "
            "Include a reason explaining why this is worth remembering."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The information to remember. Be specific and self-contained.",
                },
                "source": {
                    "type": "string",
                    "description": "Where you found this (URL, conversation context, tool output, etc.)",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this is worth remembering.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorization and search (e.g., ['python', 'security', 'user-preference']).",
                },
            },
            "required": ["content", "reason"],
        }

    def credential_keys(self) -> list[str]:
        return []

    async def execute(self, content: str, reason: str, source: str = "", tags: list[str] = None, **kwargs) -> ToolResult:
        """Submit a recall entry for approval."""
        from ...db import get_pool

        pool = get_pool()
        if not pool:
            return ToolResult.fail("Database not available — recall skill requires database configuration")

        tags = tags or []

        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO recall_entries (content, source, reason, tags)
                    VALUES ($1, $2, $3, $4)
                    RETURNING id, status, expires_at
                    """,
                    content, source, reason, tags,
                )

            log.info("recall_entry_submitted", id=row['id'], tags=tags)
            return ToolResult.ok({
                "id": row['id'],
                "status": row['status'],
                "expires_at": row['expires_at'].isoformat() if row['expires_at'] else None,
                "message": "Memory submitted for approval. It will be available via recall_read once approved.",
            })
        except Exception as e:
            log.error("recall_write_error", error=str(e))
            return ToolResult.fail(f"Failed to submit recall entry: {e}")
