# Isolated Didban editor webhook — staged change only

This directory deploys ONLY the private Bale admin bot. The three existing calendar Python modules are copied from main without modifying the original versions. No monitoring, transcription, clipping, dubbing, streams, report delivery, or the three fixed Persian program slots run on Vercel.

**Deployment target:** reuse existing Vercel project `didban-bale-calendar-webhook`. Set the project root to `editor_webhook` after verifying team access. Do not deploy the repository root (it carries video processing dependencies).

**Required Vercel environment variables (server-side only):**
- `DIDBAN_CONTROL_BOT_TOKEN`: editor-only Bale token, not `BALE_BOT_TOKEN`.
- `DIDBAN_CONTROL_ADMIN_IDS`: numeric allowlist.
- `DIDBAN_EDITOR_WEBHOOK_SECRET`: high-entropy secret for Bale `setWebhook.secret_token`.
- `DIDBAN_EDITOR_DATABASE_URL`: TLS PostgreSQL connection string.
- `DIDBAN_EDITOR_GITHUB_TOKEN`: fine-grained repo-scoped Contents read/write token.

Create the tables with `schema.sql` using a migration credential. Production database role needs DML only. The webhook is fail-closed when the secret or database is absent. `GET /webhook` is a configuration-status check, NOT proof of live Bale or PostgreSQL connectivity.

**Safe cutover sequence (do not skip):**

1. Review code and test on a preview deployment. Verify an unauthenticated POST gives 403. Confirm Bale actually forwards `X-Telegram-Bot-Api-Secret-Token` when `secret_token` is configured; otherwise do not switch.
2. Test /start, every reply keyboard entry, all wizard steps, duplicate update_id, unauthorized IDs, restart persistence, GitHub downtime, and CAS conflict. Confirm a successful mutation changes the two calendar JSON files in a single Git commit and rejects fixed-slot overlaps.
3. Only after verified operational readiness, change **only** the editor's `poll`, `reply`, and `welcome` steps in `.github/workflows/didban-extra-calendar-dispatch.yml` in a separate reviewed cutover. Leave `extra_schedule.py due` and the dispatch job and all other workflows running.
4. Register `setWebhook` using the editor token only, HTTPS URL ending `/webhook`, `secret_token`, `max_connections=1`, `allowed_updates=["message","callback_query"]`. Verify `getWebhookInfo` and real Bale messages. Never run active editor polling and webhook simultaneously.
5. For rollback, remove ONLY the editor webhook using its token, then restore the previous editor polling steps. Never touch report bot webhooks or the primary monitoring workflows.

**Consistency:** PostgreSQL inbox deduplicates calendar mutations by update_id under an advisory lock and persists session state. Failed Bale sends retry the existing outbox, which can exceptionally duplicate an informational reply if the upstream send succeeded but its acknowledgement was lost. GitHub changes use one Git tree/commit and a non-forced branch ref update. The service doesn't claim end-to-end exactly-once network delivery.

**Offline testing:** `python -m unittest discover -s editor_webhook/tests -v`. Also run parent `tests/test_calendar_bot.py` before changing routing. Offline tests are not real bot, deployed Vercel, or database tests. Root of the live monitor remains unchanged.
