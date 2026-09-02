# 第 6 章：入库主循环——事务消息、固定摄取内核与可配置 Pipeline

> 本章要拆开全书最容易讲错的一组概念：仓库里同时存在“知识文档的固定五步摄取主链”和“通用可配置 IngestionEngine”，但它们在冻结提交中不能被说成同一条默认流程。

## 6.1 先给出完整地图

### 6.1.1 当前知识文档主链

```text
POST /knowledge-base/docs/{doc-id}/chunk
  → KnowledgeDocumentServiceImpl.startChunk
  → RocketMQ 事务消息
      └─ 本地事务：文档状态改为 RUNNING
  → KnowledgeDocumentChunkConsumer
  → KnowledgeDocumentServiceImpl.executeChunk / runChunkTask
  → DefaultIngestionKernel.run
       ① MIME identity
       ② parse
       ③ chunk
       ④ embed
       ⑤ index
  → 文档状态 + 分块日志收尾
```

### 6.1.2 独立的通用摄取子系统

```text
POST /ingestion/tasks  或  /ingestion/tasks/upload
  → IngestionTaskServiceImpl
  → 从 t_ingestion_pipeline / t_ingestion_pipeline_node 读取 PipelineDefinition
  → IngestionEngine
  → Fetcher / Parser / Enhancer / Chunker / Enricher / Indexer
  → t_ingestion_task / t_ingestion_task_node
```

它们共用 Parser、Block、Chunking、Embedding 和向量写入能力，但触发入口、任务状态和当前可用性不同。

## 6.2 `startChunk`：为什么要用 RocketMQ 事务消息

### 6.2.1 一次请求里需要协调两件事

用户点击“开始分块”时，系统希望两个事实一致：

1. 数据库里的文档已经被标记为 `RUNNING`；
2. 用于异步摄取的 RocketMQ 消息可以被消费。

如果先改数据库后发普通消息，发送失败时文档会卡在 `RUNNING`；如果先发消息后改数据库，消费者可能在本地状态就绪前开始执行。

`startChunk` 因此调用 `MessageQueueProducer.sendInTransaction`。事件载荷只包含需要跨线程/跨进程传递的核心信息：

- `docId`；
- 操作者用户名，消费时用于重建 `UserContext`；
- 本地事务内还会补充 `kbId`。

### 6.2.2 本地事务不只是简单 `update status`

`startChunk` 的本地事务用条件更新争抢文档运行权：

```text
UPDATE document
SET status = RUNNING, updatedBy = operator, updateTime = now
WHERE id = docId AND status != RUNNING
```

更新行数为 0 时，Service 再查一次文档：文档不存在就报不存在，否则报“分块操作正在进行中”。这比“先 select 判断、再 update”更能避免两个请求同时看到非 RUNNING，然后都开始任务。

本地事务同时调用 `scheduleService.upsertSchedule(documentDO)`，让 URL 文档的调度定义与当前文档配置保持对齐。

### 6.2.3 Framework 层如何执行本地事务

`RocketMQProducerAdapter` 为每条事务消息生成 `txId`，把本地事务回调暂存在 `DelegatingTransactionListener.localTransactionMap`，然后将 `txId` 和 topic 放进消息 header。

RocketMQ 回调 `executeLocalTransaction` 时：

1. Listener 用 `remove(txId)` 取出一次性回调；
2. 用 Spring `TransactionTemplate` 执行这个回调；
3. 成功返回 `COMMIT`，异常返回 `ROLLBACK`；
4. 发送抛错或发送状态不是 `SEND_OK` 时，Producer 会删除还未执行的内存回调。

这个 map 是进程内短命状态，不是事务事实的持久存储。如果 Broker 后续发起回查，系统不依赖这个 map，而是走 per-topic `TransactionChecker`。

### 6.2.4 Broker 回查时为什么查数据库

`KnowledgeDocumentChunkTransactionChecker` 在启动时按 topic 注册自己。回查时它从消息中取 `docId`，再查 `KnowledgeDocumentDO`：

```text
文档存在 AND status == RUNNING  → COMMIT
否则                               → ROLLBACK
回查本身抛异常                  → UNKNOWN
```

