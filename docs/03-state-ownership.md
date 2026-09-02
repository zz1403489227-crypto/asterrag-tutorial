# 第 3 章：先认清数据——领域对象、状态所有权与生命周期

> 调用链只告诉你“代码经过哪里”。状态所有权才能回答：请求中断或进程重启后，什么还在，谁有权改它，系统又怎样恢复到可理解的状态？

## 3.1 一个常见错误：把名字相似的状态当成同一份数据

以 Agent 的“对话历史”为例，至少有四种不同数据：

| 对象 | 主要用途 | 持久落点 | 主要读者 |
|---|---|---|---|
| Agent 业务消息 | 用户页面回放 USER/ASSISTANT 内容 | `t_agent_message` | Conversation Service / 前端 |
| AgentScope State | ReAct 框架循环恢复 | `t_agent_state` 不透明 JSON | AgentScope / StateStore |
| Context Compaction | 记录长上下文的压缩边界和摘要 | `t_agent_context_compaction` | Compaction Middleware |
| Long-term Memory | 抽取、控制、存储和再注入长期信息 | memory/control/extraction 三组表 | Memory Pipeline/Middleware |

它们都与“过去发生过什么”有关，但 owner、存储结构、恢复用途完全不同。

同样的混淆还会出现在：

- 原文件 vs 文档元数据；
- 关系 Chunk vs 向量行；
- RAG 业务消息 vs Trace Node；
- Redis 中的运行 owner vs PostgreSQL 中的会话事实；
- 前端当前 `status` vs 服务端 `messageStatus`。

本章的方法就是：对每个对象都问“谁拥有、什么时候写、重启后是否仍在、能否从别处重建”。

## 3.2 四类状态，一个判定方法

![AsterRAG 状态所有权](../assets/diagrams/state-ownership.png)

### 3.2.1 持久业务事实

这类数据在进程重启后仍应存在，并由明确的业务 Service/Mapper 修改：

- 用户；
- RAG/Agent 会话与消息；
- 知识库、文档、Chunk 元数据；
- 调度计划与执行记录；
- 意图树；
- RAG Trace；
- Agent State/压缩/长期记忆；
- Ingestion Pipeline/Task/Node Log。

它们不应在没有业务规则的情况下由缓存反向覆盖。

### 3.2.2 持久原对象

对象存储中的原文件、URL 快照或资产。它们也能跨进程存在，但不是 PostgreSQL 表行：

```text
Object Storage 拥有字节
PostgreSQL Document 拥有指向字节的 fileUrl、MIME、来源和状态
```

关系数据库事务不能自动回滚对象存储写入。因此一旦跨越这条边界，就要查补偿和遗留窗口。

### 3.2.3 派生索引

向量、Elasticsearch、LightRAG 或 Milvus 中的数据用于加速查找/表示相关性。它们可以持久，却仍是派生状态：理论上可以从原文档/Chunk 重建，并且可能与业务元数据暂时漂移。

`t_knowledge_vector` 物理上在 PostgreSQL 中，但 owner 分类不应只看数据库产品：它仍是一个可由 Chunk + Embedding 重建的检索副本。

### 3.2.4 协调态与进程态

协调态决定“此刻谁可以做什么”：

- Redis 许可/信号量；
- 分布式锁与 owner token；
- Agent 运行位；
- task cancel/pub-sub；
- Snowflake 节点 ID；
- 幂等记录与 TTL。

进程态则随 JVM/浏览器生命周期消失：

- ReActAgentProvider 的 Agent cache；
- `StreamTaskManager` 本地任务投影；
- SSE 本轮累计 buffer；
- ThreadLocal/Trace Context；
- 前端当前 hint、raw frame、live duration 和临时消息 ID。

不要用这些数据替代长期业务事实。可恢复系统的正确思路是“从持久事实重建投影”，而不是指望旧内存对象继续存在。

## 3.3 31 张表是 owner 地图，不是需要背的字段清单

