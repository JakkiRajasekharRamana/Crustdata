"""Print a reproducible sample of verified, non-API claims next to their quotes for HUMAN judgement."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store

run, k = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 15
fin = store.get_stage(run, "final")
pool = [(r["company"]["name"], c) for r in fin["ranked"] if not r.get("held_for_review") for c in r["claims"]
        if c["status"] == "verified" and not str(c.get("notes") or "").startswith("Crustdata API")]
random.Random(7).shuffle(pool)
for i, (name, c) in enumerate(pool[:k], 1):
    print(f"{i}. [{name}] ({c['category']}) CLAIM: {c['claim']}\n   QUOTE: {str(c['quote'])[:230]}\n")
print("pool size:", len(pool))
