# SN25 · Mainframe — Token Intelligence Dashboard

Two-page dashboard for Bittensor Subnet 25 (Mainframe), styled on the biotech-index
design system. Data from the **tao.com Data API**.

## Files
- `index.html` — Overview: live stat band, emission value by owner/validator/miner key
  (TAO/day + USD), conviction & staking panel, top validators.
- `wallets.html` — Top 25 SN25 alpha holders, with **Keith** and the flagged taostats
  wallet highlighted. Search + tracked-only filter. Addresses link to tao.com.
- `refresh.py` — pulls fresh data from tao.com and rewrites `data.json`.
- `data.json` — the data both pages load on open.

## How "live" works
The tao.com API needs a signed token and sends no CORS headers, so a static page can't
call it directly from the browser (and embedding the secret would expose it). Instead:

1. `refresh.py` (holds the key server-side) hits the API and writes `data.json`.
2. The pages fetch `./data.json` on load. If it's missing/blocked, they render an
   embedded snapshot and show an amber **SNAPSHOT** badge; otherwise a green **LIVE** badge
   with the timestamp.

**Refresh the data:**
```bash
python3 refresh.py
```
Schedule it (cron/launchd) or run on demand. To serve locally so `data.json` loads:
```bash
python3 -m http.server 8080   # then open http://localhost:8080/index.html
```

## Deploy (GitHub Pages)
Drop all four files in a repo and enable Pages. Add a scheduled GitHub Action running
`python3 refresh.py` to commit fresh `data.json` on a cadence. The API key currently
lives in `refresh.py` — move it to a secret/env var before pushing to a public repo.

## Overview sections
- **SN25 rank on Bittensor** — subnets ranked by alpha price / FDV (the metric that
  matches the tao.com subnet leaderboard). Shows SN25's neighbours (±3) plus pinned comps
  Bitcast SN93, TrajectoryRL SN11, Endure Network SN30. Columns: rank, subnet, market cap, 7d.
- **Bittensor Conviction** — live % of circulating SN25 alpha locked via the `lock_stake`
  mechanism (taostats `GET /api/conviction/latest/v1`). Currently ~6% (2 locks); the
  dominant lock is Keith's coldkey.
- Emissions by key, holders & staking, top validators — as before.

## Notes
- SN25 emissions show 100% incentive burn; figures are scheduled TAO-denominated emission.
- **Wallet tags:** top-25 holders tagged from taostats identity, exchange, and the full
  network validator list (726 validators). Green = SN25 owner (#1); purple = Keith's two
  wallets (#2, #4); gold = named entities; ◆ marks validators. Only Macrocosmos (#5) is a
  validator among the top 25 — verified against every network validator; the rest are
  anonymous wallets with no on-chain identity.
- **Conviction positions** are listed under the % headline: only 2 locks exist on SN25,
  dominated by Keith's coldkey (318,072 α, perpetual, to the owner hotkey).
- **Subnet owner:** `5F6aRds…GiZ4D` (holder #1) is the SN25 owner (taostats Get Subnet Owner;
  on-chain identity "Owner25"). `5FRXwb2q…ypuqjG` (#5) is the Macrocosmos **validator** coldkey.
- **taostats rate limits:** the key is bucket-limited. `refresh.py` throttles taostats calls
  to ~3s and backs off on 429; a full refresh takes ~30–40s. Don't run it in tight loops.
