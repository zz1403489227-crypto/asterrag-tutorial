#!/usr/bin/env python3
"""Static release audit for the source-aligned AsterRAG tutorial.

This checks tutorial integrity and source anchors. It deliberately does not start
the application or claim runtime correctness.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sources" / "AsterRAG"

CHAPTERS = [
    "00-reading-contract.md",
    "01-system-architecture.md",
    "02-modules-and-runtime.md",
    "03-state-ownership.md",
    "04-document-entry.md",
    "05-parsing.md",
    "06-ingestion.md",
    "07-chunking-and-indexing.md",
    "08-request-sse-lifecycle.md",
    "09-memory-and-rewrite.md",
    "10-intent-and-scope.md",
    "11-multi-channel-retrieval.md",
    "12-retrieval-postprocessing.md",
    "13-answer-generation-and-trace.md",
    "14-agent-vs-workflow.md",
    "15-agent-tools.md",
    "16-agent-state-memory-finalization.md",
    "17-engineering-guardrails.md",
    "18-frontend-state-and-evidence.md",
    "19-configuration-and-failure-reasoning.md",
    "20-interview-narrative.md",
    "21-hnsw-vector-index.md",
    "22-es-bm25-retrieval.md",
    "23-lightrag-graph-retrieval.md",
    "24-hybrid-retrieval-to-evidence.md",
    "25-agentic-rag-interview-focus.md",
    "26-evaluation-overview.md",
    "27-evaluation-dataset.md",
    "28-evaluation-recording.md",
    "29-evaluation-deterministic-metrics.md",
    "30-evaluation-ragas-judge.md",
    "31-evaluation-diagnosis-and-interview.md",
]

APPENDICES = [
    "interview-question-bank.md",
    "glossary.md",
    "source-index.md",
    "retrieval-implementation-notes.md",
    "evaluation-implementation-notes.md",
]

DIAGRAMS = [
    "assets/architecture/system-overview",
    "assets/diagrams/ingestion-sequence",
    "assets/diagrams/rag-sequence",
    "assets/diagrams/agent-sequence",
    "assets/diagrams/state-ownership",
    "assets/diagrams/evaluation-overview",
    "assets/diagrams/evaluation-recording",
    "assets/diagrams/evaluation-diagnosis",
]

REPO_PREFIXES = (
    "framework/",
    "infra-ai/",
    "system/",
    "rag/",
    "agent/",
    "bootstrap/",
    "mcp-server/",
    "frontend/",
    "resources/",
)
ROOT_SOURCE_FILES = {"README.md", "NOTICE", "LICENSE", "pom.xml", "docs/UPSTREAM.md"}


failures: list[str] = []
warnings: list[str] = []
checks = 0


def check(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(message)


def published_markdown() -> list[Path]:
    return [ROOT / "README.md"] + [ROOT / "docs" / name for name in CHAPTERS] + [
        ROOT / "appendices" / name for name in APPENDICES
    ]


def strip_anchor(target: str) -> str:
    return target.split("#", 1)[0]


def validate_files() -> None:
    for name in CHAPTERS:
        check((ROOT / "docs" / name).is_file(), f"missing chapter: docs/{name}")
    for name in APPENDICES:
        check((ROOT / "appendices" / name).is_file(), f"missing appendix: appendices/{name}")
    check((ROOT / "README.md").is_file(), "missing root README.md")


def validate_markdown() -> None:
    md_link = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
    image_link = re.compile(r"!\[[^]]*\]\(([^)]+)\)")

    for path in published_markdown():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        check(text.count("```") % 2 == 0, f"unclosed fenced block: {path.relative_to(ROOT)}")
        check(text.startswith("# "), f"missing H1 at start: {path.relative_to(ROOT)}")

        # Markdown-looking examples inside fenced/inline code are not links.
        link_text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        link_text = re.sub(r"`[^`\n]*`", "", link_text)
        for target in md_link.findall(link_text) + image_link.findall(link_text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            clean = strip_anchor(target)
            if not clean:
                continue
            resolved = (path.parent / clean).resolve()
            check(resolved.exists(), f"broken local link in {path.relative_to(ROOT)}: {target}")


def validate_navigation() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for name in CHAPTERS:
        check(f"docs/{name}" in readme, f"README does not link chapter: {name}")
    for name in APPENDICES:
        check(f"appendices/{name}" in readme, f"README does not link appendix: {name}")

    for number, name in enumerate(CHAPTERS):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        check(
            re.search(rf"^# \u7b2c {number} \u7ae0", text, re.MULTILINE) is not None,
            f"chapter number/title mismatch: docs/{name}",
        )


def validate_diagrams() -> None:
    for stem in DIAGRAMS:
        for suffix in (".mmd", ".svg", ".png"):
            check((ROOT / f"{stem}{suffix}").is_file(), f"missing diagram artifact: {stem}{suffix}")


def validate_question_bank() -> None:
    path = ROOT / "appendices" / "interview-question-bank.md"
    text = path.read_text(encoding="utf-8")
    numbers = [int(value) for value in re.findall(r"^### Q(\d+)[：:]", text, re.MULTILINE)]
    check(numbers == list(range(1, 101)), "interview question numbering is not exactly Q1..Q100")


def validate_source_map() -> None:
    path = ROOT / "evidence" / "source-map.csv"
    check(path.is_file(), "missing evidence/source-map.csv")
    if not path.is_file():
        return

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    check(len(rows) == 41, f"source-map row count changed: expected 41, got {len(rows)}")
    check(len({row["claim_id"] for row in rows}) == len(rows), "duplicate claim_id in source-map")

    for row in rows:
        anchor = row["path"].strip()
        if anchor.startswith(("http://", "https://", "evidence/")):
            continue
        for item in anchor.split(";"):
            item = item.strip()
            if not item:
                continue
            check((SOURCE / item).exists(), f"source-map {row['claim_id']} missing source path: {item}")


def validate_precise_inline_source_paths() -> None:
    token_pattern = re.compile(r"`([^`\n]+)`")
    for path in published_markdown():
        if not path.is_file():
            continue
        for token in token_pattern.findall(path.read_text(encoding="utf-8")):
            for item in token.split(";"):
                item = item.strip()
                looks_like_path = item in ROOT_SOURCE_FILES or (
                    item.startswith(REPO_PREFIXES)
                    and ("." in Path(item).name or item.endswith("/"))
                )
                if looks_like_path:
                    if any(mark in item for mark in ("*", "...", " + ", " → ")):
                        warnings.append(f"non-exact source token in {path.relative_to(ROOT)}: {item}")
                        continue
                    clean = item.split("#", 1)[0]
                    check((SOURCE / clean).exists(), f"missing inline source path in {path.relative_to(ROOT)}: {item}")


def validate_provenance_and_scope() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    chapter20 = (ROOT / "docs" / "20-interview-narrative.md").read_text(encoding="utf-8")
    plan = (ROOT / "TUTORIAL_DEVELOPMENT_PLAN.md").read_text(encoding="utf-8")

    check("nageoffer/ragent" in readme, "README omits upstream repository attribution")
    check("Apache-2.0" in readme, "README omits Apache-2.0 attribution")
    check("98894c2c42c015a3c874c6b3c986ac863c85b731" in readme, "README omits frozen source SHA")
    check("不以部署复现为目标" in readme, "README omits non-reproduction learning goal")
    check("不是从零原创" in chapter20 or "不是我从零写" in chapter20, "chapter 20 lacks explicit from-scratch boundary")
    check("读者不需要实际部署或复现项目" in plan, "plan lost the learning-not-reproduction scope")


def main() -> int:
    check(ROOT.is_dir(), f"tutorial root missing: {ROOT}")
    check(SOURCE.is_dir(), f"frozen AsterRAG source missing: {SOURCE}")
    validate_files()
    validate_markdown()
    validate_navigation()
    validate_diagrams()
    validate_question_bank()
    validate_source_map()
    validate_precise_inline_source_paths()
    validate_provenance_and_scope()

    print(f"checks={checks}")
    print(f"failures={len(failures)}")
    print(f"warnings={len(warnings)}")
    for message in warnings:
        print(f"WARN: {message}")
    for message in failures:
        print(f"FAIL: {message}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