回查可能被发到任意应用实例，所以不能依赖发送实例的内存 map。数据库中的 `RUNNING` 才是本地事务已成功的可跨实例事实。

## 6.3 消费者：重建操作者上下文，然后交还业务层

`KnowledgeDocumentChunkConsumer` 的代码很短，但有两个责任：

1. 用事件中的 operator 重建 `UserContext`；
2. 调用 `documentService.executeChunk(docId)`，并在 `finally` 中清除上下文。

它不自己处理 MIME、Parser、Chunk 或数据库状态，避免把业务逻辑塞进 MQ 适配层。

`executeChunk` 首先重新查文档。如果文档已不存在，只记录告警并返回；否则进入 `runChunkTask`。

## 6.4 `runChunkTask`：业务任务 owner

### 6.4.1 它先解决四个“本次到底是谁”

`runChunkTask` 不会直接把文档 DO 扔给内核。它先派生：

- `ProcessMode`：直接分块还是 Pipeline；
- `VectorTarget`：知识库对应的逻辑分区、Embedding 模型和维度；
- `IngestionSpec`：文档级 ParseProfile 和 ChunkBudget；
- `DocumentRef`：`docId`、`kbId`、文件名。

这四个对象把“业务 DO 上的字段”翻译成“摄取内核所需的最小契约”。

### 6.4.2 任务日志在调用内核前就建立

Service 先插入一条 `KnowledgeDocumentChunkLogDO`，初始状态为 `RUNNING`，记录：

- 文档 ID；
- 处理模式；
- 解析档位；
- Pipeline ID；
- 开始时间。

内核完成后，Service 再将 parse/chunk/embed/index 四段耗时、总耗时和 Chunk 数回填到这条日志。

### 6.4.3 直接分块模式调用固定内核

Service 从对象存储打开 `fileUrl`，读取原始字节，然后调用：

```java
ingestionKernel.run(doc, bytes, spec, target)
```

成功后：

1. 用内核从真实字节检测到的 MIME 刷新文档 `mimeType`；
2. 将文档状态改为 `SUCCESS`，更新 `chunkCount`；
3. 将分块日志改为 `SUCCESS`，回填分阶段耗时。

失败时：

1. 捕获异常并记录；
2. 将文档状态改为 `FAILED`；
3. 将分块日志改为 `FAILED`，保存错误消息；
4. **异常不再向消费者抛出。**

第 4 点非常关键。它意味着 RocketMQ 在这条链路中保障的是“异步任务能在本地 `RUNNING` 事实成立后被投递”；一旦 `runChunkTask` 已经捕获并持久化业务失败，消费者不会因这个业务异常而触发 RocketMQ 重试。后续重做依赖再次显式发起分块，不是对所有 Parser/Embedding/索引失败无限自动重试。

## 6.5 `DefaultIngestionKernel`：不可换序的五步骨架

### 6.5.1 输入契约

```java
run(DocumentRef doc,
    byte[] bytes,
    IngestionSpec spec,
    VectorTarget target)
```

刻意不让调用方传入两样东西：

- **MIME**：内核必须从字节+文件名自己识别，避免调用方传一个与字节不一致的类型；
- **Embedding 默认模型**：模型和维度必须从 `VectorTarget` 显式传入，不允许文档级配置随意改变同一向量空间的语义模型。

`IngestionSpec` 只持有文档级自由度：`ParseProfile` 和 `ChunkBudget`。

### 6.5.2 五步不变式

| 阶段 | 输入 | 输出 | 失败门槛 |
|---|---|---|---|
| ① identity | bytes + filename | MIME | 字节空或无法识别 |
| ② parse | MIME + profile + parser options | `List<Block>` | 无 Parser、Parser 异常 |
| ③ chunk | Blocks + budget | `List<Chunk>` | 空分块结果 |
| ④ embed | Chunk.embeddingText + VectorTarget | `List<EmbeddedChunk>` | 返回数量错、空向量、维度错 |
| ⑤ index | DocumentRef + EmbeddedChunks + target | 所有 `ChunkSink` 替换结果 | 任一强一致写入失败 |

