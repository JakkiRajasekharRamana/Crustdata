"""Single entry point for every Crustdata call.

Responsibilities (all in one place so nothing can bypass them):
  * auth + version headers (x-api-version: 2025-11-01)
  * per-endpoint rate limiting (limits read from the free GET /account/endpoints)
  * retries: 429 waits for x-ratelimit-reset; timeouts/5xx back off; 402 is fatal (retry won't help)
  * per-run credit and time ceilings, checked BEFORE each call
  * ledger row per call with the credits reported in the X-Credits-Used header
  * raw-response cache, so a repeated request costs nothing and a crashed run resumes cheaply

An API failure is never treated as "the information does not exist": it raises CrustdataError,
and the caller marks the item `needs_review` instead.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import defaultdict, deque

import requests

import store

BASE = "https://api.crustdata.com"
API_VERSION = "2025-11-01"

# Conservative defaults; overwritten with the key's real limits from /account/endpoints.
DEFAULT_RPM = {
    "/company/search": 5, "/company/identify": 5, "/company/enrich": 5,
    "/person/search": 5, "/person/enrich": 5, "/web/search/live": 10, "/web/enrich/live": 10,
}


class CrustdataError(Exception):
    def __init__(self, msg: str, status: int | None = None, body: str = ""):
        super().__init__(msg)
        self.status, self.body = status, body


class CreditsExhausted(CrustdataError):
    """402: retrying will not help."""


class BudgetExceeded(Exception):
    """The per-run credit or time ceiling was reached. The run stops cleanly and can be resumed."""


class Crustdata:
    def __init__(self, run_id: str, credit_ceiling: float | None = None, time_ceiling: float | None = None):
        self.key = os.environ.get("CRUSTDATA_API_KEY", "").strip()
        if not self.key:
            raise CrustdataError("CRUSTDATA_API_KEY is not set (put it in .env)")
        self.run_id = run_id
        self.credit_ceiling = credit_ceiling if credit_ceiling is not None else float(os.environ.get("RUN_CREDIT_CEILING", 300))
        self.time_ceiling = time_ceiling if time_ceiling is not None else float(os.environ.get("RUN_TIME_CEILING_SECONDS", 900))
        self.started = time.time()
        self.rpm = dict(DEFAULT_RPM)
        self._hits: dict[str, deque] = defaultdict(deque)
        self.s = requests.Session()
        self.s.headers.update({"authorization": f"Bearer {self.key}", "x-api-version": API_VERSION,
                               "content-type": "application/json"})
        self._load_limits()

    # ---- helpers ----
    def _load_limits(self) -> None:
        try:
            r = self.s.get(f"{BASE}/account/endpoints", timeout=20)
            if r.ok:
                for e in r.json().get("endpoints", []):
                    if e.get("status") == "enabled" and e.get("effective_rate_limit_rpm"):
                        self.rpm[e["path"]] = e["effective_rate_limit_rpm"]
        except requests.RequestException:
            pass  # keep conservative defaults

    def balance(self) -> float:
        """GET /account/credits is free."""
        r = self.s.get(f"{BASE}/account/credits", timeout=20)
        r.raise_for_status()
        return r.json()["account"]["credits"]

    def spent(self) -> float:
        return store.ledger_totals(self.run_id)["credits"]

    def _check_budget(self) -> None:
        if self.spent() >= self.credit_ceiling:
            raise BudgetExceeded(f"credit ceiling {self.credit_ceiling} reached (spent {self.spent():.2f})")
        if time.time() - self.started >= self.time_ceiling:
            raise BudgetExceeded(f"time ceiling {self.time_ceiling}s reached")

    def _throttle(self, path: str) -> None:
        limit = self.rpm.get(path, 5)
        q = self._hits[path]
        while True:
            now = time.time()
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) < limit:
                q.append(now)
                return
            time.sleep(max(0.5, 60 - (now - q[0]) + 0.2))

    @staticmethod
    def _key(path: str, body: dict) -> str:
        return hashlib.sha256((path + json.dumps(body, sort_keys=True)).encode()).hexdigest()

    def _log(self, path, body, status, credits, latency, cached=0, attempt=1, error=None) -> None:
        store.execute(
            "INSERT INTO calls(run_id,ts,service,endpoint,request_json,status,credits,latency_ms,cached,attempt,error) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (self.run_id, time.time(), "crustdata", path, json.dumps(body)[:2000], status, credits,
             int(latency * 1000), cached, attempt, error),
        )

    # ---- the one call ----
    def call(self, path: str, body: dict, *, use_cache: bool = True, max_attempts: int = 4):
        """POST {path}. Returns parsed JSON. Raises CrustdataError / CreditsExhausted / BudgetExceeded."""
        key = self._key(path, body)
        if use_cache:
            rows = store.query("SELECT response_json FROM cache WHERE key=?", (key,))
            if rows:
                self._log(path, body, 200, 0.0, 0.0, cached=1)
                return json.loads(rows[0]["response_json"])

        last_err = ""
        for attempt in range(1, max_attempts + 1):
            self._check_budget()
            self._throttle(path)
            t0 = time.time()
            try:
                r = self.s.post(f"{BASE}{path}", json=body, timeout=60)
            except requests.RequestException as e:  # timeout / connection reset
                last_err = f"{type(e).__name__}: {e}"
                self._log(path, body, None, 0.0, time.time() - t0, attempt=attempt, error=last_err)
                time.sleep(min(2 ** attempt, 20))
                continue

            credits = float(r.headers.get("X-Credits-Used") or 0)
            latency = time.time() - t0
            if r.status_code == 200:
                try:
                    data = r.json()
                except ValueError:  # a 200 whose body is not JSON: log it, never cache it, retry (bounded)
                    self._log(path, body, 200, credits, latency, attempt=attempt, error="invalid JSON body")
                    last_err = "200 with invalid JSON"
                    time.sleep(min(2 ** attempt, 20))
                    continue
                self._log(path, body, 200, credits, latency, attempt=attempt)
                store.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?,?)",
                              (key, path, time.time(), json.dumps(data)))
                return data
            self._log(path, body, r.status_code, credits, latency, attempt=attempt, error=r.text[:300])
            if r.status_code == 429:
                wait = float(r.headers.get("x-ratelimit-reset") or 5)
                time.sleep(min(max(wait, 1), 60))
                last_err = "429 rate limited"
                continue
            if r.status_code == 402:
                raise CreditsExhausted("402: out of credits (check GET /account/credits)", 402, r.text)
            if r.status_code in (401, 403):
                raise CrustdataError(f"{r.status_code}: auth/permission problem for {path}", r.status_code, r.text)
            if r.status_code >= 500:
                last_err = f"{r.status_code} server error"
                time.sleep(min(2 ** attempt, 20))
                continue
            raise CrustdataError(f"{r.status_code} on {path}: {r.text[:300]}", r.status_code, r.text)
        raise CrustdataError(f"gave up on {path} after {max_attempts} attempts: {last_err}")

    # ---- thin endpoint wrappers (request shapes verified against docs.crustdata.com) ----
    def company_search(self, *, query: str | None = None, filters: dict | None = None,
                       fields: list[str] | None = None, limit: int = 20, mode: str = "hybrid"):
        body: dict = {"limit": limit}
        if query:
            body["search"] = {"query": query, "mode": mode}
        if filters:
            body["filters"] = filters
        if fields:
            body["fields"] = fields
        return self.call("/company/search", body)

    def company_identify(self, *, domains=None, names=None):
        body = {k: v for k, v in (("domains", domains), ("names", names)) if v}
        return self.call("/company/identify", body)

    def company_enrich(self, *, domains=None, ids=None, fields=None):
        body: dict = {}
        if domains:
            body["domains"] = domains
        if ids:
            body["crustdata_company_ids"] = ids
        if fields:
            body["fields"] = fields
        return self.call("/company/enrich", body)

    def web_search(self, query: str, *, sources=("web", "news"), location: str | None = "IN", **kw):
        body: dict = {"query": query, "sources": list(sources), **kw}
        if location:
            body["location"] = location
        return self.call("/web/search/live", body)

    def web_fetch(self, urls: list[str]):
        return self.call("/web/enrich/live", {"urls": urls[:10]})

    def person_search_company(self, company_id: int, *, limit: int = 25):
        """People whose CURRENT employer is this Crustdata company id. Only name, title and id are requested.
        Filter field and response shape come from the API's own error message listing supported fields (checked live)."""
        body = {"filters": {"field": "experience.employment_details.current.company_id", "type": "=", "value": company_id},
                "fields": ["basic_profile.name", "basic_profile.current_title", "crustdata_person_id"], "limit": limit}
        return self.call("/person/search", body)
