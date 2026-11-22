"""Metrics for the ranking-stability experiment: top-K overlap, Spearman, Kendall tau, inclusion frequency.
usage: python scripts/stability_metrics.py LABEL"""
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path


def spearman(a, b):
    common = [x for x in a if x in set(b)]
    if len(common) < 3:
        return float("nan")
    ra = {x: i for i, x in enumerate([y for y in a if y in set(common)])}
    rb = {x: i for i, x in enumerate([y for y in b if y in set(common)])}
    n = len(common)
    d2 = sum((ra[x] - rb[x]) ** 2 for x in common)
    return 1 - 6 * d2 / (n * (n * n - 1))


def kendall(a, b):
    common = [x for x in a if x in set(b)]
    pa = {x: i for i, x in enumerate(a)}
    pb = {x: i for i, x in enumerate(b)}
    conc = disc = 0
    for x, y in combinations(common, 2):
        s = (pa[x] - pa[y]) * (pb[x] - pb[y])
        conc += s > 0
        disc += s < 0
    t = conc + disc
    return (conc - disc) / t if t else float("nan")


def main(label):
    runs = []
    for part in label.split("+"):  # several result files of the same method can be merged: label_a+label_b
        runs += json.loads((Path(__file__).resolve().parent.parent / "audit_results" / f"stability_{part}.json").read_text())
    n = len(runs)
    out = {"label": label, "repeats": n}
    for K in (5, 6):
        ov = [len(set(a["ranking"][:K]) & set(b["ranking"][:K])) / K for a, b in combinations(runs, 2)]
        out[f"top{K}_mean_pairwise_overlap"] = round(sum(ov) / len(ov), 3)
        out[f"top{K}_min_pairwise_overlap"] = round(min(ov), 3)
        cnt = Counter(i for r in runs for i in r["ranking"][:K])
        out[f"top{K}_distinct_companies_ever_selected"] = len(cnt)
        out[f"top{K}_always_selected"] = sum(1 for v in cnt.values() if v == n)
    sp = [spearman(a["ranking"][:30], b["ranking"][:30]) for a, b in combinations(runs, 2)]
    kt = [kendall(a["ranking"][:30], b["ranking"][:30]) for a, b in combinations(runs, 2)]
    out["spearman_top30_mean"] = round(sum(sp) / len(sp), 3)
    out["kendall_top30_mean"] = round(sum(kt) / len(kt), 3)
    names = runs[0]["names"]
    cnt = Counter(i for r in runs for i in r["ranking"][:6])
    out["top6_inclusion_frequency"] = {names.get(str(i), str(i))[:30]: f"{v}/{n}" for i, v in cnt.most_common(12)}
    print(json.dumps(out, indent=1))
    (Path(__file__).resolve().parent.parent / "audit_results" / f"stability_{label.replace('+', '_')}_metrics.json").write_text(json.dumps(out, indent=1))


main(sys.argv[1])
