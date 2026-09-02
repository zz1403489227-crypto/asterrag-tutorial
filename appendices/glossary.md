# 附录 B：术语表——先分清责任，再记名字

> 本表不追求收录所有类名，只收录阅读和面试时最容易混淆的概念。每个解释都以 AsterRAG `98894c2c42c015a3c874c6b3c986ac863c85b731` 为准。

## B.1 项目与证据

### AsterRAG

本教程讲解的目标 fork。它基于 Apache-2.0 的 `nageoffer/ragent` 学习和二次开发，保留了上游历史、LICENSE、NOTICE 和来源说明。不应把上游 RAG/Agent 核心能力说成从零原创。

### 冻结提交

教程认定的唯一实现基准，即完整 commit `98894c2c42c015a3c874c6b3c986ac863c85b731`。使用完整 SHA 是为了避免 `main` 继续变化后，教程的类、配置和时序与读者手中源码错位。

### `verified-source`

已由冻结源码、Schema 或配置确认的事实。它证明“代码如此实现”，不自动证明某环境已成功运行。

### `verified-test`

不仅有测试代码，还有针对冻结提交的真实执行记录。本教程只将已有的聚焦测试当作辅助理解，不以扩建测试为主任务。

### `verified-runtime`

某一次真实请求的 Trace、日志、持久结果和用户可见输出共同支持的运行事实。它不能由“类存在”、“HTTP 200”或“页面有截图”单独替代。

### `reference-only`

来自作者旧教程、公开页或外部教学项目的参考信息。它可以解释演进背景或教学组织，不能覆盖冻结源码的实现事实。

## B.2 架构与组装

### 模块化单体

`framework`、`infra-ai`、`system`、`rag`、`agent` 等 Maven 模块有编译依赖和责任边界，但最终由 `bootstrap` 组装到一个 Spring Boot 主进程。模块不等于微服务。

### 主应用

以 `RagentApplication` 为入口的 Spring Boot 进程，拥有 UI/API、知识库、确定性 RAG、Agent 和管理控制面。

### MCP Server

以 `McpServerApplication` 为入口的独立工具服务进程。它与主应用处于同一仓库，但不是同 JVM 的 Controller。

### 条件装配

Spring 根据配置键、类路径和 Bean 存在性决定实现是否进容器。“仓库有某个实现类”只证明支持，还要看 YAML 和运行分支才能判断是否默认使用。

### Java 字段兜底

`@ConfigurationProperties` 对象里的初始值。它只在外部配置没有覆盖时生效。例如编排类型的 Java 兜底是 workflow，但随仓库 YAML 显式选了 agent。

### 运行时分支

Bean 已经进入容器后，本轮请求仍可能通过 `enabled`、scope、threshold 或工厂选择跳过它。这是配置证据的第四层。

## B.3 知识写路径

### Knowledge Document

知识库中一份原始资料的业务元数据。它记录对象地址、MIME、来源、处理模式、状态和 Chunk 数，不等于对象存储中的原文件。

### Object Storage

保存上传文件或远程 URL 快照的 S3/OSS 兼容存储。它是原对象 owner，不是文档处理状态 owner。

### `PENDING / RUNNING / SUCCESS / FAILED`

知识文档的摄取生命周期。`SUCCESS` 表示当前固定摄取内核成功完成并回填终态，不等于任意问题都能召回它。

### 固定摄取内核

`DefaultIngestionKernel` 执行的固定五步：MIME 识别、结构化解析、分块、Embedding、索引替换。当前知识文档主链走这个内核。

### 通用 Ingestion Pipeline

`/ingestion/tasks` 子系统中由 `PipelineDefinition` 和 `nextNodeId` 定义的单根链。它可组装 Fetcher、Parser、Enhancer、Chunker、Enricher 和 Indexer，但不是当前知识文档的默认主链。

### `ProcessMode.PIPELINE`

