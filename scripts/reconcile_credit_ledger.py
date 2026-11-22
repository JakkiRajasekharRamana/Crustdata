"""Reconcile the local call ledger with the authoritative account balance (GET /account/credits is free).
usage: python scripts/reconcile_credit_ledger.py STARTING_BALANCE
Credits per call come from the X-Credits-Used response header. Any call made OUTSIDE the central client (for example a
manual curl or an exploratory script) is not in the ledger and shows up as an unexplained difference."""
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store

start = float(sys.argv[1])
h = {"authorization": "Bearer " + os.environ["CRUSTDATA_API_KEY"], "x-api-version": "2025-11-01"}
bal = requests.get("https://api.crustdata.com/account/credits", headers=h, timeout=30).json()["account"]["credits"]
led = store.query("SELECT COALESCE(SUM(credits),0) c, COUNT(*) n, COALESCE(SUM(cached),0) hits FROM calls WHERE service='crustdata'")[0]
failed = store.query("SELECT COUNT(*) n, COALESCE(SUM(credits),0) c FROM calls WHERE service='crustdata' AND (status IS NULL OR status!=200)")[0]
print(f"starting balance (stated): {start}\ncurrent balance (API):     {bal}\nspent according to API:    {start - bal:.2f}")
print(f"spent according to ledger: {led['c']:.2f}  ({led['n']} rows, {led['hits']} cache hits at 0 credits, {failed['n']} non-200 rows costing {failed['c']:.2f})")
print(f"difference (API - ledger): {start - bal - led['c']:+.2f}")