`resources/database/schema_pg.sql` 有 31 个 `CREATE TABLE`。正确阅读方法是按领域分组。

### 3.3.1 用户、示例和审计（7 张中的 3 类）

| 表 | 核心事实 |
|---|---|
| `t_user` | 用户身份与系统属性 |
| `t_sample_question` | 前端展示/推荐的样例问题 |
| `t_biz_change_log` | 管理对象 before/after 与操作人审计 |

`t_biz_change_log` 不是 RAG Trace。前者记录管理操作，后者记录问答运行节点。

### 3.3.2 确定性 RAG 会话（5 张）

| 表 | 作用 |
|---|---|
| `t_conversation` | 会话身份、归属和展示状态 |
| `t_conversation_summary` | 历史压缩/摘要投影 |
| `t_message` | USER/ASSISTANT 持久消息、来源和终态 |
| `t_message_feedback` | 用户对回答的反馈 |
| `t_sample_question` | 也被控制面/欢迎面使用，不是当轮会话事实 |

`t_message.message_status` 的 Schema 评论明确三种主要终态：

```text
NORMAL      正常完成
INTERRUPTED 用户中断（当前有非空累计正文时才保存）
REJECTED    限流/排队拒绝
```

流式错误当前不通过一条“ERROR assistant”业务消息表达。错误会通过 emitter 和 Trace 终态反映，这是一个必须如实讲的当前边界。

### 3.3.3 知识库与文档（6 张）

| 表 | 主要 owner |
|---|---|
| `t_knowledge_base` | 知识集合、用户归属、状态/配置 |
| `t_knowledge_document` | 原文件指针、来源、MIME、处理模式和摄取终态 |
| `t_knowledge_chunk` | 关系 Chunk、展示内容与 provenance |
| `t_knowledge_document_chunk_log` | 分块/摄取次数的时序、统计和错误 |
| `t_knowledge_document_schedule` | URL 来源的刷新计划和 owner 状态 |
| `t_knowledge_document_schedule_exec` | 某次刷新执行的结果/错误/跳过 |

一个 document 行不包含原文件字节，一个 chunk 行也不是向量行。这是后续理解跨存储一致性的前提。

### 3.3.4 意图与查询映射（2 张）

| 表 | 作用 |
|---|---|
| `t_intent_node` | 意图树、知识库/工具路由及引导配置 |
| `t_query_term_mapping` | 查询词与规范术语/扩展的映射 |

意图树既参与确定性 RAG 的范围，也参与 Agent MCP 工具的可见交集。但它不持有工具实际连接状态，后者在 MCP registry/runtime。

### 3.3.5 RAG Trace（2 张）

| 表 | 作用 |
|---|---|
| `t_rag_trace_run` | 一次问答的总体身份、开始/终止和统计 |
| `t_rag_trace_node` | 改写、意图、检索、模型等阶段级记录 |

Trace 可以回答“为什么这一轮没召回”或“时间花在哪个节点”，但不是会话消息的备份。

### 3.3.6 Agent（9 张）

| 表 | 主要责任 |
|---|---|
| `t_agent_profile` | Agent 人设配置 |
| `t_agent_prompt` | 系统/Agent Prompt 配置 |
| `t_agent_conversation` | Agent 业务会话 |
| `t_agent_message` | 用户可回放消息与 blocks |
| `t_agent_state` | AgentScope 不透明 State JSON |
| `t_agent_context_compaction` | 上下文压缩记录 |
| `t_agent_memory` | 已接受的长期记忆 |
| `t_agent_memory_extraction` | 某次记忆抽取过程/终态 |
| `t_agent_memory_control` | 长期记忆过滤/控制与审核性数据 |

`t_agent_message.message_status` 的 Schema 评论只列 NORMAL 和 INTERRUPTED。Agent 失败路径当前也不保存 assistant 错误行。不要把 RAG 的 REJECTED 消息契约原样套到 Agent 表。

### 3.3.7 通用 Ingestion（4 张）

