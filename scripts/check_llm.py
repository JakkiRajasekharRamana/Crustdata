import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import llm, store

store.create_run("smoke", "smoke")
print(llm.ask_json("smoke", "ping", "Reply with JSON only.", 'Return {"ok": true, "n": 4}'))
print(store.ledger_totals("smoke"))
