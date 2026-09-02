# P3 知识写路径 Hermetic 测试报告

> 执行日期：2026-09-01  
> 源码：`98894c2c42c015a3c874c6b3c986ac863c85b731`  
> 环境：`maven:3.9.11-eclipse-temurin-17`，独立 Maven 缓存卷，无数据库、Broker、对象存储或模型服务

## 1. 执行结果

| 组 | Maven 范围 | 测试类 | 用例数 | 结果 | 原始日志 |
|---|---|---|---:|---|---|
| MQ adapter | `framework -am` | `RocketMQProducerAdapterTest` | 4 | PASS | `evidence/runtime/p3-hermetic-framework-2026-09-01.txt` |
| 写路径核心 | `rag -am` | 6 个测试类 | 23 | PASS | `evidence/runtime/p3-hermetic-rag-2026-09-01.txt` |

总计：**27 个用例，0 failure，0 error，0 skipped**。这是两条独立 Maven 执行的合计，不是 Surefire 单次汇总。

## 2. 第二组实际覆盖

| 测试类 | 用例数 | 本次可确认的边界 |
|---|---:|---|
| `ChunkingFixtureTest` | 1 | 当前分块 fixture 与预期结果一致 |
| `IngestionSpecCodecTest` | 5 | 摄取 spec 的默认值、序列化/反序列化与非法配置边界 |
| `ScheduleRefreshProcessorTest` | 5 | 锁心跳、文件切换、状态写回失败与 lease 释放分支 |
| `RemoteFileFetcherTest` | 4 | 远程文件协议、响应和大小/内容相关防线 |
| `IngestionTaskServiceImplTest` | 4 | 通用摄取任务状态与服务级行为 |
| `IngestionEngineTest` | 4 | 单根 nextNode 链执行、节点顺序及异常/定义边界 |

## 3. 如何读日志里的 ERROR

两组测试都故意注入失败：

- MQ adapter 用 `RuntimeException("broker unavailable")` 验证失败清理；
- 定时刷新用 `RuntimeException("boom")`、`heartbeat rejected` 等验证失败结算。

因此“日志出现 ERROR/堆栈”不是测试失败的充分条件。判定依据是对应测试断言、Surefire 汇总和 Maven 退出码：

```text
framework: Tests run: 4, Failures: 0, Errors: 0, Skipped: 0
framework: BUILD SUCCESS

rag:       Tests run: 23, Failures: 0, Errors: 0, Skipped: 0
rag:       BUILD SUCCESS
```

## 4. 本报告没有越权声称的内容

- 没有声称 RocketMQ Broker 可用；MQ 测试使用 mock template。
- 没有声称上传后已写入对象存储、数据库、Chunk 或 pgvector。
- 没有声称 `DocumentStatus.SUCCESS` 一定可召回。
- 没有声称远程 URL 在公网环境可用；测试用本地 mock server/fixture。
- 没有把编译 453 个 `rag` 主源码文件当作端到端成功。

## 5. 可复现命令

命令在 `runtime-work/AsterRAG` 工作副本运行，缓存卷名称只属于本教程：

```bash
TUTORIAL_WORKSPACE=/absolute/path/to/AsterRAG-Tutorial
docker run --rm \
  -v "${TUTORIAL_WORKSPACE}/runtime-work/AsterRAG:/workspace" \
  -v asterrag-tutorial-m2:/root/.m2 \
  -w /workspace \
  maven:3.9.11-eclipse-temurin-17 \
  mvn -pl framework -am \
    -Dtest=RocketMQProducerAdapterTest \
    -Dsurefire.failIfNoSpecifiedTests=false test
```

```bash
TUTORIAL_WORKSPACE=/absolute/path/to/AsterRAG-Tutorial
docker run --rm \
  -v "${TUTORIAL_WORKSPACE}/runtime-work/AsterRAG:/workspace" \
  -v asterrag-tutorial-m2:/root/.m2 \
  -w /workspace \
  maven:3.9.11-eclipse-temurin-17 \
  mvn -pl rag -am \
    -Dtest=IngestionEngineTest,IngestionTaskServiceImplTest,IngestionSpecCodecTest,RemoteFileFetcherTest,ScheduleRefreshProcessorTest,ChunkingFixtureTest \
    -Dsurefire.failIfNoSpecifiedTests=false test
```
