#!/usr/bin/env python3
"""
SN25 (Mainframe) top-holder portfolio builder.

For each of the top 5 SN25 alpha holders (the coldkeys ranked 1-5 in data.json),
this pulls two things from taostats and writes portfolios.json, which
analytics.html renders:

  - dtao/stake_balance/latest  -> every subnet position the coldkey holds. Gives
    the total portfolio value and the top-5 positions across all subnets.
  - delegation                 -> the coldkey's full SN25 stake add/remove ledger.
    Gives the major buys and the TAO-weighted average purchase price.

SN25 PnL is denominated in TAO, the funding asset. The alpha still held is marked
at the live SN25 alpha price and compared to the TAO-weighted average price paid
for it. Denominating in TAO isolates the SN25 bet from TAO's own USD move; the USD
figures are shown alongside for readability.

Run AFTER refresh.py: it reads data.json for live prices, the top-5 coldkeys, and
their labels. Values are marked at the same instant as the rest of the dashboard.

Usage:
    TAOSTATS_API_KEY=... python3 portfolio.py
"""
import json, os, sys, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone

TAOSTATS_API_KEY = os.environ.get("TAOSTATS_API_KEY", "")
TS_BASE = "https://api.taostats.io"
NETUID = 25
TOP_N = 5                 # number of holders to profile
MAX_POSITIONS = 5         # top positions shown per wallet
MAX_BUYS = 5              # major buys shown per wallet
COVERAGE_MIN = 0.5        # ledger must explain this share of a position to report its PnL
RAO = 1e9                 # rao -> whole-unit divisor

# taostats sits behind Cloudflare, which rejects the default urllib agent with a 1010 block
UA = "sn25-mainframe-intel/1.0 (+https://github.com/haitzupp/sn25-mainframe-intel)"
# taostats is bucket rate-limited; 6s spacing keeps a full run inside the budget
_TS_DELAY = 6.0
_ts_last = [0.0]


