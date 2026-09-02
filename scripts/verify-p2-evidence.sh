#!/usr/bin/env bash

set -euo pipefail

workspace_dir="$(cd "$(dirname "$0")/.." && pwd)"

required_docs=(
  "docs/00-03-detailed-outline.md"
  "docs/04-20-chapter-cards.md"
  "evidence/chapter-claim-map.csv"
  "evidence/diagram-qa.md"
)

diagram_bases=(
  "assets/architecture/system-overview"
  "assets/diagrams/ingestion-sequence"
  "assets/diagrams/rag-sequence"
  "assets/diagrams/agent-sequence"
  "assets/diagrams/state-ownership"
)

for relative_path in "${required_docs[@]}"; do
  if [[ ! -s "$workspace_dir/$relative_path" ]]; then
    printf 'FAIL missing P2 document: %s\n' "$relative_path" >&2
    exit 1
  fi
done
printf 'PASS P2 documents=%s\n' "${#required_docs[@]}"

for diagram_base in "${diagram_bases[@]}"; do
  for extension in mmd svg png; do
    diagram_path="$workspace_dir/$diagram_base.$extension"
    if [[ ! -s "$diagram_path" ]]; then
      printf 'FAIL missing diagram artifact: %s\n' "$diagram_path" >&2
      exit 1
    fi
  done
  grep -q '<svg' "$workspace_dir/$diagram_base.svg"
done
printf 'PASS diagram triplets=%s\n' "${#diagram_bases[@]}"

grep -q 'DefaultIngestionKernel' "$workspace_dir/assets/architecture/system-overview.mmd"
grep -q '/ingestion/tasks' "$workspace_dir/assets/architecture/system-overview.mmd"
grep -q 'ProcessMode PIPELINE 当前暂停' "$workspace_dir/assets/architecture/system-overview.mmd"
grep -q '具体 save/load 时点待依赖源码核验' "$workspace_dir/assets/diagrams/agent-sequence.mmd"
printf 'PASS critical diagram boundaries present\n'

for chapter in 0 1 2 3; do
  grep -q "第 ${chapter} 章" "$workspace_dir/docs/00-03-detailed-outline.md"
done
for chapter in $(seq 4 20); do
  grep -q "第 ${chapter} 章" "$workspace_dir/docs/04-20-chapter-cards.md"
done
printf 'PASS chapter skeleton covers 0-20\n'

python3 - "$workspace_dir" <<'PY'
import csv
import pathlib
import sys

workspace = pathlib.Path(sys.argv[1])
with (workspace / "evidence/source-map.csv").open(newline="", encoding="utf-8") as handle:
    source_rows = list(csv.DictReader(handle))
with (workspace / "evidence/chapter-claim-map.csv").open(newline="", encoding="utf-8") as handle:
    chapter_rows = list(csv.DictReader(handle))

source_ids = [row["claim_id"] for row in source_rows]
chapter_ids = [row["claim_id"] for row in chapter_rows]
if len(chapter_ids) != len(set(chapter_ids)):
    raise SystemExit("FAIL duplicate chapter claim allocation")
if set(source_ids) != set(chapter_ids):
    missing = sorted(set(source_ids) - set(chapter_ids))
    extra = sorted(set(chapter_ids) - set(source_ids))
    raise SystemExit(f"FAIL chapter claim mismatch missing={missing} extra={extra}")

covered_chapters = set()
for row in chapter_rows:
    primary = int(row["primary_chapter"])
    if not 0 <= primary <= 20:
        raise SystemExit(f"FAIL invalid primary chapter {row}")
    covered_chapters.add(primary)
    for value in row["supporting_chapters"].split(";"):
        if value:
            chapter = int(value)
            if not 0 <= chapter <= 20:
                raise SystemExit(f"FAIL invalid supporting chapter {row}")
            covered_chapters.add(chapter)

if covered_chapters != set(range(21)):
    raise SystemExit(f"FAIL claim allocation does not touch chapters: {sorted(set(range(21)) - covered_chapters)}")
print(f"PASS chapter claims={len(chapter_rows)} chapters=0-20")
PY

printf 'PASS P2 evidence verification complete\n'

