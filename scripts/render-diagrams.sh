#!/usr/bin/env bash

set -euo pipefail

workspace_dir="$(cd "$(dirname "$0")/.." && pwd)"
mermaid_version="11.12.0"

diagram_sources=(
  "assets/architecture/system-overview.mmd"
  "assets/diagrams/ingestion-sequence.mmd"
  "assets/diagrams/rag-sequence.mmd"
  "assets/diagrams/agent-sequence.mmd"
  "assets/diagrams/state-ownership.mmd"
)

cd "$workspace_dir"
for diagram_source in "${diagram_sources[@]}"; do
  svg_output="${diagram_source%.mmd}.svg"
  png_output="${diagram_source%.mmd}.png"
  npx -y "@mermaid-js/mermaid-cli@${mermaid_version}" \
    -i "$diagram_source" -o "$svg_output" -b transparent
  npx -y "@mermaid-js/mermaid-cli@${mermaid_version}" \
    -i "$diagram_source" -o "$png_output" -b white -w 2400
  printf 'PASS rendered %s -> %s, %s\n' "$diagram_source" "$svg_output" "$png_output"
done

