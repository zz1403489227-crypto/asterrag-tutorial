# 第一章总体架构节点责任表

> 冻结提交：`98894c2c42c015a3c874c6b3c986ac863c85b731`  
> 用途：约束第 1 章总体图。每个箭头后续必须能回到本表和 `source-map.csv`；本表是静态源码事实，不是运行证明。

## 1. 接入与控制面

| 节点 | Owner | 输入 | 输出 | 状态/持久化 | 正常路径 | 主要失败边界 | 源码锚点 |
|---|---|---|---|---|---|---|---|
| React 控制台 | `frontend` | 用户操作、后端 JSON/SSE | 管理请求、RAG/Agent 问题、页面投影 | Zustand/组件临时态；服务端状态需重新请求 | 路由→API/hook→store→组件 | 两套 SSE 不能混用；断线后本地投影不等于服务端终态 | `frontend/src/hooks/useStreamResponse.ts`；`frontend/src/hooks/useAgentStream.ts`；`frontend/src/stores/*ChatStore.ts` |
| Spring MVC API | 各 Controller | HTTP、认证身份、参数 | JSON `Result` 或 `SseEmitter` | 本身不作为事实存储 | 校验→Service | HTTP 200/SSE 建连不等于异步任务完成 | `*Controller.java` 共 24 个 |
| 认证/用户上下文 | `framework` + `system` | Sa-Token 登录态 | `UserContext` 身份 | 登录/用户数据在 Redis/PG 的具体边界按实现展开 | Filter/Interceptor→上下文→业务 | 线程池跨线程需 TTL/显式恢复；Consumer 需手动设置/清理 | `framework/context`；`system/user` |
| 知识库与管理 API | `rag` 的 knowledge/admin/ingestion | 管理员/用户 CRUD 与运行请求 | 知识、配置、任务、Trace 投影 | PostgreSQL；原文件在对象存储 | Controller→领域 Service→Mapper/外部存储 | CRUD 成功不能替代索引/运行闭环 | `rag/.../knowledge/controller`；`rag/.../admin` |

## 2. 知识文档主写路径

| 节点 | Owner | 输入 | 输出 | 状态/持久化 | 正常路径 | 主要失败边界 | 源码锚点 |
|---|---|---|---|---|---|---|---|
| 上传/远程来源 | `KnowledgeDocumentServiceImpl` | Multipart 或 URL、kbId、摄取规格 | `KnowledgeDocumentVO` | 原文件→对象存储；元数据→`t_knowledge_document(PENDING)` | 校验→保存对象→Parser 可用性→插文档 | 不支持 MIME 时删对象；上传完成仍不可检索 | `KnowledgeDocumentServiceImpl#upload` |
| 对象存储 | `FileStorageService` 及 S3/OSS 实现 | 文件字节、collection/key | URL/Stream | S3 兼容或 OSS | put/open/delete | 对象与 DB 不是同一存储事务，失败窗口需补偿 | `rag/.../service/FileStorageService.java` |
| 显式开始分块 | `KnowledgeDocumentServiceImpl` | docId | 事务消息 | 文档→`RUNNING`；Schedule upsert | 条件更新→本地事务→MQ | 重复 RUNNING 被拒；MQ 回查/重试仍需运行证据 | `KnowledgeDocumentServiceImpl#startChunk` |
| RocketMQ Consumer | `KnowledgeDocumentChunkConsumer` | `KnowledgeDocumentChunkEvent` | 调用 `executeChunk` | MQ 消费状态不作为业务文档终态 | 恢复 UserContext→Service→finally 清理 | 消费重投与业务幂等需结合 MQ 适配核验 | `KnowledgeDocumentChunkConsumer#onMessage` |
| 固定摄取内核 | `DefaultIngestionKernel` | `DocumentRef`、bytes、`IngestionSpec`、`VectorTarget` | `IngestionOutcome` | 内核本身不写任务状态/日志 | MIME→parse→chunk→embed→index | 空文件、未知 MIME、无 Parser、空 Chunk、模型/写入失败 | `DefaultIngestionKernel#run` |
| Parser 注册表 | `ParserRegistry` | MIME + parse profile | `DocumentParser` / structured blocks | Parser 本身不拥有文档终态 | require→parseStructured | 上传时 `canParse` 只是前置能力校验；真实字节仍会重新探测 | `rag/.../core/parser/registry/ParserRegistry.java` |
| 分块 | `ChunkingService` | `List<Block>` + budget | `List<Chunk>` | 暂态，随后进入 Embedding/落点 | 结构类型→策略→预算 | 空结果使整次摄取失败 | `rag/.../core/chunk/ChunkingService.java` |
| Embedding | `ChunkEmbeddingService` + AI Infra | Chunk + VectorTarget | EmbeddedChunk | 向量值为派生数据 | 批量请求→维度校验 | 供应商、凭据、维度或批次错误 | `rag/.../core/ingest/embed/ChunkEmbeddingService.java` |
| Chunk/索引替换 | `ChunkIndexWriter` + `ChunkSink` | EmbeddedChunk 列表 | 全落点替换 | 关系 Chunk + 向量/可选派生落点 | TransactionOperations→逐 sink replace | Java 事务外的远端索引是否可回滚不能先验保证 | `ChunkIndexWriter#replaceDocument` |
| 文档与分块日志收尾 | `KnowledgeDocumentServiceImpl` | `IngestionOutcome` 或异常 | SUCCESS/FAILED | `t_knowledge_document` + `t_knowledge_document_chunk_log` | 回填 MIME/Chunk 数/各阶段耗时 | catch 后标 FAILED；外部副作用清理需按失败点验证 | `runChunkTask`；`markChunkSucceeded/Failed` |

