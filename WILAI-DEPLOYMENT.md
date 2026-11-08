# WilAI.ir — deployment staging and handover

This is a **draft-only** migration. DNS is pending IrNIC confirmation.
No production server has been accessed; no FTP credentials are configured here.
No site deployment or database migration has taken place.

## Prepared (staging branch only)
- `docs/wilai/index.html`: independent neutral landing page for WilAI.ir.
- `docs/atlas/index.html`: resolves the public archive from the sibling `../data/`
  on HTTP(S) hosting, including GitHub Pages. Local file previews use existing
  public GitHub archive.
- `scripts/build_wilai_public.py`: strict allowlist and verification:
  `atlas/index.html`, `atlas/atlas-pro.css`, `atlas/atlas-pro.js`,
  `atlas/overrides.json`, public year archives and their index files.
  No raw transcripts, credentials, unrelated `docs/data` settings,
  restricted files or internal pages enter the package.
- `tests/test_wilai_public.py`: regression tests for public-only inclusion,
  unexpected archive names and accidental overwrites.
- `.github/workflows/wilai-validate.yml`: validates packages on PRs without secrets.
- `.github/workflows/wilai-ftps-public.yml`: **manually** pushes a package
  via TLS-verified FTPS, only after it is deliberately enabled.

## When IrNIC / DNS confirms WilAI.ir
1. Verify DNS A and NS records correspond to the purchased Netafraz hosting.
2. Enable SSL and verify `https://wilai.ir` from a browser.
3. Confirm Netafraz **explicit FTPS** endpoint/port and exact remote document
   root for this domain. Prefer an FTP account restricted to this site's folder.
4. Confirm Netafraz permits FTP connections from the changing IP ranges used
   by GitHub-hosted runners; test an actual connection.
5. Configure GitHub Actions secrets:
   `WILAI_FTPS_HOST`, `WILAI_FTPS_USER`, `WILAI_FTPS_PASSWORD`.
6. Configure repo variables:
   `WILAI_FTPS_REMOTE_DIR` (confirmed web document root),
   optional `WILAI_FTPS_PORT` (defaults to 21), and only then
   `WILAI_FTPS_ENABLED=true`.
7. Review the `wilai-production` environment protection rules. Do **not**
   store hosting credentials in source files, PR descriptions or chats.
8. Merge reviewed PR after successful CI; run the FTPS workflow manually.
9. Validate home page, `/atlas/`, and `/data/index.json` on HTTPS.
10. Keep GitHub Pages and original archive available until monitoring, backups
    and restore checks succeed.

The uploader intentionally **does not delete remote files**. It only
publishes the public package, and existing GitHub Pages publishing remains
unchanged. DNS confirmation does not itself publish any changes.

## Not implemented yet
- Private staff-only API and database.
- Migrating complete raw transcripts to private Netafraz storage.
- ChatGPT direct management through an authenticated connector.
- Automated continuous deployment to WilAI (manual dispatch only for safety).

Review `WILAI-SECURITY-PLAN.md` and the draft schema at
`infrastructure/wilai/001_schema.sql` before implementing these.
Do not install the schema until backups and access controls are ready.

## Constraints
Netafraz E1 is shared hosting: PHP/MySQL and FTPS, not SSH/SFTP/long-lived
Python services. AI processing stays on GitHub Actions.
The one-database quota makes a small shared metadata schema practical, while
confidential text files must be kept outside the public document root.
Complete raw transcripts in expiring GitHub Actions artifacts are not a backup.
