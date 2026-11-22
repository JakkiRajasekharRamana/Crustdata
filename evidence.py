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

    def to_json(self) -> dict:
        return {"sid": self.sid, "kind": self.kind, "url": self.url, "ref": self.ref,
                "text": self.text, "title": self.title, "published_at": self.published_at,
                "retrieved_at": self.retrieved_at}

    @classmethod
    def from_json(cls, d: dict) -> "Source":
        s = cls(d["sid"], d["kind"], d["url"], d["ref"], d["text"], d.get("title", ""), d.get("published_at"))
        s.retrieved_at = d.get("retrieved_at", s.retrieved_at)
        return s


# How much to trust a verified quote, by where it came from.
SOURCE_CONFIDENCE = {"crustdata_api": "high", "news": "medium", "first_party": "medium", "search_snippet": "medium"}


def check_claims(run_id: str, company_id: str, raw_claims: list[dict], sources: dict[str, Source]) -> list[dict]:
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
        row = {
            "claim_id": f"{company_id}-c{i+1}", "run_id": run_id, "company_id": company_id,
            "category": c.get("category", "other"), "claim": c["claim"], "source_url": src.url if src else None,
            "source_ref": (src.ref if src else None), "quote": quote[:600] if quote else None,
            "published_at": src.published_at if src else None, "retrieved_at": src.retrieved_at if src else now_iso(),
            "status": status, "confidence": conf, "agent": c.get("agent", "intelligence"), "notes": note,
        }
        store.execute(
            "INSERT OR REPLACE INTO evidence VALUES (:claim_id,:run_id,:company_id,:category,:claim,:source_url,"
            ":source_ref,:quote,:published_at,:retrieved_at,:status,:confidence,:agent,:notes)", row)
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
    }
    store.execute(
        "INSERT OR REPLACE INTO evidence VALUES (:claim_id,:run_id,:company_id,:category,:claim,:source_url,"
        ":source_ref,:quote,:published_at,:retrieved_at,:status,:confidence,:agent,:notes)", row)
    return row


def claims_for(run_id: str, company_id: str) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT * FROM evidence WHERE run_id=? AND company_id=? ORDER BY claim_id", (run_id, company_id))]