内核返回 `IngestionOutcome`，其中只有识别到的 MIME、实际 Parser、Block 数、最终 Chunk 和四段耗时。向量不再返回，因为第五步已经把它写入索引落点。

### 6.5.3 内核明确不拥有任务状态

`IngestionKernel` 的注释明确说：取数是内核之前的事，任务状态与摄取日志归外层。这个责任分工让同一内核可以被：

- 普通用户显式分块调用；
- 定时刷新 Processor 调用；
- 未来其他任务 owner 调用。

不同 owner 可以用自己的状态表和日志，内核只保证五步业务顺序。

## 6.6 通用 `IngestionEngine`：它是什么，又不是什么

### 6.6.1 PipelineDefinition 是单链定义

`PipelineDefinition` 包含一组 `NodeConfig`。每个节点只有：

- `nodeId`；
- `nodeType`；
- JSON `settings`；
- JSON `condition`；
- 唯一一个 `nextNodeId`。

因此它不是任意 DAG 引擎：一个节点没有多条输出边，引擎要求全图恰好一个起点，然后沿 `nextNodeId` 链式执行。

### 6.6.2 Engine 执行前先校验结构

`IngestionEngine.execute` 会：

1. 将 context 状态设为 `RUNNING`；
2. 按 `nodeId` 建映射；
3. 沿 `nextNodeId` 检查环、丢失的下一节点；
4. 找出“没被任何人引用”的起始节点；
5. 无起点或多起点都报错；
6. 从唯一起点循环执行，并保留一个“执行节点数不得超过节点总数”的第二层死循环防护。

### 6.6.3 条件是“跳过当前节点”，不是分支跳转

`ConditionEvaluator` 支持布尔、SpEL 文本、`all/any/not` 组合和字段比较规则。条件不满足时，Engine 生成 `NodeResult.skip`：

- 记一条成功但状态为 skipped 的节点日志；
- `shouldContinue=true`；
- 继续走同一个 `nextNodeId`。

所以它能表达“这一节可选”，不能表达“条件 A 走 X，条件 B 走 Y”的图分支。

### 6.6.4 当前六种节点的责任

| Node | 输入上下文 | 主要输出 |
|---|---|---|
| `FetcherNode` | `DocumentSource` 或已预置 `rawBytes` | `rawBytes`、`mimeType`、文件名 |
| `ParserNode` | 字节、MIME、ParserSettings | `StructuredDocument`、`rawText` |
| `EnhancerNode` | 解析文本 + 增强任务配置 | `enhancedText` 等加工结果 |
| `ChunkerNode` | Blocks + `VectorTarget` + ChunkerSettings | 已向量化 `EmbeddedChunk` |
| `EnricherNode` | EmbeddedChunks + enrichment 任务 | 带关键词/问题等扩展元数据的块 |
| `IndexerNode` | EmbeddedChunks + 分区/空间配置 | 向量写入，或只准备块交由调用方统一写 |

### 6.6.5 任务与节点日志如何持久化

`IngestionTaskServiceImpl` 在调用 Engine 前插入 `t_ingestion_task`，状态为 `RUNNING`。Engine 在 `IngestionContext.logs` 中累积每个节点的：

- nodeId/nodeType；
- 成功、失败或跳过；
- 耗时；
- 消息、异常；
- `NodeOutputExtractor` 提取的输出摘要。

Engine 返回后，Service 把日志写入 `t_ingestion_task_node`，再把最终状态、Chunk 数、错误、日志摘要和元数据回填任务行。

Engine 对节点抛出的异常会转成 `NodeResult.fail`，之后停止链并将 context 设为 `FAILED`；这样 Service 可以保留失败任务和节点日志，而不是任何业务失败都直接抛出并回滚掉可观测记录。

## 6.7 两套摄取能力的当前真实边界

### 6.7.1 知识文档的 `ProcessMode.PIPELINE` 当前明确暂停

上传时，`resolveProcessModeConfig` 确实允许请求指定 Pipeline ID，并且会校验 Pipeline 存在。但 `runChunkTask` 在真正执行时有一个明确分支：

```java
if (ProcessMode.PIPELINE == processMode) {
    throw new ClientException("管道模式重构中，暂不可用，请改用直接分块...");
}
```

