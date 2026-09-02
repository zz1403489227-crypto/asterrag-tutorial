#!/usr/bin/env bash

set -euo pipefail

workspace_dir="$(cd "$(dirname "$0")/.." && pwd)"
source_dir="$workspace_dir/sources/AsterRAG"

required_files=(
  "$workspace_dir/evidence/source-census.md"
  "$workspace_dir/evidence/test-matrix.md"
  "$workspace_dir/evidence/call-chains.md"
  "$workspace_dir/evidence/architecture-node-map.md"
  "$workspace_dir/evidence/reference-drift.md"
  "$workspace_dir/evidence/source-map.csv"
  "$workspace_dir/evidence/reviews/open-questions.md"
)

for path in "${required_files[@]}"; do
  if [[ ! -s "$path" ]]; then
    printf 'FAIL required evidence missing or empty: %s\n' "$path" >&2
    exit 1
  fi
done
printf 'PASS required P1 evidence files=%s\n' "${#required_files[@]}"

"$workspace_dir/scripts/verify-source-lock.sh"

python3 - "$workspace_dir" "$source_dir" <<'PY'
import csv
import pathlib
import sys

workspace = pathlib.Path(sys.argv[1])
source = pathlib.Path(sys.argv[2])
csv_path = workspace / "evidence/source-map.csv"
allowed = {
    "verified-source",
    "verified-test",
    "verified-runtime",
    "reference-only",
    "pending",
}

with csv_path.open(newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))

expected_fields = [
    "claim_id",
    "chapter",
    "claim",
    "source_commit",
    "path",
    "symbol",
    "test_anchor",
    "runtime_evidence",
    "status",
]
if not rows:
    raise SystemExit("FAIL source-map has no claims")
if list(rows[0]) != expected_fields:
    raise SystemExit(f"FAIL source-map header: {list(rows[0])}")
if len({row["claim_id"] for row in rows}) != len(rows):
    raise SystemExit("FAIL duplicate claim_id")
unknown = sorted({row["status"] for row in rows} - allowed)
if unknown:
    raise SystemExit(f"FAIL unknown statuses: {unknown}")

missing = []
for row in rows:
    for raw_path in row["path"].split(";"):
        raw_path = raw_path.strip()
        if not raw_path or raw_path.startswith(("http://", "https://")):
            continue
        candidate = workspace / raw_path if raw_path.startswith("evidence/") else source / raw_path
        if not candidate.exists():
            missing.append((row["claim_id"], raw_path))
    for raw_anchor in row["test_anchor"].split(";"):
        raw_path = raw_anchor.split("#", 1)[0].strip()
        if not raw_path:
            continue
        candidate = workspace / raw_path if raw_path.startswith("scripts/") else source / raw_path
        if not candidate.exists():
            missing.append((row["claim_id"], raw_path))

if missing:
    rendered = ", ".join(f"{claim}:{path}" for claim, path in missing)
    raise SystemExit(f"FAIL missing anchors: {rendered}")

source_claims = sum(row["status"] == "verified-source" for row in rows)
reference_claims = sum(row["status"] == "reference-only" for row in rows)
print(f"PASS source-map claims={len(rows)} verified-source={source_claims} reference-only={reference_claims}")
PY

grep -q 'DefaultIngestionKernel' "$workspace_dir/TUTORIAL_DEVELOPMENT_PLAN.md"
grep -q 'PIPELINE 模式当前暂停' "$workspace_dir/TUTORIAL_DEVELOPMENT_PLAN.md"
grep -q '三条主调用链' "$workspace_dir/TUTORIAL_DEVELOPMENT_PLAN.md"
printf 'PASS plan reflects active ingestion boundary and three main call chains\n'

printf 'PASS P1 static evidence verification complete\n'