知识文档上的处理选项。在冻结源码的 `runChunkTask` 中，这一模式被明确暂停并抛出错误；不能因为通用 Pipeline 子系统存在就宣称已接通。

### Parser Profile

除 MIME 外的解析路由选择。Parser 实际按“真实 MIME + profile”从 `ParserRegistry` 中选出，不只看文件扩展名。

### Block

Parser 输出的结构化中间对象。它让后续分块可以保留页码、标题或其他 provenance，而不是先把所有内容压成一个无位置字符串。

### Chunk

供检索和引用的基本证据单元。一个 Chunk 可同时有用于展示的 `content` 和用于嵌入的 `embeddingText`，两者不必完全相同。

### `ChunkIndexWriter`

将同一文档的 Chunk 整体扇出到多个 `ChunkSink` 的写入协调者。其 Spring 事务可包住关系库操作，但不能将外部向量库或其他索引自动变成全局原子事务。

### 派生索引

pgvector、Milvus、Elasticsearch 或 LightRAG 等用于检索的副本。从语义上它们可由文档/Chunk 重建，因此不应与原文件或业务元数据合并为一个 owner。

## B.4 确定性 RAG 读路径

### 确定性 RAG Pipeline

`StreamChatPipeline` 组织的固定顺序：保存 USER/加载记忆、改写、意图、检索、后处理、Prompt、模型流和收尾。“确定性”指编排骨架固定，不是说 LLM 输出确定。

### 会话记忆

从持久消息和摘要组装的当轮历史上下文。它是查询理解的输入，不是 AgentScope State 的同义词。

### 改写与拆分

将依赖历史的用户口语问题改成更适合检索的自包含问题，并可产生多个子问题。它改变检索输入，不改变用户原始消息这个持久事实。

### 意图与知识库范围

决定请求是否需要引导、是否只回系统答案，以及检索哪些知识库。它不等于检索算法本身。

### 多通道检索

向量、关键词、图谱和联网通道可按配置并行。单通道超时/异常会降级为空结果，不阻断其他通道。随仓库 YAML 默认只启用 vector。

### Scope

检索范围，如用户、知识库或文档约束。某个索引中有向量不代表本轮 scope 允许召回它。

### RRF

Reciprocal Rank Fusion，用多个结果列表中的排名而不是直接比较异构原始分数进行融合。它是检索后处理的一环。

### Rerank

对已经召回的候选证据进行二次相关性排序。它不创造新证据，也不能挽回第一阶段完全没召回的文档。

### 证据门

在候选排序后按阈值过滤低证据结果。如果最终为空，确定性 RAG 走空检索短路，而不是把裸 LLM 猜测包装成有来源答案。

### Grounding Context

最终送入 Prompt 的编号证据上下文。它与原始召回集不必相同，因为中间经过去重、融合、Rerank、证据门和富化。

### Source / Citation

回答引用的证据投影，用于前端来源面板和后续回放。它不等于模型输出必然逐字被证据支持，只是可检查 grounding 链的基础。

### Trace Run / Node

确定性 RAG 的诊断时序记录。Run 表示一次问答，Node 表示改写、检索或模型等阶段。Trace 不是会话消息 owner，也不是审计日志的别名。

### `FINISH` 与 `DONE`

SSE 协议中两个不同层次的收尾信号。完整事件序列和前端 hook 才能说明 UI 怎样结束当轮；不能只看 HTTP 连接成功。

## B.5 Agent 运行时

### ReAct

“推理/选择行动→执行工具→观察结果→继续”的动态循环。具体循环由 AgentScope 运行时实现，AsterRAG 负责人设、工具、State/Memory 适配和业务收尾。

### `AgentRunGate`

位于会话创建、USER 消息和 SSE 副作用之前的每用户运行位。释放时比较当前值，避免旧任务误删新任务的 owner 记录。

### `ReActAgentProvider`

根据用户人设和工具目录指纹懒构建/重建 Agent 实例，并组装 State Store 和记忆中间件。其进程内 cache 不是持久真相。

