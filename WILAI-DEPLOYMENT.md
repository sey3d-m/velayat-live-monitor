# WilAI.ir | staging deployment plan

This proposal is deliberately non-destructive. **Nothing automatically deploys when merged.**
The manual deployment workflow starts only when repository variable `WILAI_FTPS_ENABLED`
equals `true`. Keep it unset until the host, DNS and deployment directory are validated.

## Scope

- Existing GitHub Actions processing remains on GitHub.
- Existing GitHub Pages site and archive remain active.
- Initial upload copies only the **already-public** `docs/atlas/**` and `docs/data/**`
  to `wilai.ir/atlas/` and `wilai.ir/data/` respectively.
- The FTPS mirror intentionally does NOT use `--delete`.
- It does not upload raw transcripts, production artifacts, credentials, or internal data.
- The Atlas reads a sibling `../data/` directory on HTTP(S); local `file:` testing retains
  the existing GitHub Pages fallback.
- This is not the private employee panel, not a MySQL migration, not a backup replacement,
  and not a ChatGPT-to-host management integration. Those require a separate authenticated API.

## Configure after buying hosting

In Netafraz DirectAdmin:
1. Attach `wilai.ir` and its DNS records to this hosting account.
2. Provision SSL and verify `https://wilai.ir` is reachable.
3. Obtain the FTPS host and dedicated deploy username/password if supported.
4. Identify the **exact** remote document root for `wilai.ir` (do not guess).
5. Confirm explicit FTPS with TLS works from an external GitHub-hosted runner.

In GitHub repository Settings > Secrets and variables > Actions:
- Secrets: `WILAI_FTPS_HOST`, `WILAI_FTPS_USER`, `WILAI_FTPS_PASSWORD`.
- Variables: `WILAI_FTPS_REMOTE_DIR` (document root from host), optionally
  `WILAI_FTPS_PORT` (defaults to 21).
- After setup and review, set variable `WILAI_FTPS_ENABLED` to `true`.
- Use the `wilai-production` GitHub environment to restrict who can deploy.

Run the manual workflow **only after** validating the remote directory. Test
`https://wilai.ir/atlas/` and `https://wilai.ir/data/index.json` afterward.
Archive and overrides on GitHub remain the authoritative source for this phase.

## Safety and limitations

GitHub Actions runner IPs vary; Netafraz may need to permit FTPS connections from
external networks. Confirm successful connection empirically before relying on it.
FTPS protects credentials and data with TLS, but is distinct from SFTP/SSH.

Published `docs/data` is public. Do NOT add staff-only reports or complete raw
transcripts to it. A separate PHP/MySQL API with authentication and off-webroot
storage is needed for private uploads, staff roles, and ChatGPT actions.
Create independent verified backups before moving or changing source-of-truth data.
