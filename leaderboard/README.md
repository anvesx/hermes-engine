# token-metrics leaderboard

The backend for the plugin's opt-in sync. It runs the internal leaderboard, public share cards and each user's own dashboard (`/u/<handle>`) and company-wide results (`/admin`). It's a Next.js app on Vercel with Postgres for storage and Gmail SMTP (nodemailer) for sign-in emails.

## Deploy

1. Create a Vercel project with **root directory `leaderboard/`**. Company use needs a Pro team, because Hobby is non-commercial only.
2. Add Neon Postgres from the Vercel Marketplace. It sets `DATABASE_URL`. Then apply the schema: `DATABASE_URL=... npm run db:init`. It is idempotent; rerun it after deploys that add tables (1.5.0 added `login_links` for the dashboard sign-in links).
3. Create a Google app password for the sending Gmail account (needs 2-Step Verification). Then set the environment variables listed in `.env.example`: `SMTP_USER`, `SMTP_PASS`, `EMAIL_FROM`, `ALLOWED_DOMAINS`, `ADMIN_EMAILS` and `PUBLIC_URL`. `SMTP_HOST`/`SMTP_PORT` default to Gmail.
4. `DEFAULT_URL` in `plugins/token-metrics/scripts/share.py` holds the production URL (https://token-metrics-leaderboard.vercel.app). If it changes, update it and bump the plugin version; until users update, they need `CC_METRICS_SHARE_URL`.

## Local

```bash
npm install
DATABASE_URL=postgres://localhost/token_metrics npm run db:init
DATABASE_URL=postgres://localhost/token_metrics ADMIN_EMAILS=you@devxlabs.ai npm run dev
```

Without `SMTP_USER`/`SMTP_PASS`, sign-in codes are printed to the server log.
