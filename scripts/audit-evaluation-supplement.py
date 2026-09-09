#!/usr/bin/env python3
"""Check tutorial structure and hand calculations; never run the RAG evaluator."""
from fractions import Fraction
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SHA = "9d69c63cdca0bf730d8900c3076e0480e541360c"
NAMES = [
    "26-evaluation-overview.md",
    "27-evaluation-dataset.md",
    "28-evaluation-recording.md",
    "29-evaluation-deterministic-metrics.md",
    "30-evaluation-ragas-judge.md",
    "31-evaluation-diagnosis-and-interview.md",
]
checks = 0
failures = []


def check(ok, message):
    global checks
    checks += 1
    if not ok:
        failures.append(message)


texts = {}
readme = (ROOT / "README.md").read_text()
for name in NAMES:
    path = ROOT / "docs" / name
    check(path.exists(), f"missing chapter {name}")
    if not path.exists():
        continue
    content = path.read_text()
    texts[name[:2]] = content
    check(f"docs/{name}" in readme, f"missing homepage entry {name}")
    check(content.startswith(f"# 第 {int(name[:2])} 章"), f"wrong title {name}")
    check(content.count("```") % 2 == 0, f"unclosed fence {name}")
    check("../README.md" in content, f"missing return link {name}")
    check("源码" in content or "项目实现" in content, f"missing source entry {name}")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
        if target.startswith("https://gitcode.net/nageoffer/ragenteval/-/blob/"):
            check(f"/blob/{SHA}/" in target, f"unfrozen source URL {target}")
        elif not target.startswith(("https://", "http://", "#")):
            check((path.parent / target.split("#")[0]).exists(), f"broken link {target}")
    check(not re.search(r"/Users/|/data2/|ghp_[A-Za-z0-9]{20,}", content), f"private path/token {name}")

for chapter in ("26", "28", "31"):
    check("../assets/diagrams/evaluation-" in texts.get(chapter, ""), f"missing process diagram {chapter}")

check("两个请求不是同一次请求" in texts["28"], "lost dual-request explanation")
check("业务文档召回" in texts["29"] and "HNSW 近似召回" in texts["29"], "lost recall distinction")
check("空召回的代理指标" in texts["29"], "lost behavior semantics")
check("None" in texts["29"] and "跳过" in texts["30"], "lost denominator explanation")
check("不代表统计学显著性检验" in texts["31"], "lost diff interpretation")
check("预留结构" in texts["31"], "lost Agent evaluation scope")
check("不会重新向 RAG 提问" in texts["31"], "lost report stage boundary")

# Independent arithmetic for the authored examples; no evaluator imports.
gold = {"A", "B"}
ranked = ["X", "A", "Y", "B", "Z"]
for k, hit, recall in [(1, 0, Fraction(0)), (3, 1, Fraction(1, 2)), (5, 1, Fraction(1))]:
    intersection = set(ranked[:k]) & gold
    check(int(bool(intersection)) == hit, f"Hit@{k} example")
    check(Fraction(len(intersection), len(gold)) == recall, f"Recall@{k} example")
check(Fraction(1, next(i for i, d in enumerate(ranked, 1) if d in gold)) == Fraction(1, 2), "RR example")
check((1 + Fraction(1, 2) + 0) / 3 == Fraction(1, 2), "MRR example")


def average_precision(flags):
    positives = 0
    total = Fraction(0)
    for i, flag in enumerate(flags, 1):
        positives += flag
        if flag:
            total += Fraction(positives, i)
    return total / sum(flags)


check(average_precision([1, 0, 1, 0]) == Fraction(5, 6), "context precision first ranking")
check(average_precision([0, 0, 1, 1]) == Fraction(5, 12), "context precision second ranking")
check(Fraction(3, 4) * Fraction(1, 2) + Fraction(1, 4) * Fraction(4, 5) == Fraction(23, 40), "correctness weighted example")
check(sum([1, 2, 3, 4, 20]) / 5 == 6, "TTFT mean example")
check((Fraction(4, 5) * 2 + 1) / 3 == Fraction(13, 15), "manual override mean")

print(f"checks={checks} failures={len(failures)}")
for failure in failures:
    print(f"FAIL: {failure}")
raise SystemExit(bool(failures))
