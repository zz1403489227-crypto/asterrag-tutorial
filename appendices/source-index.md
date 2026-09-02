# 附录 C：源码导航索引

> 这不是按字母排列的类清单，而是“想回答什么问题，应该从哪里进入”的路线图。所有路径相对于冻结 AsterRAG 仓库根目录。

## C.1 五分钟定位法

| 你想回答的问题 | 第一个入口 | 继续跟踪 | 教程 |
|---|---|---|---|
| 七个模块怎样组装 | `pom.xml` | `bootstrap/pom.xml` → `RagentApplication` | 第 2 章 |
| 文档上传后发生什么 | `KnowledgeDocumentController` | `KnowledgeDocumentServiceImpl.upload` | 第 4 章 |
| 文档如何开始分块 | `KnowledgeDocumentServiceImpl.startChunk` | 事务 Listener → Consumer → `runChunkTask` | 第 6 章 |
| 固定摄取五步是什么 | `DefaultIngestionKernel.run` | Parser → Chunker → Embedding → Writer | 第 5～7 章 |
| 一次 RAG 请求怎样流动 | `RAGChatController.chat` | `RAGChatServiceImpl` → `StreamChatPipeline` | 第 8～13 章 |
| 多通道如何检索 | `MultiChannelRetrievalEngine` | channel → postprocessor | 第 11～12 章 |
| 流式回答怎样收尾 | `StreamChatEventHandler` | `StreamChatTraceRunner` | 第 13 章 |
| Agent 怎样进入 ReAct | `AgentChatController.chat` | `AgentChatServiceImpl.startRun` → provider | 第 14～16 章 |
| Agent 有哪些工具 | `AgentToolCatalog.resolve` | Knowledge / Memory / MCP adapters | 第 15 章 |
| Agent 三种终局怎样收敛 | `AgentRunHandle.settle` | `AgentStreamEventBridge` | 第 16 章 |
| 前端怎样消费 SSE | `frontend/src/hooks/useStreamResponse.ts` / `frontend/src/hooks/useAgentStream.ts` | 各自 store 和消息类型 | 第 18 章 |
| 默认到底启用什么 | `bootstrap/src/main/resources/application.yaml` | Properties → Conditional Bean → runtime branch | 第 19 章 |

## C.2 项目身份与构建

| 路径/符号 | 主要责任 | 不要误读为 |
|---|---|---|
| `README.md` | AsterRAG 学习/二次开发身份和功能入口 | 精确时序的最高权威 |
| `NOTICE` | 上游归属与保留声明 | 个人从零原创证明 |
| `docs/UPSTREAM.md` | fork 与上游关系 | 运行时组件说明 |
| `pom.xml` | 7 模块、Java/Spring Boot 版本和公共依赖 | 7 个网络服务 |
| `bootstrap/pom.xml` | 主应用最终组装 | 业务 owner |
| `frontend/package.json` | 前端构建和依赖 | 后端开关真相 |

## C.3 两个启动边界

### 主应用

- 入口：`bootstrap/src/main/java/com/nageoffer/ai/ragent/RagentApplication.java`
- 主配置：`bootstrap/src/main/resources/application.yaml`
- 数据库建表：`resources/database/schema_pg.sql`
- 实际责任：组装 `framework + infra-ai + system + rag + agent`。

### 独立 MCP Server

- 入口：`mcp-server/src/main/java/com/nageoffer/ai/ragent/mcp/McpServerApplication.java`
- 配置：`mcp-server/src/main/resources/application.yml`
- 实际责任：提供示例 MCP tools，由主应用作为 client 连接。

## C.4 知识文档主链

### HTTP 与并发保护

- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/controller/KnowledgeDocumentController.java`
  - 上传、开始分块、预览和文件读取入口。
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/filter/UploadRateLimitFilter.java`
  - multipart 之前的 Redisson 许可控制。

### 上传与远程来源

- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/service/impl/KnowledgeDocumentServiceImpl.java`
  - `upload`：配置校验、对象保存、MIME 可解析校验、PENDING 元数据。
  - `startChunk`：事务消息与 RUNNING 切换。
  - `runChunkTask`：固定内核调用和 SUCCESS/FAILED 回填。
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/handler/RemoteFileFetcher.java`
  - HEAD/GET、大小上限、ETag/Last-Modified/SHA-256 变更判断。
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/schedule/ScheduleRefreshProcessor.java`
  - 锁 owner、新文件先摄取后切换、分阶段清理。

### 解析、分块与索引

- `rag/src/main/java/com/nageoffer/ai/ragent/core/ingest/DefaultIngestionKernel.java`
  - 固定五步主循环。
- `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/registry/ParserRegistry.java`
  - MIME/Profile 路由与 Parser 可用性。
- `rag/src/main/java/com/nageoffer/ai/ragent/core/chunk/`
  - 结构化分块、Chunk 组装和位置信息。
- `rag/src/main/java/com/nageoffer/ai/ragent/core/ingest/sink/ChunkIndexWriter.java`
  - 文档级 replace 和多 sink 扇出。
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/sink/RelationalChunkSink.java`
  - 关系 Chunk 落点。
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/sink/VectorChunkSink.java`
  - 向量落点。

### 通用 Ingestion 子系统

- `rag/src/main/java/com/nageoffer/ai/ragent/ingestion/service/impl/IngestionTaskServiceImpl.java`
  - Pipeline/Task 校验、同步执行和任务终态。
- `rag/src/main/java/com/nageoffer/ai/ragent/ingestion/engine/IngestionEngine.java`
  - 单根链校验、环/断链/多起点检测、按 `nextNodeId` 执行。
- `rag/src/main/java/com/nageoffer/ai/ragent/ingestion/node/`
  - Fetcher / Parser / Enhancer / Chunker / Enricher / Indexer 实现。

## C.5 确定性 RAG 主链

### 接入、闸门与任务

- `rag/src/main/java/com/nageoffer/ai/ragent/rag/controller/RAGChatController.java`
  - `/rag/v3/chat` 与 `/rag/v3/stop` HTTP 入口。
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/impl/RAGChatServiceImpl.java`
  - 申请许可、组装 SSE/Trace/Pipeline、转交事件 Handler。
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/ratelimit/ChatQueueLimiter.java`
  - 获取、排队、拒绝和释放；拒绝路径有自己的 SSE/消息收尾。
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/web/`
  - SSE 封装与任务基础契约。

### 主编排与短路

- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/pipeline/StreamChatPipeline.java`
  - 固定编排总入口。
  - `loadMemory`：加载历史并保存 USER。
  - `rewriteQuery`：改写/拆分。
  - `resolveIntents`：意图与范围。
  - `handleGuidance`、`handleSystemOnly`、`handleEmptyRetrieval`：三类主要短路。

### 检索

- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/MultiChannelRetrievalEngine.java`
  - 子问题/通道并行、通道超时和失败降级。
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/channel/`
  - 向量、关键词、图谱、联网通道的共同接口与实现。
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/postprocessor/`
  - 去重 `1` → 融合 `5` → Rerank `10` → 证据门 `15` → 元数据富化 `20`。

### 生成、Trace 与收尾

- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/handler/StreamChatEventHandler.java`
  - token/来源事件、正常/取消/错误收尾、assistant 持久边界。
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/trace/StreamChatTraceRunner.java`
  - Run/Node 上下文、用户首包与最终 Run 终态。
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/prompt/`
  - grounding 证据组装、编号和 Prompt 边界。

## C.6 ReAct Agent 主链

### 入口与运行位

- `agent/src/main/java/com/nageoffer/ai/ragent/agent/controller/AgentChatController.java`
  - Agent chat/stop 入口，只在 Agent 执行架构装配。
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/service/impl/AgentChatServiceImpl.java`
  - gate 后创建/读取会话、保存 USER、获得 Agent、启动流和组装收尾。
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentRunGate.java`
  - 每用户 owner token 和对比释放。

### Agent 构建与工具

- `agent/src/main/java/com/nageoffer/ai/ragent/agent/config/ReActAgentProvider.java`
  - 人设/工具指纹、AgentScope ReAct 实例、State Store 与两层记忆中间件。
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/tool/AgentToolCatalog.java`
  - 固定工具、可选记忆工具、意图与 MCP 交集。
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/tool/KnowledgeSearchTool.java`
  - `search_knowledge` 工具适配器。
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/KnowledgeSearchFacade.java`
  - Agent 复用知识检索的窄门面，不含完整 RAG SSE 流水线。

### State、Memory 与收尾

