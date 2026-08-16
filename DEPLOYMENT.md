# Deploying Arbitrium

Backend + Postgres on **Fly.io**, frontend on **Vercel**.

Everything in this file has been prepared and locally verified — the production
image builds, both process commands import, and the release command resolves the
migration head. The `fly`/`vercel` steps themselves require account credentials
and have **not** been run.

---

## Why Fly rather than Railway

The deciding factor is the scheduler, not the API.

This app has a long-running poller that must never stop: it holds per-source
interval state in memory, adapts the Odds API cadence to the next kickoff, and
accumulates append-only history that **cannot be backfilled** — the scores feed
only reaches back three days, so a gap is permanent. A deployed API with a dead
scheduler is the original week-long outage wearing a different hat.

Fly's `[processes]` maps that requirement directly: one image, two process
groups (`api`, `scheduler`), mirroring `docker-compose.yml` exactly, with
`auto_stop_machines = false` and `min_machines_running = 1` so neither can be
scaled to zero. Railway would work, but needs two separately-configured
services from the same repo and its idle-sleep behaviour is the wrong default
for a process whose entire job is to not stop.

**The scheduler is a process group, not a cron job**, deliberately. Cron would
reset the adaptive interval state on every invocation and spend Odds API credits
at the wrong rate — the pacing that keeps the ~500 credits/month budget alive
depends on the process staying up.

---

## 1. Backend — Fly.io

```bash
brew install flyctl        # not currently installed on this machine
fly auth login

fly apps create arbitrium-api

# Managed Postgres, attached as DATABASE_URL
fly postgres create --name arbitrium-db --region iad
fly postgres attach arbitrium-db --app arbitrium-api
```

`fly postgres attach` sets `DATABASE_URL` automatically, but it writes a
`postgres://` URL. This app uses the psycopg 3 driver, so it must be
`postgresql+psycopg://`:

```bash
fly secrets set --app arbitrium-api \
  DATABASE_URL="postgresql+psycopg://<user>:<pass>@<host>:5432/<db>"
```

Then the API credentials — **never committed**:

```bash
fly secrets set --app arbitrium-api \
  KALSHI_API_KEY_ID="..." \
  KALSHI_PRIVATE_KEY="$(cat path/to/kalshi_private_key.pem)" \
  ODDS_API_KEY="..."
```

Deploy. `fly.toml` runs migrations as the release command before new machines
take traffic:

```bash
fly deploy
fly scale count api=1 scheduler=1
```

Verify both groups are up — this matters more than the API responding:

```bash
fly status                      # expect one api machine AND one scheduler machine
fly logs --app arbitrium-api    # scheduler should log its resolved intervals
curl https://arbitrium-api.fly.dev/health
```

---

## 2. Frontend — Vercel

```bash
npm i -g vercel                 # not currently installed on this machine
cd frontend
vercel link
vercel env add BACKEND_URL production     # https://arbitrium-api.fly.dev
vercel --prod
```

**No CORS configuration is needed**, and this is by design rather than luck:
the browser never calls FastAPI. Server components fetch it over `BACKEND_URL`,
and client polling goes through the Next route handler at `/api/be/[...path]`,
which forwards an allowlist of GET endpoints. The backend origin is never sent
to the browser, so there is no cross-origin request to permit.

`BACKEND_URL` is a **server-side** variable — deliberately not `NEXT_PUBLIC_`.
Prefixing it would ship the backend origin to every visitor and defeat the proxy.

---

## 3. Keeping the scheduler honest

`fly.toml` prevents the scheduler being scaled to zero, but it cannot detect the
process being alive and silently doing nothing — which is precisely the failure
mode this project has already hit twice.

Point an external uptime monitor (UptimeRobot, Better Stack, both free) at:

```
https://arbitrium-api.fly.dev/health?strict=true
```

`strict=true` returns **503** instead of 200 when any source is stale or the
resolution countdown is at risk. Plain `/health` stays 200 with a degraded body,
because the dashboard needs to render the reason — a monitor needs a status
code, a human needs the explanation, and conflating them serves neither.

Suggested cadence: every 5 minutes, alert after two consecutive failures.

Fly's own health check in `fly.toml` deliberately hits plain `/health`, not the
strict variant: restarting the API because ingestion is stale would be the wrong
remedy for the wrong problem.

---

## Environment variables

| Where | Name | Notes |
|---|---|---|
| Fly | `DATABASE_URL` | must use the `postgresql+psycopg://` scheme |
| Fly | `KALSHI_API_KEY_ID` | secret |
| Fly | `KALSHI_PRIVATE_KEY` | secret, PEM contents |
| Fly | `ODDS_API_KEY` | secret |
| Vercel | `BACKEND_URL` | `https://arbitrium-api.fly.dev`, server-side only |

Nothing above belongs in git. `.env` is gitignored; `.env.example` carries the
names and comments only.

---

## Post-deploy verification

Do not call it done until all four pass:

1. `https://arbitrium-api.fly.dev/health` → `"status": "ok"`, both sources present.
2. `fly status` → an `api` machine **and** a `scheduler` machine running.
3. The Vercel URL loads the dashboard with real events, and the header status
   pill reads `Live`.
4. Wait one Kalshi poll interval (5 min) and re-check `/health` — `age_seconds`
   for `kalshi` should have **reset**, proving the deployed scheduler is
   actually writing, not merely running.

Step 4 is the one that matters. The first three would all pass with a scheduler
that starts, does nothing, and stays up.
