# Instar Skill: Recall

A [Project Instar](https://github.com/thegman54/project-instar) skill that gives your bot long-term memory with an approval workflow. The bot stores things it wants to remember, you approve or reject them, and approved entries become queryable.

## Tools

| Tool | Permission Level | Description |
|---|---|---|
| `recall_read` | Read | Bot queries its approved long-term memories |
| `recall_write` | Write (approval required) | Bot submits new entries — owner must approve before they're queryable |

Read and write are **separate tools** with independent permissions. The bot can only read memories you've approved. Unapproved entries expire after 7 days.

## How It Works

```
Bot finds something worth remembering
  └─► recall_write (content, source, reason, tags)
        └─► Entry saved as "pending" in database
              └─► Owner sees it in Admin UI → Recall page
                    ├─► Approve → entry becomes queryable via recall_read
                    └─► Reject → entry stays but is excluded from queries
                          └─► Unapproved entries expire after 7 days
```

1. Install this skill via the Admin UI
2. Create grants:
   - Grant with `recall_read` — bot can search its approved memories
   - Grant with `recall_write` — bot can submit new memories for approval
3. Bot uses `recall_write` to store things it finds (URLs, facts, preferences, etc.)
4. Review pending entries in **Admin UI > Recall**
5. Approved entries are returned by `recall_read` — sorted by most recent, filterable by tags or text search

## Database Requirement

This skill requires database access (`database: true` in manifest). On install, it automatically runs migrations to create the `recall_entries` table. The tool executor must have `DATABASE_URL` configured (included by default in the Instar docker-compose).

### Migration: `001_create_recall_entries.sql`

Creates:
- `recall_entries` table with content, source, reason, tags, status, timestamps
- Indexes on status, created_at (DESC), and tags (GIN for array search)

## Recall Entry Fields

| Field | Description |
|---|---|
| `content` | The information to remember (required) |
| `source` | Where the bot found it — URL, conversation, tool output |
| `reason` | Why the bot wants to remember it (required) |
| `tags` | Searchable tags for categorization |
| `status` | `pending` → `approved` or `rejected` |
| `expires_at` | Pending entries expire after 7 days if unreviewed |

## Query Examples

```
recall_read()                           → last 20 approved entries
recall_read(tags=["python"])            → entries tagged "python"
recall_read(query="API rate limit")     → text search across content/source/reason
recall_read(query="auth", tags=["security"], limit=5)  → combined filters
```

## File Structure

```
recall/
├── manifest.yaml                              # Skill metadata (database: true)
├── __init__.py                                 # Imports tool classes
├── recall_read.py                             # Read tool — query approved entries
├── recall_write.py                            # Write tool — submit for approval
└── migrations/
    └── 001_create_recall_entries.sql           # Creates recall_entries table
```

## Installation

### Via Admin UI (Recommended)

1. Download this repo as a zip
2. In the Instar Admin UI, go to **Tools**
3. Click **Upload** and select the zip
4. Migrations run automatically on upload
5. Review pending entries at **Admin UI > Recall**

### Manual

```bash
git clone https://github.com/thegman54/instar-skill-recall.git
cp -r instar-skill-recall/ /path/to/project-instar/tool-executor/src/tools/recall/
```

Restart the tool executor to trigger migrations.

## License

MIT
