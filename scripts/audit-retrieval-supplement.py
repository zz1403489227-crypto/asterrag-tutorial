#!/usr/bin/env python3
"""Read-only tutorial/source checks; never starts the application or services."""
from pathlib import Path
import csv
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "sources/AsterRAG"
SHA = "98894c2c42c015a3c874c6b3c986ac863c85b731"
failures = []
checks = 0


def check(ok, message):
    global checks
    checks += 1
    if not ok:
        failures.append(message)


head = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
check(head == SHA, "source HEAD drift")
check(not subprocess.check_output(["git", "-C", str(SOURCE), "status", "--porcelain"], text=True).strip(), "source worktree dirty")
with (ROOT / "evidence/retrieval-supplement-claims.csv").open() as handle:
    rows = list(csv.DictReader(handle))
check(len(rows) == 19, "expected 19 supplement claims")
check(len({row["claim_id"] for row in rows}) == len(rows), "duplicate claim id")
for row in rows:
    target = SOURCE / row["path"]
    check(target.is_file(), f"missing {row['path']}")
    if target.is_file():
        check(row["anchor"] in target.read_text(), f"missing anchor {row['claim_id']}")

chapters = sorted(p for p in (ROOT / "docs").glob("*.md") if re.match(r"2[1-5]-", p.name))
check(len(chapters) == 5, "expected five supplement chapters")
for path in chapters + [ROOT / "appendices/retrieval-implementation-notes.md"]:
    text = path.read_text()
    check(text.count("```") % 2 == 0, f"unclosed fence {path.name}")
    check("rag.retrieval.channels" not in text, f"wrong config prefix {path.name}")
    check("源码" in text, f"missing source navigation {path.name}")
    for target in re.findall(r"\]\((https://github.com/zz1403489227-crypto/AsterRAG/blob/[^)]+)\)", text):
        tail = target.split("/blob/", 1)[1]
        revision, rel = tail.split("/", 1)
        check(revision == SHA, f"unfrozen source link {path.name}: {target}")
        relpath, _, fragment = rel.partition("#")
        sourcefile = SOURCE / relpath
        check(sourcefile.is_file(), f"broken source link {target}")
        if fragment.startswith("L") and sourcefile.is_file():
            check(int(fragment[1:]) <= len(sourcefile.read_text().splitlines()), f"line out of range {target}")

scores = {"A": 1/21, "B": 1/22 + 1/21 + .8/22, "C": 1/23 + 1/22, "D": 1/23 + .8/21}
check(sorted(scores, key=scores.get, reverse=True) == ["B", "C", "D", "A"], "RRF example ordering")
chapter24 = (ROOT / "docs/24-hybrid-retrieval-to-evidence.md").read_text()
for value in scores.values():
    check(f"{value:.5f}" in chapter24, "RRF example rounded score mismatch")

# Structural/numeric checks assist review; they do not judge teaching quality.
required_topics = {
    "21-hnsw-vector-index.md": ["随机", "邻居", "候选", "入库", "查询"],
    "22-es-bm25-retrieval.md": ["倒排", "词频", "IDF", "长度", "avgdl"],
    "23-lightrag-graph-retrieval.md": ["抽取", "合并", "原文", "local", "global", "hybrid"],
    "24-hybrid-retrieval-to-evidence.md": ["召回", "RRF", "精排", "上下文"],
    "25-agentic-rag-interview-focus.md": ["循环", "工具结果", "知识工具"],
}
for name, topics in required_topics.items():
    content = (ROOT / "docs" / name).read_text()
    for topic in topics:
        check(topic in content, f"missing topic {topic} in {name}")
bm25 = (ROOT / "docs/22-es-bm25-retrieval.md").read_text()
for frequency in (1, 2, 10):
    factor = frequency * (1.2 + 1) / (frequency + 1.2)
    check(f"{factor:.2f}" in bm25, "BM25 saturation example mismatch")

print(f"checks={checks} failures={len(failures)}")
for failure in failures:
    print(f"FAIL: {failure}")
raise SystemExit(bool(failures))