旁边保留了被注释的 `runPipelineProcess` 调用轮廓，但注释代码不是当前运行能力。所以教程必须说：

> 当前知识文档默认且可用的是固定五步 `DefaultIngestionKernel`；不能说它已经默认通过用户自定义 Pipeline 入库。

### 6.7.2 `/ingestion/tasks` 是单独的同步 API

`IngestionTaskController.create/upload` 直接调用 `IngestionTaskServiceImpl`，Service 在当前 HTTP 调用链内执行 Engine，没有经过知识文档的 RocketMQ topic。

它可以独立管理 Pipeline、任务和节点日志，但当前 `IngestionTaskServiceImpl.executeInternal` 只向 context 传入 `vectorSpaceId`，没有构造 `VectorTarget`；而当前 `ChunkerNode` 在入口显式要求 `context.vectorTarget != null`，否则返回“分块节点缺少向量落点”。现有节点中也没有一个节点会为 standalone task 设置它。

因此在当前冻结提交中，不能将 `/ingestion/tasks` 描述为一条已经默认闭环的“上传→分块→向量写入”替代主链。它是已经具备 Pipeline/Task/Node 模型和执行引擎的独立子系统，但完整向量链的调用方落点上下文尚未在这个 API 中闭合。

这不是对项目正确性的评判，而是教程对当前入口参数与节点前置条件的如实对齐。

## 6.8 责任与非责任

| 组件 | 负责 | 不负责 |
|---|---|---|
| `startChunk` | 设置 `RUNNING`、发事务消息、防重入 | 执行 Parser/Embedding |
| RocketMQ 事务适配 | 协调本地事务事实与消息投递 | 自动修复所有业务失败 |
| Consumer | 重建用户上下文并调用业务 Service | 拥有摄取业务逻辑 |
| `runChunkTask` | 解析业务配置、读文件、任务状态与日志收尾 | 实现五步内核算法 |
| `DefaultIngestionKernel` | 固定 identity→parse→chunk→embed→index | 取数、任务状态、业务日志 |
| `IngestionEngine` | 单链 Pipeline 校验、条件跳过、节点执行与内存日志 | 任意 DAG、当前知识文档默认入库 |
| `IngestionTaskServiceImpl` | 独立 task/node 持久化 | 知识文档的 `PENDING/RUNNING/SUCCESS` 状态 |

## 6.9 为什么这样设计

下列是从实现责任推导的解释：

- **事务消息只包围起动事实**：本地事务只把文档改为 `RUNNING`，重量摄取在消费端执行，避免 HTTP 请求持有长时数据库事务。
- **内核固定五步**：不让调用方跳过维度校验、换序索引写入，将核心数据不变式集中在一处。
- **任务 owner 与内核分开**：用户手动摄取和定时刷新可复用一套内核，但各自保留不同状态和清理语义。
- **Pipeline 节点用 registry 而非中央 switch**：引擎在构造时将 `getNodeType()` 映射到节点，新节点可以以 Bean 加入。
- **失败转成 NodeResult**：保留失败任务和节点日志，便于管理端看到究竟停在哪一步。

## 6.10 面试官可能怎样追问

### 问题 1：为什么开始分块用事务消息，而不是普通异步线程？

参考回答：它需要协调“文档状态已改为 RUNNING”与“摄取消息可投递”。事务消息用本地事务结果决定 COMMIT/ROLLBACK，不确定时通过查数据库中的 RUNNING 状态回查。

### 问题 2：RocketMQ 会自动重试 Parser 或 Embedding 失败吗？

参考回答：不能这样概括。`runChunkTask` 捕获内核异常，把文档和日志改为 FAILED，然后不再往 Consumer 抛。因此业务失败不会以消费异常的形式自动重试。

### 问题 3：摄取内核为什么不管文档状态？

参考回答：状态属于任务 owner。手动分块和定时刷新的状态/清理语义不同，但都需要相同的 MIME→Parser→Chunk→Embedding→Index 不变式。内核只管不变式，owner 管生命周期。

### 问题 4：IngestionEngine 是 DAG 引擎吗？

