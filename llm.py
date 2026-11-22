"""LLM access behind one function: ask_json(). Gemini REST (free tier) by default.

Every call is written to the same ledger as Crustdata calls (handbook: "model calls included").
To swap providers, only _gemini() needs replacing.
"""
from __future__ import annotations

import json
import os
import re
import time

import requests

import store

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# List prices (USD per 1M tokens) used only to ESTIMATE cost in the ledger; the free tier bills $0.
EST_PRICE_IN, EST_PRICE_OUT = 0.30, 2.50


class LLMError(Exception):
    pass


def _gemini(system: str, prompt: str, model: str, temperature: float) -> tuple[str, dict]:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise LLMError("GEMINI_API_KEY is not set (put it in .env)")
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }
    r = requests.post(URL.format(model=model), json=body, headers={"x-goog-api-key": key}, timeout=120)
    if r.status_code != 200:
        raise LLMError(f"{r.status_code}: {r.text[:300]}")
    d = r.json()
    try:
        text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError):
        raise LLMError(f"empty/blocked response: {json.dumps(d)[:300]}")
    return text, d.get("usageMetadata", {})


def _loads(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    return json.loads(text)


MODELS = [m for m in (MODEL, FALLBACK_MODEL, "gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-3.6-flash") if m]


def ask_json(run_id: str, label: str, system: str, prompt: str, *, temperature: float = 0.1, retries: int = 8):
    """Returns parsed JSON. Retries transient errors / invalid JSON, rotating models; raises LLMError when exhausted."""
    last = ""
    for attempt in range(1, retries + 1):
        model = MODELS[(attempt - 1) % len(MODELS)]
        t0 = time.time()
        try:
            text, usage = _gemini(system, prompt, model, temperature)
            tin, tout = usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0)
            store.execute(
                "INSERT INTO calls(run_id,ts,service,endpoint,request_json,status,credits,cost_usd,latency_ms,attempt) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, time.time(), "llm", f"{model}:{label}", json.dumps({"in": tin, "out": tout}), 200, 0,
                 (tin * EST_PRICE_IN + tout * EST_PRICE_OUT) / 1e6, int((time.time() - t0) * 1000), attempt),
            )
            return _loads(text)
        except json.JSONDecodeError as e:
            last = f"invalid JSON: {e}"
        except (LLMError, requests.RequestException) as e:
            last = str(e)
            if "429" in last or "503" in last or "500" in last:
                time.sleep(min(3 * attempt, 20))
            elif isinstance(e, LLMError) and "not set" in last:
                raise
        store.execute(
            "INSERT INTO calls(run_id,ts,service,endpoint,status,latency_ms,attempt,error) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, time.time(), "llm", f"{model}:{label}", None, int((time.time() - t0) * 1000), attempt, last[:300]),
        )
    raise LLMError(f"{label}: gave up after {retries} attempts: {last}")
