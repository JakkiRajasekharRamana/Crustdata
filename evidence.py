"""Evidence ledger + quote verification.

The core anti-hallucination rule: a claim is `verified` ONLY if the verbatim quote the model gave
is actually present in the text of the cited source. Otherwise it is stored as `unverified` and the
report says "I can't verify this from the available sources". A model's memory is never a source.

Statuses: verified | unverified | inferred | contradicted | needs_review
"""
from __future__ import annotations

import html
import re
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from datetime import datetime, timezone
from html.parser import HTMLParser

import store


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "iframe"}

    def __init__(self):
        super().__init__()
        self.out, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "div", "tr"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.out.append(data.strip() + " ")


def html_to_text(raw: str) -> str:
    p = _Text()
    try:
        p.feed(raw or "")
    except Exception:
        return re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"[ \t]+", " ", html.unescape("".join(p.out))).strip()


def _squash(s: str) -> str:
    """Normalise for comparison: lowercase alphanumerics only. Robust to quotes, dashes, whitespace."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def verify_quote(quote: str, source_text: str) -> bool:
    q = _squash(quote)
    return len(q) >= 12 and q in _squash(source_text)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Source:
    """One retrievable record: an API field path, a fetched page or a search snippet."""

    def __init__(self, sid: str, kind: str, url: str, ref: str, text: str,
                 title: str = "", published_at: str | None = None):
        self.sid, self.kind, self.url, self.ref = sid, kind, url, ref
        self.text, self.title, self.published_at = text, title, published_at
        self.retrieved_at = now_iso()
        self.canonical_url = None

    def to_json(self) -> dict:
        return {"sid": self.sid, "kind": self.kind, "url": self.url, "ref": self.ref,
                "text": self.text, "title": self.title, "published_at": self.published_at,
                "retrieved_at": self.retrieved_at, "canonical_url": self.canonical_url}

    @classmethod
    def from_json(cls, d: dict) -> "Source":
        s = cls(d["sid"], d["kind"], d["url"], d["ref"], d["text"], d.get("title", ""), d.get("published_at"))
        s.retrieved_at = d.get("retrieved_at", s.retrieved_at)
        s.canonical_url = d.get("canonical_url")
        return s


# ---------------------------------------------------------------- source quality
# Source classes (1 official company, 2 official regulatory/government, 3 independent news, 4 verified partner/customer,
# 5 third-party business database, 6 weak/unverified). Class 4 cannot be assigned automatically (a person must confirm that a
# page really is a named partner's or customer's own statement), so the code never assigns it.
REGULATORY_SUFFIX = (".gov.in", ".nic.in", ".gov", "rbi.org.in", "sebi.gov.in", "irdai.gov.in", "cert-in.org.in", "mca.gov.in")
NEWS_DOMAINS = {"economictimes.indiatimes.com", "livemint.com", "business-standard.com", "thehindu.com", "thehindubusinessline.com",
                "moneycontrol.com", "financialexpress.com", "reuters.com", "bloomberg.com", "techcrunch.com", "inc42.com",
                "yourstory.com", "businesstoday.in", "hindustantimes.com", "indianexpress.com", "ndtv.com", "medianama.com",
                "cnbctv18.com", "timesofindia.indiatimes.com", "forbesindia.com", "bwdisrupt.com", "expresscomputer.in"}
DATABASE_DOMAINS = {"tracxn.com", "zaubacorp.com", "instafinancials.com", "crunchbase.com", "tofler.in", "pitchbook.com",
                    "craft.co", "glassdoor.com", "ambitionbox.com", "justdial.com", "indiamart.com", "dnb.com", "clutch.co", "g2.com",
                    "rocketreach.co", "zoominfo.com", "apollo.io", "owler.com", "cbinsights.com", "mouthshut.com"}


def host_of(url) -> str:
    h = (urlparse(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def same_site(host: str, domain: str) -> bool:
    d = (domain or "").lower().removeprefix("www.")
    return bool(host and d and (host == d or host.endswith("." + d)))


def classify_source(url, kind: str, company_domain: str = ""):
    """Return (source_class, corroboration). corroboration says what the source can and cannot prove:
    api_record = the company's own submitted data held by Crustdata; self_reported = the company's own site;
    independent = regulatory or reputable news; database_listing = a third-party directory that often copies other
    data (never counted as strong corroboration on its own); weak = an unclassified web page or snippet."""
    if kind == "crustdata_api":
        return "third_party_business_database", "api_record"
    host = host_of(url)
    if kind == "first_party" or same_site(host, company_domain):
        return "official_company_source", "self_reported"
    if host.endswith(REGULATORY_SUFFIX):
        return "official_regulatory_source", "independent"
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        # A company's LinkedIn page and posts are written by the company (or its staff): self-published, not corroboration.
        return "company_social_profile", "self_reported"
    if host in NEWS_DOMAINS or any(host.endswith("." + d) for d in NEWS_DOMAINS):
        return "independent_news_source", "independent"
    if host in DATABASE_DOMAINS or any(host.endswith("." + d) for d in DATABASE_DOMAINS):
        return "third_party_business_database", "database_listing"
    return "weak_or_unverified_source", "weak"


_TRACKING = ("utm_", "gclid", "fbclid", "gsessionid", "ved", "usg")


def strip_tracking(url: str) -> str:
    u = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if not k.lower().startswith(_TRACKING)]
    return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(q), ""))


def canonicalize(url, session=None, max_hops: int = 3, timeout: float = 10.0):
    """Real destination of a search-result link. Google 'goto' links are opaque tokens, so the destination can only be
    learned from the redirect's Location header. We follow at most `max_hops` hops, only while the current URL is still a
    Google redirect, and never request the destination page itself. Returns None when it cannot be resolved; the caller
    keeps the original link but must not present it as a verified canonical source."""
    if not url:
        return None
    cur = url
    if "google." not in host_of(cur):
        return strip_tracking(cur)  # already a direct URL
    import requests
    s = session or requests
    for _ in range(max_hops):
        if "google." not in host_of(cur):
            return strip_tracking(cur)
        try:
            r = s.get(cur, allow_redirects=False, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (PartnerScout citation resolver)"})
        except Exception:
            return None
        loc = r.headers.get("location") or r.headers.get("Location")
        if r.status_code not in (301, 302, 303, 307, 308) or not loc or not loc.lower().startswith(("http://", "https://")):
            return None
        cur = loc
    return strip_tracking(cur) if "google." not in host_of(cur) else None


# How much to trust a verified quote, by where it came from.
SOURCE_CONFIDENCE = {"crustdata_api": "high", "news": "medium", "first_party": "medium", "search_snippet": "medium"}


def check_claims(run_id: str, company_id: str, raw_claims: list[dict], sources: dict[str, Source], company_domain: str = "") -> list[dict]:
    """Verify model-proposed claims against the actual source text and write them to the ledger."""
    out = []
    for i, c in enumerate(raw_claims or []):
        if not isinstance(c, dict) or not c.get("claim"):
            continue
        sid = str(c.get("source_id") or "")
        src = sources.get(sid)
        quote = (c.get("quote") or "").strip()
        is_inference = c.get("type") == "inference"
        if is_inference:
            status, conf, note = "inferred", "low", "Reasonable business inference, not stated by a source."
            src = None
        elif src and verify_quote(quote, src.text):
            status, conf, note = "verified", SOURCE_CONFIDENCE.get(src.kind, "medium"), None
            if src.kind == "first_party":
                note = "Self-reported on the company's own website."
        else:
            status, conf = "unverified", "low"
            note = "I can't verify this from the available sources." if src else "Cited source not found."
        s_class = corro = canon = org = None
        if src:
            s_class, corro = classify_source(src.canonical_url or src.url, src.kind, company_domain)
            canon, org = src.canonical_url, host_of(src.canonical_url or src.url) or None
            if status == "verified" and corro in ("database_listing", "weak"):
                note = (note + " " if note else "") + "Listed by a third-party site that may copy other data; not strong corroboration."
        row = {
            "claim_id": f"{company_id}-c{i+1}", "run_id": run_id, "company_id": company_id,
            "category": c.get("category", "other"), "claim": c["claim"], "source_url": src.url if src else None,
            "source_ref": (src.ref if src else None), "quote": quote[:600] if quote else None,
            "published_at": src.published_at if src else None, "retrieved_at": src.retrieved_at if src else now_iso(),
            "status": status, "confidence": conf, "agent": c.get("agent", "intelligence"), "notes": note,
            "canonical_url": canon, "source_class": s_class, "source_org": org,
            "corroboration": (corro if status == "verified" else ("unverified" if status == "unverified" else "inference")),
        }
        store.put_evidence(row)
        out.append(row)
    return out


def api_claim(run_id: str, company_id: str, n: int, category: str, claim: str, field_path: str,
              value: str, record_url: str, agent="intelligence") -> dict:
    """A claim read straight from a Crustdata API field: the field value IS the evidence."""
    row = {
        "claim_id": f"{company_id}-a{n}", "run_id": run_id, "company_id": company_id, "category": category,
        "claim": claim, "source_url": record_url, "source_ref": field_path, "quote": str(value)[:600],
        "published_at": None, "retrieved_at": now_iso(), "status": "verified", "confidence": "high",
        "agent": agent, "notes": "Crustdata API record field.",
        "canonical_url": None, "source_class": "third_party_business_database", "source_org": "crustdata.com", "corroboration": "api_record",
    }
    store.put_evidence(row)
    return row


def claims_for(run_id: str, company_id: str) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT * FROM evidence WHERE run_id=? AND company_id=? ORDER BY claim_id", (run_id, company_id))]


def annotate_claims(claims: list[dict], company_domain: str = "") -> list[dict]:
    """Fill source_class / corroboration for claims that do not have them (runs created before source classification).
    Classification only: no network access, so an unresolved Google redirect stays 'weak' (never treated as verified)."""
    for c in claims:
        if c.get("corroboration") is not None:
            continue
        url = c.get("canonical_url") or c.get("source_url") or ""
        if c["status"] == "verified" and url:
            kind = "crustdata_api" if url.startswith("crustdata:") else "first_party" if str(c.get("notes") or "").startswith("Self-reported") else "search_snippet"
            cls, corro = classify_source(url, kind, company_domain)
            c.update(source_class=cls, corroboration=corro, source_org=c.get("source_org") or host_of(url) or None)
        else:
            c["corroboration"] = {"unverified": "unverified", "inferred": "inference", "contradicted": "contradiction"}.get(c["status"], c.get("corroboration"))
    return claims