- `agent/src/main/java/com/nageoffer/ai/ragent/agent/state/PgAgentStateStore.java`
  - 按 user/session/key 保存不透明 AgentScope JSON State。
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/memory/`
  - 上下文压缩、长期记忆提取/控制/注入。
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentStreamEventBridge.java`
  - AgentScope event 到业务 block/SSE 的映射，及正常/取消/失败收尾数据。
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentRunHandle.java`
  - complete/cancel/fail 互斥 settle，任务注销与释放钩子。

## C.7 配置、基础设施与横切保护

| 主题 | 入口 | 读法 |
|---|---|---|
| 执行架构 | `OrchestrationProperties` + `application.yaml` | 区分 Java workflow 兜底与 YAML agent 选择 |
| 向量后端 | vector config/classes + YAML | 默认 pg；Milvus 可选；再核对 Bean 条件 |
| 检索通道 | `SearchChannelProperties` + YAML | 默认只启 vector；实现存在不等于启用 |
| 对象存储 | storage config + `FileStorageService` | 启动 fail-fast 与业务补偿分开 |
| Redis | Redisson/config/initializer/gates | 不只是 cache，还有 ID、许可、锁、owner 和 pub/sub |
| MQ | `framework` MQ abstractions + knowledge producer/consumer | 只对真实使用点下结论，不泛化为所有业务 |
| 幂等 | `framework` idempotent AOP/filter | 识别 key、owner、TTL 与失败释放 |
| 审计 | system biz change log | 与 RAG Trace 分开 |
| 认证 | framework security/user context | 前端 route guard 不是后端角色授权 |

## C.8 前端导航

| 路径 | 作用 | 刷新后的边界 |
|---|---|---|
| `frontend/src/components/common/EngineGate.tsx` | 获取引擎元信息并选 RAG/Agent 端 | meta 是配置投影，不是运行任务证据 |
| `frontend/src/hooks/useStreamResponse.ts` | 消费确定性 RAG SSE | 当前 token/hint 是临时投影 |
| `frontend/src/stores/chatStore.ts` | RAG 会话与当轮 UI 状态 | 持久消息必须从服务端重载 |
| `frontend/src/hooks/useAgentStream.ts` | 消费 Agent SSE，组装 text/thinking/tool blocks | raw frames 只保留当前内存窗口 |
| `frontend/src/stores/agentChatStore.ts` | Agent 会话和临时 blocks | 实时工具配对并未利用后端 `toolCallId` |
| `frontend/src/pages/admin/` | 知识库、意图、Agent、Trace、设置管理页 | 客户端 `/admin` 守卫不替代后端角色校验 |

## C.9 用状态反向找源码

| 你看到的状态 | 先查 | 再查 |
|---|---|---|
| 文档长时间 `PENDING` | upload 是否只创建元数据 | 是否调用 `startChunk` |
| 文档 `RUNNING` | 事务消息本地状态 | Consumer/Chunk Log/终态回填 |
| 文档 `SUCCESS` 但查不到 | Chunk/向量落点 | document enabled、scope、通道 enabled、threshold |
| RAG 立即拒绝 | `ChatQueueLimiter` | REJECTED assistant 与 META/REJECT/FINISH/DONE |
| RAG 没有调用 LLM | guidance/system-only/empty-retrieval | 意图、scope 和证据门 |
| RAG 流中断 | `StreamChatEventHandler` | assistant 是否有累计正文、Trace 终态、许可释放 |
| Agent 第二轮被拒 | `AgentRunGate` | owner token 是否属于旧运行 |
| Agent 没某个 MCP 工具 | MCP registry 初始化日志 | 意图树和注册表是否同时包含 |
| Agent 页面刷新后丢 raw frame | `useAgentStream` 内存 buffer | 服务端业务消息/blocks 是否已持久 |

## C.10 源码阅读的停止条件

跟一条链时，满足以下六项就可以暂停，不必把所有 DTO/Mapper 都背下来：

1. 知道入口和最终 owner；
2. 能按顺序说出 5～8 个关键节点；
3. 能说出哪一步首次产生外部副作用；
4. 能区分持久事实、派生索引、协调态和进程态；
5. 能说出正常、短路/拒绝、取消和错误怎样收尾；
6. 能区分源码事实、配置选择、运行证据和设计推断。

做到这六点，你就不再是“记住类名”，而是已经建立了可用于面试追问的系统模型。