| 表 | 作用 |
|---|---|
| `t_ingestion_pipeline` | Pipeline 身份/说明/状态 |
| `t_ingestion_pipeline_node` | 节点类型、配置和 `nextNodeId` |
| `t_ingestion_task` | 一次通用 Pipeline 执行总状态 |
| `t_ingestion_task_node` | 每个节点输入/输出/耗时/错误记录 |

这四张表不是知识文档固定摄取的同义表。后者主要通过 document + chunk log 表达状态。

### 3.3.8 pgvector（1 张）

| 表 | 作用 |
|---|---|
| `t_knowledge_vector` | Chunk 的 embedding 向量、检索必需范围字段和内容投影 |

它与 `t_knowledge_chunk` 通过 Chunk 身份/范围对齐，但两者的写入目的和可重建性不同。

## 3.4 文档生命周期：一个状态不代表所有落点

### 3.4.1 主状态机

```text
上传/远程抓取
   → Object + Document(PENDING, chunkCount=0)

显式 startChunk
   → 事务消息本地回调尝试 Document(RUNNING)
   → ChunkLog(RUNNING)

固定摄取成功
   → 关系 Chunk + 向量/可选派生落点
   → Document(SUCCESS, chunkCount, mime, timings)
   → ChunkLog(SUCCESS)

固定摄取失败
   → Document(FAILED, error)
   → ChunkLog(FAILED, error)
```

上面是业务主线，不是全局原子事务。要把每个失败窗口分开。

### 3.4.2 对象已存，文档未插入

`upload` 在对象写入后、数据库 insert 前会用 ParserRegistry 校验 MIME。如果没有 Parser，源码显式删除刚写的对象。

但如果后续 DB insert 本身失败，当前方法没有对称的“删对象”分支。因此可以说“不支持 MIME 有显式补偿”，不能说“对象存储 + DB 全过程原子”。

### 3.4.3 消息已提交，Consumer 未完成

事务消息协调“本地 RUNNING 状态和消息提交”，但消息提交不等于 Consumer 已经完成五步内核。当文档停在 RUNNING 时，应继续查 Consumer、Chunk Log 和终态回填，而不是仅查 Producer 发送成功。

### 3.4.4 一个 sink 已写，另一个 sink 失败

`ChunkIndexWriter` 在 `TransactionOperations` 中遍历多个 `ChunkSink`。对同一数据库连接的关系写入，Spring 事务可以提供回滚语义；对外部 Milvus/ES/LightRAG 副作用，不能由这个事务自动变成全局 ACID。

所以文档 FAILED 后是否遗留了某个派生索引，必须根据具体 sink 顺序、异常处理和补偿查，不能只看方法有 `transactionOperations.execute`。

### 3.4.5 文档 SUCCESS 与可召回

`SUCCESS` 精确表达：当前固定摄取调用成功返回，Service 回填了终态/计数/时间。

它不能表达：

- 所有可选索引都已写入；
- 知识库/文档当前仍 enabled；
- 本轮意图选中了该知识库；
- 查询与 Chunk 的相关性足够；
- Rerank/证据门一定保留该候选。

## 3.5 远程刷新：原文件“当前版本”怎样切换

URL 文档的 `ScheduleRefreshProcessor` 将进度分为：

```text
INIT
  → DOC_OCCUPIED
  → CHUNK_STARTED
  → CHUNK_COMPLETED
  → FILE_SWITCHED
```

设计的关键不是 Cron，而是新旧对象的 owner 切换：

1. 新远程内容先存为一个新对象；
2. 用内存 `runtimeDoc` 指向新文件进行摄取；
3. 只有摄取成功，才把 DB Document 的“当前 fileUrl”切到新对象；
4. 切换成功后才删旧对象。

如果新对象已经产生 Chunk/索引，却在切 fileUrl 前失败，清理逻辑不会盲目删新对象，而是保留并告警。这体现了“清理责任必须取决于任务已经跨过哪个副作用边界”。

## 3.6 确定性 RAG 会话生命周期

### 3.6.1 正常路径