def f(x):
    """Coerce a possibly-null/string numeric to float, defaulting to 0.0."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


class TaostatsError(RuntimeError):
    """A taostats call could not be completed. Raised rather than returning partial data."""


def ts_get(path, **params):
    """
    GET a taostats endpoint as JSON, rate-limited with back-off.

    Raises TaostatsError once retries are exhausted. It must never return None on
    failure: callers paginate until there is no next page, so a swallowed error would
    silently truncate a wallet's ledger and produce a plausible but wrong cost basis.
    """
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = TS_BASE + path + ("?" + q if q else "")
    last = "unknown"
    for attempt in range(8):
        gap = time.time() - _ts_last[0]
        if gap < _TS_DELAY:
            time.sleep(_TS_DELAY - gap)
        _ts_last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"Authorization": TAOSTATS_API_KEY,
                                                       "accept": "application/json",
                                                       "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
            if e.code in (403, 429):          # throttled (or Cloudflare-blocked), back off
                time.sleep(4 + attempt * 4)
                continue
            raise TaostatsError("%s -> HTTP %s" % (path, e.code))
        except Exception as e:
            last = type(e).__name__
            time.sleep(3 + attempt * 2)
    raise TaostatsError("%s -> gave up after retries (%s)" % (path, last))


def subnet_names():
    """netuid -> {'name', 'symbol'} for every subnet, from the dtao pool list."""
    out = {}
    d = ts_get("/api/dtao/pool/latest/v1", limit=200)
    for p in d.get("data", []) or []:
        out[p["netuid"]] = {"name": p.get("name") or ("SN%d" % p["netuid"]),
                            "symbol": p.get("symbol") or ""}
    return out


def stake_positions(coldkey, names):
    """All subnet positions for a coldkey, aggregated by netuid and sorted by TAO value."""
    d = ts_get("/api/dtao/stake_balance/latest/v1", coldkey=coldkey, limit=200)
    by_netuid = {}
    for r in d.get("data", []) or []:
        uid = r["netuid"]
        pos = by_netuid.setdefault(uid, {"netuid": uid, "alpha": 0.0, "value_tao": 0.0})
        pos["alpha"] += f(r.get("balance")) / RAO
        pos["value_tao"] += f(r.get("balance_as_tao")) / RAO
    rows = list(by_netuid.values())
    for r in rows:
        meta = names.get(r["netuid"], {})
        r["name"] = meta.get("name", "SN%d" % r["netuid"])
        r["symbol"] = meta.get("symbol", "")
    rows.sort(key=lambda r: r["value_tao"], reverse=True)
    return rows


def _events(param, coldkey, inbound):
    """
    Page one SN25 delegation query into normalised events.

    Only `nominator` filters this endpoint. A `coldkey` param is silently ignored and
    returns the whole subnet ledger, so it must never be used here. `transfer_address`
    catches stake transferred *into* the wallet, which the nominator view does not show.
    """
    out = []
    page = 1
    total = None
    while page <= 40:
        d = ts_get("/api/delegation/v1", netuid=NETUID, limit=200, page=page,
                   order="block_number_asc", **{param: coldkey})
        pag = d.get("pagination") or {}
        if total is None:
            total = pag.get("total_items")
        for r in d.get("data", []) or []:
            # An inbound transfer is an acquisition for the recipient regardless of the
            # action recorded against the sender.
            action = "DELEGATE" if inbound else r.get("action", "")
            out.append({
                "timestamp": r.get("timestamp", ""),
                "action": action,               # DELEGATE = add/buy, UNDELEGATE = remove/sell
                "tao": f(r.get("amount")) / RAO,
                "alpha": f(r.get("alpha")) / RAO,
                "usd": f(r.get("usd")),
                "price_tao": f(r.get("alpha_price_in_tao")),
                "price_usd": f(r.get("alpha_price_in_usd")),
                "is_transfer": inbound or bool(r.get("is_transfer")),
            })
        if not pag.get("next_page"):
            break
        page += 1
    # The ledger drives the cost basis, so a short read is a correctness bug, not a warning.
    if total is not None and len(out) != total:
        raise TaostatsError("%s=%s returned %d of %d events" % (param, coldkey[:8], len(out), total))
    return out


def sn25_ledger(coldkey):
    """Full SN25 acquisition/disposal ledger for a coldkey, oldest-first."""
    events = _events("nominator", coldkey, False) + _events("transfer_address", coldkey, True)
    events.sort(key=lambda e: e["timestamp"])
    return events


def sn25_position(events, current_alpha, price_tao, price_usd):
    """
    Cost basis and unrealised PnL on the SN25 alpha still held.

    Runs a weighted-average-cost book over the ledger in chronological order: adds
    increase the alpha and the TAO/USD cost carried against it, disposals retire cost
    pro-rata at the running average. Averaging over gross buys instead would charge a
    wallet for lots it has already sold, badly misstating anyone who traded in and out.

    The alpha still on-chain is marked at the live price against the cost remaining in
    the book. Alpha received as emissions never appears as an add, so it carries no
    cost and shows up as gain, which is economically correct.

    A wallet can hold alpha the ledger does not explain (stake moved between hotkeys or
    subnets is not a delegation event). `coverage` is the share of the current position
    the book accounts for; below COVERAGE_MIN the basis is not representative and PnL is
    withheld rather than reported against a fraction of the position.
    """
    buys = [e for e in events if e["action"] == "DELEGATE"]
    sells = [e for e in events if e["action"] != "DELEGATE"]

    alpha_book = cost_tao_book = cost_usd_book = 0.0
    for e in sorted(events, key=lambda x: x["timestamp"]):
        if e["action"] == "DELEGATE":
            alpha_book += e["alpha"]
            cost_tao_book += e["tao"]
            cost_usd_book += e["usd"]
        elif alpha_book > 0:
            frac = min(e["alpha"], alpha_book) / alpha_book
            cost_tao_book -= cost_tao_book * frac
            cost_usd_book -= cost_usd_book * frac
            alpha_book -= min(e["alpha"], alpha_book)

    avg_tao = (cost_tao_book / alpha_book) if alpha_book > 0 else 0.0
    avg_usd = (cost_usd_book / alpha_book) if alpha_book > 0 else 0.0
    coverage = (alpha_book / current_alpha) if current_alpha > 0 else 0.0
    available = bool(buys) and alpha_book > 0 and coverage >= COVERAGE_MIN

    cur_value_tao = current_alpha * price_tao
    cur_value_usd = current_alpha * price_usd
    pnl_tao = cur_value_tao - cost_tao_book if available else 0.0
    pnl_usd = cur_value_usd - cost_usd_book if available else 0.0
    pnl_pct = (pnl_tao / cost_tao_book * 100) if available and cost_tao_book else 0.0

    return {
        "current_alpha": current_alpha,
        "current_value_tao": cur_value_tao,
        "current_value_usd": cur_value_usd,
        "basis_available": available,
        "coverage": coverage,
        "book_alpha": alpha_book,
        "avg_buy_price_tao": avg_tao,
        "avg_buy_price_usd": avg_usd,
        "current_price_tao": price_tao,
        "current_price_usd": price_usd,
        "cost_tao": cost_tao_book,
        "cost_usd": cost_usd_book,
        "pnl_tao": pnl_tao,
        "pnl_usd": pnl_usd,
        "pnl_pct": pnl_pct,
        "up": pnl_tao >= 0,
        "n_buys": len(buys),
        "n_sells": len(sells),
        "alpha_bought": sum(e["alpha"] for e in buys),
        "alpha_sold": sum(e["alpha"] for e in sells),
        "first_trade": events[0]["timestamp"][:10] if events else None,
        "last_trade": events[-1]["timestamp"][:10] if events else None,
    }


def major_buys(events):
    """The largest SN25 adds by alpha size, most-significant first."""
    buys = [e for e in events if e["action"] == "DELEGATE"]
    buys.sort(key=lambda e: e["alpha"], reverse=True)
    return [{"date": e["timestamp"][:10], "alpha": e["alpha"], "tao": e["tao"],
             "usd": e["usd"], "price_usd": e["price_usd"], "is_transfer": e["is_transfer"]}
            for e in buys[:MAX_BUYS]]


def build_wallet(holder, names, tao_usd, price_tao, price_usd):
    """Assemble one wallet's portfolio record from its live positions and SN25 ledger."""
    ck = holder["coldkey"]
    positions = stake_positions(ck, names)
    total_tao = sum(p["value_tao"] for p in positions)
    sn25_alpha = next((p["alpha"] for p in positions if p["netuid"] == NETUID), 0.0)
    events = sn25_ledger(ck)

    top = []
    for p in positions[:MAX_POSITIONS]:
        top.append({"netuid": p["netuid"], "name": p["name"], "symbol": p["symbol"],
                    "alpha": p["alpha"], "value_tao": p["value_tao"],
                    "value_usd": p["value_tao"] * tao_usd,
                    "pct": (p["value_tao"] / total_tao * 100) if total_tao else 0.0,
                    "is_sn25": p["netuid"] == NETUID})

    return {
        "rank": holder["rank"],
        "coldkey": ck,
        "label": holder.get("label"),
        "hl": holder.get("hl"),
        "total_value_tao": total_tao,
        "total_value_usd": total_tao * tao_usd,
        "n_positions": len(positions),
        "positions": top,
        "sn25": sn25_position(events, sn25_alpha, price_tao, price_usd),
        "major_buys": major_buys(events),
    }


