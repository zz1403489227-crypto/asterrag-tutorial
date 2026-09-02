#!/usr/bin/env bash
set -euo pipefail

workspace="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

check_repo() {
  local name="$1"
  local expected_head="$2"
  local expected_tree="$3"
  local repo="$workspace/sources/$name"

  test -d "$repo/.git"
  local actual_head
  local actual_tree
  actual_head="$(git -C "$repo" rev-parse HEAD)"
  actual_tree="$(git -C "$repo" rev-parse 'HEAD^{tree}')"

  if [[ "$actual_head" != "$expected_head" ]]; then
    printf 'FAIL %s HEAD expected=%s actual=%s\n' "$name" "$expected_head" "$actual_head" >&2
    return 1
  fi
  if [[ "$actual_tree" != "$expected_tree" ]]; then
    printf 'FAIL %s tree expected=%s actual=%s\n' "$name" "$expected_tree" "$actual_tree" >&2
    return 1
  fi
  if [[ -n "$(git -C "$repo" status --porcelain)" ]]; then
    printf 'FAIL %s worktree is dirty\n' "$name" >&2
    git -C "$repo" status --short >&2
    return 1
  fi
  printf 'PASS %s head=%s tree=%s clean=true\n' "$name" "$actual_head" "$actual_tree"
}

check_repo AsterRAG \
  98894c2c42c015a3c874c6b3c986ac863c85b731 \
  19b1702464b756670138554e70894ede5ba4198a
check_repo ragent-upstream \
  1cb684ed5df03f241d90c836466465f6aab37800 \
  1fb1efdf6595f2406cc4822544d5819a09565864
check_repo how-claude-code-works \
  f4d6505ed9162a0ee6be089190f74c419ecacb19 \
  36e3674cf0162e1d0547bca62e23eeef56edfd52

tag_commit="$(git -C "$workspace/sources/ragent-upstream" rev-parse 'refs/tags/1.0.0^{commit}')"
if [[ "$tag_commit" != "5500546c4e4742752adaaebf51c9423bef5f3497" ]]; then
  printf 'FAIL ragent 1.0.0 tag expected=%s actual=%s\n' \
    5500546c4e4742752adaaebf51c9423bef5f3497 "$tag_commit" >&2
  exit 1
fi
printf 'PASS ragent-tag-1.0.0 commit=%s\n' "$tag_commit"