```text
进入 Pipeline
  → 读取 conversation/summary/messages
  → 保存 USER message
  → 改写/意图/检索/生成
  → 保存 NORMAL assistant + sources/grounding projection
  → Trace Run/Node 收尾
  → FINISH/DONE
```

注意 USER 消息在 Pipeline 早期已持久。如果后续模型流失败，可能出现“USER 已在，没有 assistant 错误行”的会话历史。这不是数据莫名丢失，而是当前 finalizer 契约的结果。

### 3.6.2 排队拒绝

拒绝发生在 Pipeline 之前。`ChatQueueLimiter` 自己尝试：

- 保存 USER；
- 保存 `REJECTED` assistant；
- 发 `META / REJECT / FINISH / DONE`；
- 完成本路径的资源处理。

所以 REJECTED 是可回放的业务终态，不只是浏览器看到一个瞬时 toast。

### 3.6.3 取消

当前 RAG finalizer 只在已累计非空正文时保存 `INTERRUPTED` assistant。如果连第一个正文 token 都没有，会有取消事件/收尾，但不一定有一条空 assistant 消息。

### 3.6.4 错误

流式错误会终止 emitter、记录 Trace ERROR 并执行释放。当前实现不将异常文本作为 assistant 业务消息保存。

这就解释了为什么不能用“会话表里有无错误消息”单独判断流是否失败；需要结合客户端事件和 Trace。

## 3.7 Trace、业务消息和审计的三方分工

| 数据 | 主要问题 | 寿命/owner |
|---|---|---|
| RAG Message | 用户和助手在会话里说了什么 | Conversation/Message Service |
| RAG Trace | 这次运行经过哪些节点、耗时/终态如何 | Trace Runner/Recorder |
| BizChangeLog | 谁改了哪个管理对象，before/after 是什么 | Audit AOP/Service |

它们可以用关联 ID 共同定位问题，但不应被合并成一张“什么都记”的表。合并会让数据访问目的、保留周期和权限边界变得含混。

## 3.8 Agent 的五层状态

### 3.8.1 第一层：业务会话和消息

`t_agent_conversation` / `t_agent_message` 用来重建用户页面上的会话。持久 AgentBlock 可包含文本、思考、工具调用/结果等投影。

### 3.8.2 第二层：AgentScope State

`PgAgentStateStore` 按 user/session/key 将 State 序列化为不透明 JSON。这一层是 AgentScope 恢复契约，应用业务层不应把内部 JSON 当作自己稳定的领域 Schema。

### 3.8.3 第三层：Context Compaction

当当前上下文过长时，压缩中间件产生更精简的上下文投影，并持久压缩记录。它主要解决模型窗口/token 压力，不是用户可编辑的长期事实。

### 3.8.4 第四层：Long-term Memory

记忆提取/控制管线将候选长期信息与已接受记忆分开。这让“模型觉得值得记住”不必立即变成不可逆的长期真相。

### 3.8.5 第五层：运行 owner 和进程投影

`AgentRunGate`、`StreamTaskManager`、Agent cache、SSE buffer 共同保护当前运行。它们可以被 TTL、取消、释放或进程重启清除，不是会话历史。

## 3.9 Agent 三种终局的持久边界

| 终局 | assistant 业务消息 | SSE/客户端 | 资源 |
|---|---|---|---|
| 正常 | 保存 NORMAL 内容/blocks | 完成事件 | RunHandle 注销 + 所有释放钩子 |
| 取消 | 有非空累计内容时保存 INTERRUPTED | CANCEL + DONE | 同样走 RunHandle 释放 |
| 失败 | 当前不保存 assistant 失败行 | emitter error | 同样执行业务释放钩子 |

`AgentRunHandle.settle` 用原子状态使三个终局互斥。这不只是防止多发一个 DONE，还避免同一轮会话被同时保存成 NORMAL 和 INTERRUPTED，或重复释放 owner token。

## 3.10 前端状态不是服务端真相的另一份复制