def main():
    """Read live prices + top-5 coldkeys from data.json, profile each, write portfolios.json."""
    if not TAOSTATS_API_KEY:
        print("TAOSTATS_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    data = json.load(open("data.json"))
    tao_usd = f(data["tao"]["price_usd"])
    price_tao = f(data["subnet"]["price_tao"])
    price_usd = f(data["subnet"]["price_usd"])
    holders = data["holders"][:TOP_N]

    names = subnet_names()
    wallets = [build_wallet(h, names, tao_usd, price_tao, price_usd) for h in holders]

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "taostats dtao stake balances + SN25 delegation ledger. SN25 PnL marks alpha held at the live price vs TAO-weighted average purchase price.",
        "tao_usd": tao_usd,
        "sn25_price_tao": price_tao,
        "sn25_price_usd": price_usd,
        "wallets": wallets,
    }
    with open("portfolios.json", "w") as fh:
        json.dump(out, fh, indent=2)

    print("portfolios.json @ %s | %d wallets | tao $%.2f | sn25 $%.4f" % (
        out["generated_at"], len(wallets), tao_usd, price_usd))
    for w in wallets:
        s = w["sn25"]
        pnl = ("%s%.1f%%" % ("+" if s["up"] else "", s["pnl_pct"])) if s["basis_available"] \
            else "n/a (%.0f%% covered)" % (s["coverage"] * 100)
        print("  #%d %-11s total $%s | sn25 %s | %d pos | %db/%ds" % (
            w["rank"], (w["label"] or "anon")[:11], format(int(w["total_value_usd"]), ","),
            pnl, w["n_positions"], s["n_buys"], s["n_sells"]))


if __name__ == "__main__":
    try:
        main()
    except TaostatsError as e:
        # Leave the previous portfolios.json in place: a stale-but-correct page beats a
        # fresh one built on a partial ledger.
        print("aborted, portfolios.json left untouched: %s" % e, file=sys.stderr)
        sys.exit(1)
