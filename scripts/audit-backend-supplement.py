#!/usr/bin/env python3
"""Read-only tutorial/source audit. Never starts the application or evaluator."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NAMES = [
    "35-backend-request-map.md",
    "36-backend-spring-in-project.md",
    "37-backend-persistence-in-project.md",
    "38-backend-redis-in-project.md",
    "39-backend-streaming-in-project.md",
    "40-backend-java-interview.md",
    "41-backend-spring-mybatis-interview.md",
    "42-backend-database-interview.md",
    "43-backend-redis-interview.md",
    "44-backend-network-and-mock-interview.md",
]
checks = 0
failures = []


def check(ok, message):
    global checks
    checks += 1
    if not ok:
        failures.append(message)


readme = (ROOT / "README.md").read_text()
chapters = {}
published = [ROOT / "BACKEND_INTERVIEW_SUPPLEMENT_PLAN.md",
             ROOT / "appendices/backend-source-and-interview-map.md"]
for name in NAMES:
    path = ROOT / "docs" / name
    check(path.is_file(), f"missing chapter: {name}")
    if not path.is_file():
        continue
    body = path.read_text()
    number = int(name[:2])
    chapters[number] = body
    published.append(path)
    check(body.startswith(f"# 第 {number} 章"), f"chapter title: {name}")
    check(f"docs/{name}" in readme, f"homepage link: {name}")
    check("第一部分" in body if number < 40 else "第二部分" in body,
          f"two-part placement: {name}")
    check("../README.md" in body, f"return link: {name}")
    check("backend-source-and-interview-map.md" in body, f"evidence link: {name}")
    check(len(re.findall(r"[\u4e00-\u9fff]", body)) >= 1200, f"unexpectedly short chapter: {name}")

for path in published:
    body = path.read_text()
    check(len(re.findall(r"^```", body, re.M)) % 2 == 0, f"unclosed fence: {path.name}")
    check(not re.search(r"/Users/|/data2/|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]+", body),
          f"private path or credential shape: {path.name}")
    check("agent_interviews.db" not in body, f"private database filename: {path.name}")
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", body):
        if not target.startswith(("https://", "http://", "#")):
            check((path.parent / target.split("#")[0]).exists(), f"broken local link: {path.name}: {target}")

required = {
    35: ["flowchart", "userId", "conversationId", "taskId", "Python"],
    36: ["dependencyManagement", "ReActAgentProvider", "单例", "UserContext", "Mapper"],
    37: ["replyToMessageId", "4N+1", "部分唯一索引", "ORDER BY id", "afterCommit", "最终一致性"],
    38: ["RBucket", "compareAndSet", "watchdog", "注册", "至多一次", "fencing"],
    39: ["CAS", "volatile", "synchronized", "CallerRunsPolicy", "orTimeout", "boundedElastic"],
    40: ["ConcurrentHashMap", "happens-before", "ThreadLocal", "OOM", "类加载"],
    41: ["情况 A", "情况 B", "情况 C", "REQUIRES_NEW", "#{", "${", "逻辑删除"],
    42: ["a=1 AND c=1", "MVCC", "heap", "WAL", "EXPLAIN ANALYZE", "HNSW"],
    43: ["listpack", "击穿", "雪崩", "RDB", "AOF", "Lua", "语义缓存"],
    44: ["Last-Event-ID", "幂等", "教学估算", "第一组", "第二组", "第三组"],
}
for number, needles in required.items():
    for needle in needles:
        check(needle in chapters.get(number, ""), f"coverage missing: {number}: {needle}")

manifest = json.loads((ROOT / "evidence/backend-source-map.json").read_text())
source = ROOT / "sources/AsterRAG"
check(source.is_dir(), "missing source checkout: sources/AsterRAG")
if source.is_dir():
    result = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                            text=True, capture_output=True, check=False)
    check(result.returncode == 0 and result.stdout.strip() == manifest["baseline"], "source baseline drift")
    for entry in manifest["entries"]:
        path = source / entry["path"]
        check(path.is_file(), f"source path: {entry['id']}")
        if path.is_file():
            text = path.read_text()
            for needle in entry["needles"]:
                check(needle in text, f"source anchor: {entry['id']}: {needle}")
        check(all(35 <= n <= 44 for n in entry["chapters"]), f"chapter mapping: {entry['id']}")

appendix = (ROOT / "appendices/backend-source-and-interview-map.md").read_text()
for number in (307, 309, 327, 403, 462, 726, 729, 787, 1094, 1103, 1140, 1262, 1347, 1449, 1474, 1484):
    check(str(number) in appendix, f"interview theme map: {number}")
check(appendix.count("https://www.nowcoder.com/") >= 10, "public interview sources")
for entry in manifest["entries"]:
    check(f"/blob/{manifest['baseline']}/{entry['path']}" in appendix, f"frozen source link: {entry['id']}")
check(900000 * 2 / 60000 == 30, "gate TTL calculation")
check(5 * 20 == 100, "illustrative concurrency arithmetic")
chinese_characters = sum(len(re.findall(r"[\u4e00-\u9fff]", t)) for t in chapters.values())
print(f"chapters={len(chapters)} chinese_characters={chinese_characters}")
print(f"checks={checks} failures={len(failures)}")
for failure in failures:
    print(f"FAIL: {failure}")
raise SystemExit(bool(failures))