参考回答：不是任意 DAG。`NodeConfig` 只有一个 `nextNodeId`，Engine 要求恰好一个起点，条件不满足只是跳过当前节点后继续同一条链。

### 问题 5：知识文档现在默认走用户可配置 Pipeline 吗？

参考回答：不走。当前 `runChunkTask` 在 `ProcessMode.PIPELINE` 分支明确抛出“管道模式重构中”，可用主链是直接调用 `DefaultIngestionKernel`。

### 问题 6：固定 Kernel 和可配置 Engine 是不是重复造轮子？

参考回答：两者解决的问题不同。Kernel 集中核心入库不变式和次序；Engine 表达用户定义节点链、条件跳过和节点日志。他们复用底层 Parser/Chunk/Embedding 能力，但当前知识文档主链只启用 Kernel。

## 6.11 源码卡片

| 主题 | 路径 | 关键符号 |
|---|---|---|
| 启动与收尾 | `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/service/impl/KnowledgeDocumentServiceImpl.java` | `startChunk`、`runChunkTask` |
| 分块消息 | `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/mq/KnowledgeDocumentChunkConsumer.java` | `onMessage` |
| 事务回查 | `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/mq/KnowledgeDocumentChunkTransactionChecker.java` | `check` |
| MQ Producer | `framework/src/main/java/com/nageoffer/ai/ragent/framework/mq/producer/RocketMQProducerAdapter.java` | `sendInTransaction` |
| 事务 Listener | `framework/src/main/java/com/nageoffer/ai/ragent/framework/mq/producer/DelegatingTransactionListener.java` | `executeLocalTransaction`、`checkLocalTransaction` |
| 固定内核 | `rag/src/main/java/com/nageoffer/ai/ragent/core/ingest/DefaultIngestionKernel.java` | `run` |
| 内核契约 | `rag/src/main/java/com/nageoffer/ai/ragent/core/ingest/IngestionKernel.java` | `run` |
| 摄取配置 | `rag/src/main/java/com/nageoffer/ai/ragent/core/ingest/IngestionSpec.java` | `parseProfile`、`budget` |
| Engine | `rag/src/main/java/com/nageoffer/ai/ragent/ingestion/engine/IngestionEngine.java` | `execute`、`executeChain`、`executeNode` |
| Pipeline 模型 | `rag/src/main/java/com/nageoffer/ai/ragent/ingestion/domain/pipeline/NodeConfig.java` | `nextNodeId`、`condition` |
| 节点端口 | `rag/src/main/java/com/nageoffer/ai/ragent/ingestion/node/IngestionNode.java` | `getNodeType`、`execute` |
| 通用任务入口 | `rag/src/main/java/com/nageoffer/ai/ragent/ingestion/controller/IngestionTaskController.java` | `create`、`upload` |
| 任务持久化 | `rag/src/main/java/com/nageoffer/ai/ragent/ingestion/service/impl/IngestionTaskServiceImpl.java` | `executeInternal`、`saveNodeLogs` |
| 分块节点前置条件 | `rag/src/main/java/com/nageoffer/ai/ragent/ingestion/node/ChunkerNode.java` | `context.getVectorTarget()` |

所有锚点均以 AsterRAG 冻结提交 `98894c2c42c015a3c874c6b3c986ac863c85b731` 为准。

## 6.12 自我检查

1. RocketMQ 事务消息在这里协调的两个事实是什么？
2. Broker 回查为什么不能依赖 `localTransactionMap`？
3. `runChunkTask` 捕获内核异常后，RocketMQ 为什么不会自动重试这个业务失败？
4. Kernel 的四个输入和五个阶段分别是什么？
5. `IngestionEngine` 的条件跳过与图分支有什么区别？
6. 为什么当前不能把 `/ingestion/tasks` 写成知识文档默认入库主链？

## 6.13 下一章桥梁

现在我们已经知道“谁启动任务”、“谁保存状态”以及“内核的五步是什么”。第 7 章将把第三到第五步完全拆开：Block 如何按语义预算变成 Chunk，`content` 与 `embeddingText` 为什么分开，Embedding 维度如何被约束，以及关系库、pgvector、ES 和图谱的写入一致性到底有多强。
