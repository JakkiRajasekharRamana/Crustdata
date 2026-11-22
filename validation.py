"""Deterministic request validation. Runs BEFORE any model or paid API call, so an invalid request costs nothing.

Plain dataclass + regex (no new dependency). Blocking problems make `ok` False; `clarifications` are the questions a person
must answer first; `warnings` are shown but do not block.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MIN_CHARS, MIN_WORDS, MAX_CHARS = 40, 7, 4000

COUNTRIES = ["india", "united states", "usa", "u.s.", "united kingdom", "uk", "canada", "australia", "singapore", "uae", "united arab emirates",
             "germany", "france", "netherlands", "spain", "italy", "japan", "china", "indonesia", "malaysia", "vietnam", "thailand",
             "philippines", "brazil", "mexico", "south africa", "nigeria", "kenya", "saudi arabia", "israel", "ireland", "sweden",
             "switzerland", "bangladesh", "sri lanka", "nepal", "pakistan", "egypt", "turkey", "south korea", "new zealand",
             "europe", "asia", "africa", "middle east", "apac", "emea", "latam", "north america", "global", "worldwide"]
INDIA_REGIONS = ["mumbai", "delhi", "bengaluru", "bangalore", "hyderabad", "chennai", "pune", "kolkata", "gujarat", "maharashtra", "karnataka", "tamil nadu", "kerala"]
PARTNER_WORDS = ["partner", "partnership", "reseller", "distributor", "distribution", "channel", "integrat", "alliance", "collaborat", "co-sell", "referral", "oem"]
AUTOSEND = re.compile(r"\b(send|email|mail|message|contact|reach out to|dm)\b[^.]{0,60}\b(automatically|without (my )?(approval|review)|on my behalf|immediately)\b", re.I)


@dataclass
class Verdict:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    clarifications: list[str] = field(default_factory=list)
    cleaned: str = ""


def _has(text: str, words: list[str]) -> bool:
    low = text.lower()
    return any(w in low for w in words)


def validate_request(text: str | None, structured: dict | None = None) -> Verdict:
    structured = {k: (v or "").strip() for k, v in (structured or {}).items()}
    raw = re.sub(r"\s+", " ", text or "").strip()
    v = Verdict(ok=True, cleaned=raw)
    if not raw:
        v.ok = False
        v.errors.append("The request is empty. Describe what your company sells and what kind of partner you want.")
        return v
    if len(raw) > MAX_CHARS:
        v.ok = False
        v.errors.append(f"The request is {len(raw)} characters; the limit is {MAX_CHARS}. Shorten it to the objective and the constraints.")
    words = re.findall(r"[A-Za-z]{2,}", raw)
    if len(raw) < MIN_CHARS or len(words) < MIN_WORDS:
        v.ok = False
        v.errors.append(f"The request is too short to research (needs at least {MIN_WORDS} words). Say what you sell, which market and what kind of partner.")
    letters = sum(c.isalpha() for c in raw)
    if raw and letters / max(len(raw), 1) < 0.5:
        v.ok = False
        v.errors.append("The request is mostly symbols or numbers; please describe it in words.")
    if not v.ok:
        return v

    blob = raw + " " + " ".join(structured.values())
    if AUTOSEND.search(raw):
        v.ok = False
        v.errors.append("PartnerScout never contacts anyone automatically. It prepares drafts and a person approves them. Remove the instruction to send messages.")
    m = re.search(r"\b(?:top|find|identify|give me|list|shortlist)\s+(\d{1,3})\b", raw, re.I)
    if m and not 1 <= int(m.group(1)) <= 15:
        v.ok = False
        v.errors.append(f"{m.group(1)} partners is outside the supported range of 1 to 15 per brief.")

    if not _has(blob, PARTNER_WORDS):
        v.clarifications.append("What kind of partnership do you want (reseller, channel, technology integration, referral, ...)?")
    if not (_has(blob, COUNTRIES) or _has(blob, INDIA_REGIONS)):
        v.clarifications.append("Which country or region should the partners operate in?")
    if not re.search(r"\b(we|our|i|my)\b.{0,40}\b(sell|offer|provide|build|make|are a|is a|develop|operate|run|platform|product|saas|software|service)", raw, re.I) \
            and not structured.get("Requesting company") and not structured.get("Company website"):
        v.clarifications.append("What does your company sell or do? Partner fit cannot be judged without it.")
    if v.clarifications:
        v.ok = False
    if re.search(r"\b(only|exclusively)\b.{0,40}\b(india|us|usa|uk)\b.*\b(also|and)\b.{0,30}\b(outside|abroad|global)", raw, re.I):
        v.warnings.append("The request mixes a single-country restriction with a global scope; the first country will be used.")
    return v
