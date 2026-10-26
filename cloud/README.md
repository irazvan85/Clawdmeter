# Clawdmeter cloud dashboard

A read-only page for checking the device from outside your LAN. It runs on the
Vercel Hobby (free) plan with Upstash Redis (free tier).

```
device --LAN--> host daemon --HTTPS, signed--> Vercel /api/ingest --> Upstash Redis
                                                 browser --GitHub sign-in--> / and /api/snapshot
```

## Security model

- **Outbound only.** The daemon pushes; nothing on your LAN accepts inbound
  connections, and the cloud has no route back to the device. The page can't
  change screens, settings or calibration.
- **Signed ingest.** `POST /api/ingest` requires `X-Clawd-Ts` and
  `X-Clawd-Sig` (hex HMAC-SHA256 of `"<ts>.<body>"`, keyed with
  `INGEST_HMAC_SECRET`). Requests more than 5 minutes off are rejected, and so
  is any timestamp not newer than the last accepted one (no replays). Bodies
  are capped at 32 KB. Size, signature and schema are all checked before Redis
  is touched, so junk traffic can't spend the free quota.
- **Strict schema.** Every object rejects unknown fields (`src/lib/schema.ts`),
  and links must be `https://github.com/...`.
- **Data minimisation.** The daemon sends a field-by-field allowlist
  (`daemon/cloud_push.py`). It never sends the device token, IPs or VS Code
  error text. Weather (your city), Checks (repo names and PR titles) and VS Code
  are opt-in.
- **Owner-only reads.** Sign-in is GitHub OAuth, accepted for one numeric
  GitHub user id (`ALLOWED_GITHUB_ID`). Every request re-checks the id. Signed
  out, `/` renders no device data and `/api/snapshot` returns 401.
- **Headers.** CSP, `frame-ancestors 'none'`, `no-referrer`, HSTS, `noindex`,
  and `no-store` on data.

Vercel's own Deployment Protection can't cover the production domain on Hobby,
so the app enforces access itself. Keep Standard Protection on for previews.

## Setup

1. **Vercel project.** Import this repo with *Root Directory* set to `cloud`.
2. **Upstash Redis.** Project → Storage → Marketplace → Upstash → Redis, free
   plan, connected to this project. It injects `KV_REST_API_URL` and
   `KV_REST_API_TOKEN`.
3. **GitHub OAuth app** (github.com → Settings → Developer settings → OAuth Apps):
   - Homepage URL: `https://<project>.vercel.app`
   - Callback URL: `https://<project>.vercel.app/api/auth/callback/github`
4. **Environment variables** (Production). Mark secrets *Sensitive*.

   | Key | Value |
   | --- | --- |
   | `GITHUB_ID` / `GITHUB_SECRET` | from the OAuth app |
   | `ALLOWED_GITHUB_ID` | your numeric id: `gh api user --jq .id` |
   | `NEXTAUTH_SECRET` | 32+ random bytes |
   | `NEXTAUTH_URL` | `https://<project>.vercel.app` (needed so OAuth callbacks use the production domain) |
   | `INGEST_HMAC_SECRET` | 32+ random characters, the same value as the daemon's `cloud_secret` |

5. **Redeploy**, then add to the daemon config
   (`~/.config/claude-usage-monitor/config`) and restart the daemon:

   ```
   cloud_url = https://<project>.vercel.app
   cloud_secret = <INGEST_HMAC_SECRET>
   # cloud_sections = weather, ci, vscode   (optional extras)
   ```

## Free-tier budget

At one push a minute: about 43k function invocations a month (the limit is 1M),
and about 175k Redis commands for ingest plus 2 per page poll (the limit is
500k).

## Develop

```
npm install
npm test           # vitest: signing, schema (shared fixture), routes, auth
npm run typecheck
npm run build
```