前端在当前连接中需要及时响应 token、工具 block、停止按钮和错误。因此它必然有临时投影：

```text
服务端 SSE frame
      ↓
hook 手动解析
      ↓
store 中的当前 message/block/status
      ↓
页面渲染
```

刷新后，可恢复的是服务端已持久的 conversation/message/blocks。以下内容不应被当成可恢复事实：

- 当前 raw frames 环形/上限 buffer；
- live duration；
- 流中 hint；
- 临时消息 ID；
- 尚未被服务端持久的局部 block；
- 仅供欢迎页展示的硬编码 DEMO_TURN。

这也是为什么“页面看到了工具演示”不等于“后端真的执行了该工具”。

## 3.11 一致性不是一个开关，而是一张失败矩阵

遇到“这里是否一致”，不要只回答“用了事务”。按下表问：

| 边界 | 同一本地事务？ | 可见机制 | 仍要问 |
|---|---|---|---|
| 对象存储 → Document DB | 否 | 部分显式删除补偿 | DB insert 失败有无对称补偿 |
| Document RUNNING ↔ MQ 提交 | 由事务消息协调本地部分 | 本地事务回调/回查 | Consumer 是否完成、重复语义 |
| 关系 Chunk ↔ pgvector | 默认可能同 DB 事务，仍看实现 | `TransactionOperations` + sinks | sink 顺序和异常是否继续 |
| 关系 Chunk ↔ Milvus/ES/LightRAG | 否 | 各 sink 的 fail-fast/best-effort | 遗留、重试、删除/重建 |
| 业务消息 ↔ SSE | 否 | finalizer 顺序 | 连接断开时持久到哪里 |
| Redis owner ↔ 本地 task | 否 | token 比较 + finally hooks | TTL/进程崩溃后的恢复 |

这个方法将“一致性”从抽象主张变成可检查的副作用次序。

## 3.12 删除、逻辑删除和派生清理

当 Schema 或 DO 存在逻辑删除标志时，“用户看不到”不等于“所有落点物理消失”。对知识文档删除应分别问：

1. document 元数据是逻辑删除还是物理删除？
2. 原对象是否删除？
3. 关系 Chunk 是否删除/替换？
4. pgvector 是否删除？
5. 可选 ES/LightRAG/Milvus 是同步清理、best-effort 还是需要后续重建？
6. Trace、审计、分块日志是否出于诊断/合规保留？

只有跟完真实 Service/Sink 删除链才能回答，不能从一个 `deleted=1` 推导所有副本已清空。

## 3.13 恢复性：什么可以重建，什么不应猜

| 状态 | 进程重启后 | 恢复思路 |
|---|---|---|
| Document/Message/Trace/Agent State | 仍在 PostgreSQL | 通过 Service 重读，不从前端反写 |
| 原文件 | 仍在对象存储（未被清理时） | 用 document `fileUrl` 定位 |
| pgvector/外部索引 | 数据可能仍在，也可能漂移 | 用文档/Chunk 重建，不以单行存在证明全链成功 |
| Redis gate/lock | TTL/稳定外部存储决定 | 使用 owner token、TTL 和持久事实判断，不盲目删 |
| Agent cache / SSE buffer | 丢失 | 从 Agent Profile/Tools/State/Message 懒重建可恢复部分 |
| 前端 raw frames/hints | 刷新即丢 | 不恢复；只重建持久消息/blocks |

“可以重建”不等于当前已实现全自动灾难恢复。它只是 owner 语义：哪些数据是源，哪些是派生物。

## 3.14 面试中如何用状态 owner 回答故障题

面试官问“系统中途崩了怎么办”，不要第一句回“加重试”。用下面模板：

```text
1. 先定位崩溃前最后一个已完成副作用。
2. 列出已写的持久事实、原对象和派生索引。
3. 找当前 owner token / status，确认是否仍有任务有权回写。
4. 看当前代码是回滚、显式补偿、重试、best-effort 还是遗留告警。
5. 只对幂等或有重复保护的步骤提出重试。
```

