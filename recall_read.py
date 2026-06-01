"""
recall_read — bot queries its approved long-term memories.

Only returns entries that have been approved by the bot owner.
Supports filtering by tags and limiting result count.
"""

import structlog

from ..base import BaseTool, ToolResult
from ..registry import register_tool

log = structlog.get_logger()


@register_tool
class RecallReadTool(BaseTool):
    """Query approved recall entries."""

    @property
    def name(self) -> str:
        return "recall_read"

    @property
    def description(self) -> str:
        return (
            "Search your approved long-term memories. "
            "Returns entries that you previously submitted via recall_write "
            "and that the bot owner approved. "
            "Filter by tags or search term, sorted by most recent first."
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
                    "description": "Filter by tags (returns entries matching ANY of the given tags).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of entries to return. Default 20, max 100.",
                    "default": 20,
                },
            },
            "required": [],
        }

    def credential_keys(self) -> list[str]:
        return []

    async def execute(self, query: str = "", tags: list[str] = None, limit: int = 20, **kwargs) -> ToolResult:
        """Query approved recall entries."""
        from ...db import get_pool

        pool = get_pool()
        if not pool:
            return ToolResult.fail("Database not available — recall skill requires database configuration")

        limit = min(max(1, limit), 100)
        tags = tags or []

        try:
            async with pool.acquire() as conn:
                if query and tags:
                    rows = await conn.fetch(
                        """
                        SELECT id, content, source, reason, tags, created_at
                        FROM recall_entries
                        WHERE status = 'approved'
                          AND (content ILIKE $1 OR source ILIKE $1 OR reason ILIKE $1)
                          AND tags && $2
                        ORDER BY created_at DESC
                        LIMIT $3
                        """,
                        f"%{query}%", tags, limit,
                    )
                elif query:
                    rows = await conn.fetch(
                        """
                        SELECT id, content, source, reason, tags, created_at
                        FROM recall_entries
                        WHERE status = 'approved'
                          AND (content ILIKE $1 OR source ILIKE $1 OR reason ILIKE $1)
                        ORDER BY created_at DESC
                        LIMIT $2
                        """,
                        f"%{query}%", limit,
                    )
                elif tags:
                    rows = await conn.fetch(
                        """
                        SELECT id, content, source, reason, tags, created_at
                        FROM recall_entries
                        WHERE status = 'approved'
                          AND tags && $1
                        ORDER BY created_at DESC
                        LIMIT $2
                        """,
                        tags, limit,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT id, content, source, reason, tags, created_at
                        FROM recall_entries
                        WHERE status = 'approved'
                        ORDER BY created_at DESC
                        LIMIT $1
                        """,
                        limit,
                    )

            entries = [
                {
                    "id": row['id'],
                    "content": row['content'],
                    "source": row['source'],
                    "reason": row['reason'],
                    "tags": row['tags'],
                    "created_at": row['created_at'].isoformat(),
                }
                for row in rows
            ]

            return ToolResult.ok({
                "count": len(entries),
                "entries": entries,
            })
        except Exception as e:
            log.error("recall_read_error", error=str(e))
            return ToolResult.fail(f"Failed to query recall entries: {e}")
