# WilAI security / data architecture (design only)

This is **not installed or deployed**. Code changes for the public site are handled
by GitHub and FTPS; authenticated data edits need a separate PHP API.

## Responsibilities
- GitHub Actions: Python analysis, scheduled transforms, tests, and building public archives.
- Netafraz E1: static public web, PHP 8 + PDO MySQL API, a small metadata database,
  confidential text files outside the web document root if hosting permits.
- ChatGPT: authenticated actions through an explicitly configured connector or via
  GitHub for code edits. It cannot log in to DirectAdmin by itself.
- Independent backup: daily external versioned copies of private texts and database;
  do not consider GitHub Actions artifacts (3-day retention) an archive.

## Public vs staff data
- Public: only content from the explicit allowlist in scripts/build_wilai_public.py.
- Staff: separate private storage and server-side authorization checks.
- Admin: role-specific access; edits require audit logs and validation.
- Explicit 'public' status required before a document can be published.
- On E1 one database is sufficient: use separate tables rather than requiring
  additional databases.

## Phase 2 API contract (not yet implemented)
- GET /api/health: minimal non-sensitive service availability.
- GET /api/v1/documents: authenticated scoped list / search.
- POST /api/v1/documents: authenticated ingest with size limits and content hash.
- PATCH /api/v1/documents/{id}: authorized metadata revisions.
- GET /api/v1/documents/{id}/text: authorized text download (never public URL).
- POST /api/v1/publish/{id}: explicit authorized promotion to public;
  validate content and retain historical revisions.
- GET /api/v1/audit: admin-only event log.

## Required controls
HTTPS only; strong password hashing; access sessions with HttpOnly, Secure, SameSite
cookies and CSRF protection; machine-to-machine access via scoped rotating tokens
stored only as hashes; deny public directory listing and script execution in upload
directories; never publish complete raw transcript folders or private user data.
Rate-limit login and write endpoints; separate read/write scopes. Log each mutation,
maintain immutable offsite backups, and perform restore tests.

A hosted MCP-compatible broker might be needed because E1 does not run permanent
Python/Node servers. Never expose unrestricted SQL execution or a generic command shell
to ChatGPT. Implement only narrow reviewable business operations.

## Existing content and migration
Preserve GitHub as source of truth for the existing public `docs/data` archive until
an independently verified migration succeeds. Index entries are year-partitioned.
Build full transcript storage separately; do not infer that the current public
archive contains complete raw transcripts. Reconcile counts and SHA-256 hashes
before switching consumers; avoid destructive sync operations.

## Proposed SQL
See `infrastructure/wilai/001_schema.sql`. It creates only schema metadata,
not user accounts or credentials. Do not run against production until the PHP
application and backup/recovery procedures have been reviewed.
