#!/usr/bin/env python3
"""Standalone cache warmer: registry + per-pool TVL history -> defi_topology/charts/.
Run once; the hardened pipeline reuses the cache. Safe to re-run (skips cached)."""
import json, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ZERO = "0x0000000000000000000000000000000000000000"
UA = {"User-Agent": "defi-topology-research"}
HERE = os.path.dirname(os.path.abspath(__file__))
CHART_DIR = os.path.join(HERE, "charts")

def _get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90))

def toks(p):
    return sorted(set(t.lower() for t in (p.get("underlyingTokens") or []) if t and t.lower() != ZERO))

def universe():
    pools = _get("https://yields.llama.fi/pools")["data"]
    uni = [p for p in pools if p.get("chain") == "Ethereum" and p.get("stablecoin") and 2 <= len(toks(p)) <= 8]
    return [{"pool": p["pool"], "toks": toks(p), "sym": p["symbol"], "proj": p["project"]} for p in uni]

def main():
    os.makedirs(CHART_DIR, exist_ok=True)
    uni = universe()
    json.dump(uni, open(os.path.join(CHART_DIR, "universe.json"), "w"))
    print(f"universe: {len(uni)} pools", flush=True)

    def one(u):
        fn = f"{CHART_DIR}/{u['pool']}.json"
        if os.path.exists(fn):
            return
        try:
            d = _get(f"https://yields.llama.fi/chart/{u['pool']}")["data"]
            json.dump([(c["timestamp"][:10], c.get("tvlUsd") or 0) for c in d], open(fn, "w"))
        except Exception:
            pass

    for r in range(8):
        miss = [u for u in uni if not os.path.exists(f"{CHART_DIR}/{u['pool']}.json")]
        if not miss:
            break
        print(f"fetch round {r}: {len(miss)} remaining", flush=True)
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(one, miss))
        time.sleep(3)
    have = len([u for u in uni if os.path.exists(f"{CHART_DIR}/{u['pool']}.json")])
    print(f"DONE charts cached: {have}/{len(uni)}", flush=True)

if __name__ == "__main__":
    main()