## 3. 通用可配置入库子系统

| 节点 | Owner | 输入 | 输出 | 状态/持久化 | 正常路径 | 主要失败边界 | 源码锚点 |
|---|---|---|---|---|---|---|---|
| `/ingestion/tasks` | `IngestionTaskController/ServiceImpl` | Pipeline ID + source/file | `IngestionResult` | `t_ingestion_task` | 查定义→插 RUNNING→同步 execute→更新终态 | 必须有 Pipeline；HTTP 请求承载同步执行时延 | `IngestionTaskServiceImpl#executeInternal` |
| Pipeline 定义 | `IngestionPipelineService` | 数据库 Pipeline/Node 行 | `PipelineDefinition` | `t_ingestion_pipeline(_node)` | Mapper→Definition | 冻结 init data 未发现默认定义；不能假定默认节点顺序 | `rag/.../ingestion/service` |
| IngestionEngine | `IngestionEngine` | Definition + Context | 终态 Context + NodeLog | Context 暂态，调用方保存日志 | 唯一根→nextNodeId 链→COMPLETED | 环、断链、0/多根、未知节点、节点异常 | `IngestionEngine#execute` |
| 可配置节点 | 六个 `IngestionNode` 实现 | Context + NodeConfig | NodeResult + Context 变更 | 副作用依节点而异 | 条件→execute→log→next | “配置可扩展”不等于任意 DAG；当前是单根链 | `rag/.../ingestion/node/*.java` |
| Task/Node Log | `IngestionTaskServiceImpl` | Context logs | Task/Node VO | `t_ingestion_task(_node)` | 保存 node 日志→更新 task | Service 有事务，但节点内远端副作用是否原子需逐个核验 | `saveNodeLogs`；`updateTaskFromContext` |

边界警告：知识文档的 `ProcessMode.PIPELINE` 当前在 `runChunkTask` 中显式失败，以上通用子系统不是当前知识文档默认执行器。

## 4. 确定性 RAG 读路径