### Tool Catalog

`AgentToolCatalog` 解析当前 Agent 可见工具：固定知识检索、可选记忆工具，以及意图树与 MCP 注册表交集产生的动态工具。

### `search_knowledge`

Agent 的知识检索工具。它通过 `KnowledgeSearchFacade` 复用改写、KB 意图、`RetrievalEngine` 和答案合成，但不进入完整 RAG Controller/Pipeline/SSE finalizer。

### MCP Tool

由外部 MCP Server 描述并执行的工具。主应用在启动/刷新时构建注册表，连接失败时可跳过相应工具，不应伪装成工具调用成功。

### Agent 业务消息

用于页面回放的 USER/ASSISTANT 会话事实。它与 AgentScope State、上下文压缩记录、长期记忆是四套不同数据。

### AgentScope State

框架循环的可恢复状态，由 `PgAgentStateStore` 按 user/session/key 将不透明 JSON 存入 PostgreSQL。应用层不应随意解读并重写其内部结构。

### Context Compaction

对过长当前上下文进行压缩的中间件与持久记录。它解决 token/窗口压力，不等于从历史中提取长期记忆。

### Long-term Memory

通过控制、抽取和存储表管理的长期信息。它可跨轮次/会话参与 Agent 上下文，不是每次 SSE 连接的临时 buffer。

### `AgentRunHandle`

将 complete、cancel、fail 三个终局收敛为互斥 settle，然后在 `finally` 中注销任务并执行释放钩子。它保护的是“收尾只发生一次”和“资源一定尝试释放”。

## B.6 状态、一致性与前端

### 持久业务事实

进程重启后仍应保留，并由业务 Service/Mapper 负责的数据，如文档、消息、Trace、Agent State。

### 协调态

用于限流、锁、队列、owner、cancel 或 pub/sub 的 Redis/进程状态。它保护当前执行，但不替代业务事实。

### 补偿

当跨对象存储、数据库、MQ 和索引的全局事务不存在时，在后续失败中显式撤销先前副作用。补偿是有失败窗口的业务逻辑，不是 ACID 原子性。

### 事务消息

知识文档开始分块时，用 RocketMQ 本地事务回调协调文档状态与消息提交。它不等于 Consumer 已完成，也不自动保证所有下游外部存储 exactly-once。

### Owner 令牌

分布式 gate/锁中表示“谁有权释放或回写”的值。释放前比较 owner，可防止过期任务删掉新任务的状态。

### 幂等

同一请求或业务操作重复到达时，避免重复创建不可控副作用。幂等不是“所有步骤都不会重试”，也不是全链 exactly-once。

### 客户端投影

前端 hook/store 对 SSE 和持久消息的当前视图。临时 ID、当前连接 hint、raw frame 和 live duration 可随刷新消失，不能冒充服务端可恢复事实。

### UI `status` 与 `messageStatus`

前者主要表示当前客户端流式互动状态，后者是服务端持久消息的 NORMAL/INTERRUPTED/REJECTED 等投影。它们名字相近，owner 与寿命不同。

### 推断性设计解释

从实现结构得出的“为什么可能这样设计”。教程必须用“可以这样理解”或“从实现推断”标记，不把它写成作者明示意图。

## B.7 五组最容易混淆的快速对照

| 看起来相似 | 不能等同的原因 |
|---|---|
| 上传成功 vs 可检索 | 前者只到原文件/PENDING 元数据；后者还需摄取、索引与本轮 scope/threshold |
| 固定摄取 vs 通用 Pipeline | 一个是知识文档真实主链，一个是独立可配置子系统 |
| RAG Pipeline vs ReAct Agent | 一个固定编排，一个由运行时动态选择工具 |
| 业务消息 vs Agent State | 一个用于用户回放，一个用于框架循环恢复 |
| 代码存在 vs 默认运行 | 还需配置、条件 Bean 和本轮分支共同证明 |

