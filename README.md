# SN25 · Mainframe — Token Intelligence Dashboard

Two-page dashboard for Bittensor Subnet 25 (Mainframe), styled on the biotech-index
design system. Data from the **tao.com Data API**.

## Files
- `index.html` — Overview: live stat band, emission value by owner/validator/miner key
  (TAO/day + USD), conviction & staking panel, top validators.
- `wallets.html` — Top 25 SN25 alpha holders, with **Keith** and the flagged taostats
  wallet highlighted. Search + tracked-only filter. Addresses link to tao.com.
- `analytics.html` — Portfolio analysis of the top 5 holders: total stake across every
  subnet, top positions, major SN25 buys, and unrealised PnL on the SN25 position.
- `refresh.py` — pulls fresh data from tao.com and rewrites `data.json`.
- `portfolio.py` — builds `portfolios.json` for the top-5 holders. Runs after `refresh.py`.
- `data.json` — the data the pages load on open.
- `portfolios.json` — what `analytics.html` loads.

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
  network validator list (726 validators). Green = SN25 owner (#1); purple = Keith's three
  wallets (#2, #4, #5); gold = named entities; ◆ marks validators. Macrocosmos is the only
  validator among the top 25, verified against every network validator; the rest are
  anonymous wallets with no on-chain identity. Keith's wallets are set in `MANUAL_LABELS`
  in `refresh.py`, so the tags survive every refresh.
- **Conviction positions** are listed under the % headline: only 2 locks exist on SN25,
  dominated by Keith's coldkey (318,072 α, perpetual, to the owner hotkey).
- **Subnet owner:** `5F6aRds…GiZ4D` (holder #1) is the SN25 owner (taostats Get Subnet Owner;
  on-chain identity "Owner25"). `5FRXwb2q…ypuqjG` (#5) is the Macrocosmos **validator** coldkey.
- **taostats rate limits:** the key is bucket-limited. `refresh.py` throttles taostats calls
  to ~3s and backs off on 429; a full refresh takes ~30–40s. Don't run it in tight loops.

## Portfolio page (`analytics.html`)

`portfolio.py` profiles the five largest holders using two taostats sources:
`dtao/stake_balance/latest` for every subnet position they hold, and the SN25
`delegation` ledger for the stake they added and removed.

**SN25 PnL** is unrealised, on the alpha still held, and denominated in TAO so it
reflects the SN25 trade rather than TAO's own USD move. Cost basis runs a
weighted-average cost book over the ledger in chronological order: adds increase the
carried cost, disposals retire it pro-rata. Averaging over gross buys instead would
charge a wallet for lots it had already sold. That is what made a wallet holding only
freshly-bought alpha look 38% under water in an early build.

**When PnL is withheld.** A wallet can hold alpha the ledger does not explain: stake
moved between hotkeys or subnets is not a delegation event, and emissions arrive with no
purchase at all. `portfolio.py` tracks `coverage` (the share of the current position the
book accounts for) and reports no PnL below 50%, rather than marking a whole position
against a fraction of its cost. The SN25 owner sits at ~16% coverage for exactly this
reason and shows "not reportable".

**API notes.**
- taostats sits behind Cloudflare, which 1010-blocks urllib's default User-Agent. Both
  scripts send an explicit `User-Agent`; without it every call 403s.
- On `/api/delegation/v1` only `nominator` filters. A `coldkey` param is silently ignored
  and returns the whole 118k-row subnet ledger. `transfer_address` catches stake
  transferred *into* a wallet, which the nominator view does not show.
- Pagination is verified against `total_items` and raises on a short read. A swallowed
  rate-limit error would otherwise truncate a ledger and produce a plausible but wrong
  cost basis. An early build silently reported 0 buys for a wallet that has 587.