| 节点 | Owner | 输入 | 输出 | 状态/持久化 | 正常路径 | 主要失败边界 | 源码锚点 |
|---|---|---|---|---|---|---|---|
| RAG HTTP/SSE 入口 | `RAGChatController` / `RAGChatServiceImpl` | question、conversationId、deepThinking | META + 流事件 | task 注册在 `StreamTaskManager` | emitter→callback→queue | Controller 幂等只覆盖同步窗口 | `RAGChatController#chat`；`RAGChatServiceImpl#streamChat` |
| 全局排队/并发 | `ChatQueueLimiter` + `FairDistributedRateLimiter` | 请求、最大等待、许可配置 | acquired 或 reject 流 | Redis 公平队列/许可 | acquire→专用 executor | timeout/reject 会保存 REJECTED；上下文需透传 | `ChatQueueLimiter#enqueue` |
| 会话记忆 | `ConversationMemoryService` | conversation/user | history + 新 USER messageId | `t_conversation`、`t_message`、summary | load→append user | 标题/摘要模型失败与消息主链需分开讲 | `StreamChatPipeline#loadMemory` |
| 改写拆分 | `QueryRewriteService` | 原问题 + history | `RewriteResult` | 通常为本轮暂态/Trace | `rewriteWithSplit` | 模型输出解析和回退策略后章详证 | `StreamChatPipeline#rewriteQuery` |
| 意图/引导 | `IntentResolver` + `IntentGuidanceService` | RewriteResult | SubQuestionIntent/Guidance | 意图树配置在 PG/注册表 | resolve→guidance | 歧义短路；system-only 直接回答 | `StreamChatPipeline#resolveIntents/handleGuidance` |
| 检索编排 | `RetrievalEngine` | 子问题意图 | `RetrievalContext` | 本轮暂态；Trace 节点 | 子问题并行→KB/MCP 分支合并 | 某子任务失败的收敛需结合实现；空上下文主链短路 | `RetrievalEngine#retrieve` |
| 多通道召回 | `MultiChannelRetrievalEngine` | 单子问题、scope、budget | ChannelResults | 向量/关键词/图谱索引是派生数据 | 启用通道稳定派发并行执行 | 通道失败/超时→空结果；无通道→警告+空 | `retrieveKnowledgeChannels` |
| 后处理漏斗 | 五个 `SearchResultPostProcessor` | 多通道 Chunk | 最终证据 | 本轮暂态 | order 1/5/10/15/20 | 单处理器异常被跳过；可能改变证据质量而不断主链 | `executePostProcessors` |
| Prompt/引用 | `RAGPromptService` + Source/Citation assembler | Rewrite、证据、意图、history | `ChatRequest` + sources/grounding | sources/grounding 随 assistant 消息落库 | 唯一编号→富化→结构化消息 | 内部 docId 不能泄漏到可见文本 | `StreamChatPipeline#streamRagResponse` |
| 模型基础设施 | `LLMService` / `infra-ai` 路由 | `ChatRequest` | StreamCallback 增量/终态 | 健康/熔断等运行态按实现存储 | 候选→首包→流 | 供应商失败、首包超时、取消；不能只看“开始输出” | `infra-ai/.../LLMService` 实现；`StreamChatPipeline#streamLLMResponse` |
| RAG SSE/消息收尾 | `StreamChatEventHandler` | callback 增量、sources、grounding | MESSAGE/FINISH/CANCEL/DONE | assistant `NORMAL/INTERRUPTED`；reject 另路 | 累积→落库→终态事件 | error 不保存 assistant 失败消息；落库失败仍可能完成 SSE | `StreamChatEventHandler` |
| RAG Trace | `StreamChatTraceRunner` + record service | question/task/callback | Run + Node | `t_rag_trace_run/node` | start→首正文 TTFT→finish | Trace 写失败被日志吸收，不应打断答复 | `StreamChatTraceRunner#run` |

## 5. ReAct Agent 分支