例如文档摄取失败，一个好的回答是：

> “我会先看 document/Chunk Log 的终态与失败节点，再按 `ChunkIndexWriter` 的 sink 顺序检查关系 Chunk、pgvector 和可选外部索引。Spring 事务不能覆盖外部索引，所以不能只根据 FAILED 假设所有副作用已回滚。只有在确认替换语义/幂等后才重试。”

这样的回答体现了你知道系统怎样工作，而不只是会背“分布式最终一致”。

## 3.15 常见误解

### “对象存储和数据库都是持久化，可以当一个事务吗？”

不能。两者都持久，但不在同一本地数据库事务中。要逐个查显式补偿和失败窗口。

### “pgvector 在 PostgreSQL，所以它就是业务事实？”

物理位置基本相同，但语义不能完全等同。向量是可由 Chunk + Embedding 重建的检索派生物。

### “Redis 丢了是不是会话也没了？”

不应该。会话/消息事实在 PostgreSQL。Redis 主要是锁、许可、owner、cancel 等协调态。但 Redis 丢失会影响当前执行和恢复判断，不是无影响。

### “Trace 中有节点，是不是就是用户历史？”

不是。Trace 是运行诊断，Message 是会话事实。两者用途、保留和展示不同。

### “Agent 有 State，为什么还要消息表？”

AgentScope State 是框架恢复契约，业务消息是用户可回放事实。合并它们会让应用被框架内部 JSON 结构绑定。

### “前端看到了 tool block，就能证明工具执行了？”

不一定。要区分实时事件、持久 block 和硬编码示例。后端 block 还有 `toolCallId`，前端当前实时配对主要按同名工具 LIFO，不能把更丰富的后端字段误写成前端已完整利用。

## 3.16 本章源码卡片

| 问题 | 主要锚点 |
|---|---|
| 31 表和字段注释 | `resources/database/schema_pg.sql` |
| 文档状态 | `DocumentStatus`、`KnowledgeDocumentServiceImpl` |
| 刷新阶段/owner | `ScheduleRefreshProcessor`、`DocumentStatusHelper` |
| 关系/向量落点 | `RelationalChunkSink`、`VectorChunkSink`、`ChunkIndexWriter` |
| RAG 消息终态 | `StreamChatEventHandler`、`ChatQueueLimiter`、`t_message` Schema 评论 |
| RAG Trace | `StreamChatTraceRunner`、`t_rag_trace_*` |
| Agent 业务消息 | `AgentStreamEventBridge`、`t_agent_message` |
| AgentScope State | `PgAgentStateStore`、`t_agent_state` |
| Agent 三路收尾 | `AgentRunHandle` |
| 前端临时/持久投影 | `useStreamResponse`、`useAgentStream`、两个 store |

## 3.17 本章自测

1. 将 PostgreSQL 业务表、对象存储、pgvector、Redis 和 Agent cache 分到四类 owner 中。
2. 为什么文档 SUCCESS 不能证明某次查询一定召回？
3. 对象已存、DB insert 失败时，当前代码能不能宣称全局原子？
4. RAG 正常、拒绝、取消和错误分别如何持久 assistant？
5. Agent 业务消息、AgentScope State、Context Compaction、Long-term Memory 各自解决什么？
6. 为什么释放 Redis owner 前要比较 token？
7. 前端 raw frame 和持久 block 的寿命有什么不同？
8. 如何用“最后一个已完成副作用”来回答一致性故障题？

## 3.18 小结：现在可以安全进入写路径了

前四章已经交付了一套稳定学习坐标：

```text
第 0 章：一句话凭什么可信
第 1 章：系统总体怎样流动
第 2 章：责任住在哪个模块/进程
第 3 章：每个副作用的 owner 和恢复边界
```

从第 4 章开始，我们拿着这张地图沿知识写路径逐段下钻。第一站不是分块算法，而是“原资料从哪里来，在第一个副作用前做了哪些校验，对象存储与文档元数据的失败窗口是什么”。

