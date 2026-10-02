# token-metrics leaderboard

The backend for the plugin's opt-in sync. It runs the internal leaderboard, public share cards (`/u/<handle>`) and company-wide results (`/admin`). It's a Next.js app on Vercel with Postgres for storage and Resend for sign-in emails.

## Deploy

1. Create a Vercel project with **root directory `leaderboard/`**. Company use needs a Pro team, because Hobby is non-commercial only.
2. Add Neon Postgres from the Vercel Marketplace. It sets `DATABASE_URL`. Then apply the schema once: `DATABASE_URL=... npm run db:init`.
3. In Resend, verify a sending domain (DNS records on devxlabs.ai). Then set the environment variables listed in `.env.example`: `RESEND_API_KEY`, `EMAIL_FROM`, `ALLOWED_DOMAINS`, `ADMIN_EMAILS` and `PUBLIC_URL`.
4. Set `DEFAULT_URL` in `plugins/token-metrics/scripts/share.py` to the production URL and bump the plugin version. Until then, users need `CC_METRICS_SHARE_URL`.

## Local

```bash
npm install
DATABASE_URL=postgres://localhost/token_metrics npm run db:init
DATABASE_URL=postgres://localhost/token_metrics ADMIN_EMAILS=you@devxlabs.ai npm run dev
```

Without `RESEND_API_KEY`, sign-in codes are printed to the server log.