| 节点 | Owner | 输入 | 输出 | 状态/持久化 | 正常路径 | 主要失败边界 | 源码锚点 |
|---|---|---|---|---|---|---|---|
| Agent HTTP/SSE 入口 | `AgentChatController/ServiceImpl` | question、conversationId | Agent META/事件 | Agent conversation/user message | gate→startRun→subscribe | 仅 `engine.type=agent` 装配；启动失败必须就地释放 gate | `AgentChatServiceImpl#streamChat/startRun` |
| 每用户运行闸门 | `AgentRunGate` | user/task/conversation | release hook 或拒绝 | Redis bucket，TTL=2×SSE timeout | setIfAbsent→compareAndSet release | stale releaser不能清新任务；进程崩溃靠 TTL | `AgentRunGate` |
| ReAct Runtime | `ReActAgentProvider` + AgentScope | persona、toolkit、RuntimeContext | `Flux<AgentEvent>` | State Store + 当前节点内存缓存 | get/build Agent→streamEvents | 动态工具循环非确定性；达到上限只提示并生成总结 | `ReActAgentProvider#buildAgent`；`AgentChatServiceImpl#startRun` |
| 工具目录 | `AgentToolCatalog` | Prompt 槽、意图树、MCP registry | Toolkit + fingerprint + display names | 快照随 cached Agent 保持 | resolve→buildToolkit | 配了但不可用 MCP 只告警不挂载；描述为空可能拒绝建 Agent | `AgentToolCatalog` |
| 知识检索工具 | `KnowledgeSearchTool` + `KnowledgeSearchFacade` | query + 最近 2 轮 | 同步证据答案文本 | 不走 RAG SSE/消息表 | KB-only 改写/意图/检索/合成 | 空证据返回固定文本；工具异常返回 ERROR block | `KnowledgeSearchTool#execute`；`KnowledgeSearchFacade#search` |
| MCP 工具桥 | `McpToolBridge` | AgentTool 参数 | ToolResultBlock | 复用 RAG MCP executor/registry | bridge→execute | Schema/远端错误转成工具结果；不是独立 AgentScope MCP Client | `agent/.../tool/McpToolBridge.java` |
| Agent State | `PgAgentStateStore` | user/session/key + State | opaque JSON | `t_agent_state` | save/get/list/delete | 业务层无法单独证明框架所有终态都已 save | `PgAgentStateStore` |
| 压缩/长期记忆 | 两个 middleware + `AgentMemoryPipeline` | Agent context / 轮次结束 | 压缩上下文、memory records | compaction/memory/control/extraction 表 | user memory→context compaction；终态后异步 extract | 抽取失败仅记录日志；与 State/会话消息不可等同 | `ReActAgentProvider#buildAgent`；`scheduleMemoryExtraction` |
| Agent 事件桥 | `AgentStreamEventBridge` | AgentEvent | Agent message/tool/hint/finish/cancel | assistant message + blocks | event→buffer/block→RunHandle | onError 不保存 assistant 失败消息 | `AgentStreamEventBridge` |
| Agent 统一收尾 | `AgentRunHandle` | complete/cancel/fail | emitter 终结 | unregister；release hooks | CAS winner→body→finally hooks | 单 hook 失败不阻塞其余；body 失败被收敛 | `AgentRunHandle#settle` |

## 6. 共享存储与可选基础设施

| 节点 | Owner | 持有内容 | 不应被误解为 | 默认/条件 | 源码锚点 |
|---|---|---|---|---|---|
| PostgreSQL | 各 Mapper/Service | 31 表的业务事实、Agent State、Trace、入库任务、pgvector | “只存聊天记录”或“所有外部状态的全局事务” | 必需主存储；默认向量后端也是 PG | `resources/database/schema_pg.sql` |
| Redis/Redisson | framework/rag/agent | 认证相关、队列/许可、锁、运行位、取消等协调态 | 长期事实存储 | 默认配置存在；真实能力依赖 Redis 可用 | `bootstrap/application.yaml`；各 limiter/gate |
| 对象存储 | rag | 原文件与解析资产 | 文档元数据或可检索完成标志 | 默认 S3 兼容，可选 OSS | `rag.storage.*` |
| RocketMQ | framework MQ + knowledge Consumers | 分块/清理等异步事件 | 所有任务的通用队列 | 分块主链已确认使用；完整必需性仍 open | `knowledge/mq`；`framework/mq` |
| 可选 ES/LightRAG/Web/Milvus | 对应条件实现 | 关键词、图谱、联网或替代向量索引 | 当前默认都已启用 | YAML 默认仅 pgvector 向量通道 | `bootstrap/application.yaml`；条件 Bean |

## 7. 第一章画图检查

- [x] 上传、开始分块、MQ 消费和固定内核拆成不同节点。
- [x] 通用 IngestionEngine 与知识文档主链并列，标出 `PIPELINE` 模式暂停。
- [x] RAG 和 Agent 分别有入口、编排与 SSE 收尾。
- [x] Agent 只在 `KnowledgeSearchFacade` 处复用 RAG 检索，而不是复用整个 RAG HTTP/SSE 链。
- [x] PostgreSQL、对象存储、Redis、MQ 和可选索引有不同状态责任。
- [x] 每个节点至少有冻结源码锚点；测试/运行证据缺口没有伪装成完成。
