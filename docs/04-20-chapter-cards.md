# 第 4～20 章章节卡片

> 阶段：P2 全书骨架，v1.1 学习/面试目标已同步。每张卡保证专题有总体图位置、上游输入、下游输出和源码入口；正文逐章补责任、调用链、状态、失败语义、设计权衡和面试追问，不以读者运行复现为目标。

## 全书主线索引

| 段落 | 章节 | 总体图区域 | 共同产出 |
|---|---|---|---|
| 知识写路径 | 4～7 | Upload → MQ → Kernel → Index | 可被检索引擎读取的证据 |
| 确定性读路径 | 8～13 | RAG API → Memory → Retrieval → LLM → SSE | 有来源的 RAG assistant 消息与 Trace |
| Agent 分支 | 14～16 | Agent API → ReAct → Tools/State → Agent SSE | 动态工具执行结果、Agent 消息和可恢复状态 |
| 工程闭环 | 17～20 | 横切护栏 → UI → 配置组装 → Interview | 能解释运行边界、能推演故障、能诚实讲述的项目 |

---

## 第 4 章：文档从哪里来——上传、远程来源、定时刷新与并发保护

- **总体图位置**：`KnowledgeDocument API → 上传/远程来源 → 对象存储 + PENDING 文档`。
- **上游输入**：第 3 章的知识库、文档、对象存储和 Schedule 所有权。
- **核心问题**：怎样在第一个副作用前完成可完成的校验，并让本地文件和远程资料安全成为一个可处理的文档？
- **叙事主轴**：
  1. `KnowledgeDocumentController.upload` 的 multipart/来源参数；
  2. 知识库与用户归属、文件大小/并发、来源和调度校验；
  3. `resolveStoredFile` 与对象键/URL；
  4. `ParserRegistry.canParse` 前置拦截和对象补偿删除；
  5. `PENDING` 文档插入；
  6. `RemoteFileFetcher` 的 ETag → Last-Modified → Hash 判断；
  7. Schedule/lease/刷新冲突和文件切换失败窗口。
- **必须解释的反例**：上传返回 docId 不等于已经开始分块；对象存储成功不等于数据库元数据成功；远程 304/validator 不变不等于任务失败。
- **下游输出**：一个 `PENDING` 文档和可读原文件，交给第 5～6 章。
- **主要源码**：`KnowledgeDocumentController`、`KnowledgeDocumentServiceImpl#upload`、`RemoteFileFetcher`、`ScheduleRefreshProcessor`、上传并发信号量。
- **Source Map**：`SM-003`、`SM-013`、`SM-014`。
- **讲解证据**：Fetcher/Schedule 方法体、状态和异常分支；现有测试代码只用来确认边界案例。
- **大胆舍弃**：普通分页、改名、预览 DTO 映射；只保留会改变生命周期的 API。
- **桥梁**：文件已经“进仓”，下一章问 MIME、结构化 Block 和解析质量怎样决定后续分块上限。

## 第 5 章：文档怎样变干净——解析器、结构化结果与质量边界

- **总体图位置**：固定摄取内核的 `MIME → Parser → Block` 切片。
- **上游输入**：原始 bytes、文件名、docId、parse profile。
- **核心问题**：系统凭什么选择解析器，解析结果携带哪些结构，哪些“数据清洗”问题仍没有自动解决？
- **叙事主轴**：
  1. 扩展名只用于展示，真实 MIME 由 bytes + filename 探测并最终回填；
  2. `ParserRegistry.require(mime, profile)` 的路由；
  3. `DocumentParser.parseStructured` → `ParsedDocument.blocks`；
  4. docId/sourceFile 选项怎样维系图片资产归属；
  5. Tika/MinerU/其他 Parser 的装配条件和输出边界；
  6. Block 类型、页码/来源/资产元数据怎样交给分块和引用；
  7. 扫描件、公式、表格、双栏、OCR 错误等质量边界。
- **必须解释的反例**：`canParse` 成功只说明有候选 Parser，不等于某份复杂 PDF 解析质量合格；解析有文本不等于结构/位置正确。
- **下游输出**：带来源元数据的结构化 Block 列表，交给第 6～7 章。
- **主要源码**：`DefaultIngestionKernel#run`、`ParserRegistry`、`DocumentParser`、`ParsedDocument`、各 Parser 实现、资产存储。
- **Source Map**：`SM-015`、`SM-016`。
- **计划证据**：每类支持格式最小 fixture；PDF/Office/图像解析结果和资产目录检查；Live MinerU 单独标注。
- **大胆舍弃**：逐字段罗列每个 Parser DTO；聚焦选择、结构和失败边界。
- **桥梁**：下一章把 Block 送进唯一固定内核，并解释通用 Pipeline 为什么不能冒充这条主链。

## 第 6 章：入库主循环——固定摄取内核与可配置 Pipeline 的真实边界

- **总体图位置**：`startChunk → RocketMQ → DefaultIngestionKernel`，旁路是 `/ingestion/tasks → IngestionEngine`。
- **上游输入**：PENDING 文档、对象 bytes、IngestionSpec、VectorTarget；或显式 PipelineDefinition + DocumentSource。
- **核心问题**：当前知识文档真正执行哪条摄取序列，通用可配置 Pipeline 又在哪个边界独立存在？
- **叙事主轴 A：知识文档主链**：
  1. `startChunk` 事务消息与条件更新 RUNNING；
  2. Consumer 恢复/清理 UserContext；
  3. `runChunkTask` 写 RUNNING log；
  4. 固定五步 MIME/parse/chunk/embed/index；
  5. Outcome 耗时和 SUCCESS/FAILED 收尾。
- **叙事主轴 B：通用 Pipeline**：
  1. `/ingestion/tasks` 要求显式 Pipeline ID；
  2. Definition/Context/Node/NodeResult；
  3. 单根、环/断链校验、条件、nextNodeId；
  4. 六类节点与 Task/Node Log；
  5. 同步执行和事务/外部副作用边界。
- **版本警告**：`KnowledgeDocumentServiceImpl.runChunkTask` 对 `ProcessMode.PIPELINE` 明确失败；源码无默认 Pipeline 种子顺序。
- **下游输出**：EmbeddedChunk 及索引替换请求；或通用 Task 终态/节点日志。
- **主要源码**：`KnowledgeDocumentServiceImpl#startChunk/runChunkTask`、`KnowledgeDocumentChunkConsumer`、`DefaultIngestionKernel`、`IngestionTaskServiceImpl`、`IngestionEngine`、六 Node。
- **Source Map**：`SM-004`～`SM-007`、`SM-016`～`SM-018`。
- **讲解证据**：`startChunk`、Consumer、`runChunkTask`、固定 Kernel 与通用 `IngestionEngine` 的实际方法体；现有测试用例作边界例子。
- **大胆舍弃**：不逐行展开所有 Node settings；只讲改变执行图/副作用的字段。
- **桥梁**：两条摄取路径都可能产生 Chunk/索引，下一章聚焦落点一致性和“真正可检索”的证明。

## 第 7 章：从 Chunk 到可检索证据——分块、Embedding 与索引一致性

- **总体图位置**：`ChunkingService → ChunkEmbeddingService → ChunkIndexWriter → relation/vector/optional sinks`。
- **上游输入**：结构化 Block、预算、VectorTarget、DocumentRef。
- **核心问题**：怎样把 Chunk 业务事实和多个派生索引整体替换，并知道它们是否仍一致？
- **叙事主轴**：
  1. Block-aware Chunking 和 budget 不变式；
  2. Chunk 元数据、来源/资产引用；
  3. Embedding client、批次和维度从 target 来；
  4. `ChunkIndexWriter` 的 sink 扇出；
  5. `RelationalChunkSink` 与 `VectorChunkSink`；
  6. pgvector 默认与 Milvus/ES/LightRAG 可选边界；
  7. replace/delete、事务边界和外部落点补偿；
  8. 文档 enabled/scope/threshold 怎样影响“有向量但未召回”。
- **下游输出**：可以被第 11 章 SearchChannel 读取的证据集合。
- **主要源码**：`ChunkingService`、`ChunkEmbeddingService`、`ChunkIndexWriter`、两个 ChunkSink、VectorStore 实现、Schema/YAML。
- **Source Map**：`SM-019`～`SM-021`、`SM-026`、`SM-029`。
- **讲解证据**：Chunk 策略、Embedding、`replaceDocument`、各 Sink 方法体和 Schema；可选后端逐个标注组装条件。
- **大胆舍弃**：不做向量数据库百科；只解释项目抽象、默认值和一致性窗口。
- **桥梁**：写路径到此交付“可检索候选”，第 8 章从用户请求进入读路径。

---

## 第 8 章：一次问题从哪里开始——HTTP、并发闸门、任务与 SSE 生命周期

- **总体图位置**：`/rag/v3/chat → ChatQueueLimiter → StreamTaskManager → Trace/Pipeline`。
- **上游输入**：用户 question、可选 conversationId、deepThinking。
- **核心问题**：系统怎样在长连接开始前/期间限制并发，并让拒绝、停止、断线和完成都有终态？
- **叙事主轴**：Controller 幂等同步窗口；emitter timeout；Callback 初始化 META/register；Redis 公平许可；TTL 上下文；acquire/timeout/cancel binder；reject 落库/事件；stop→task manager→upstream handle。
- **下游输出**：被许可的 `StreamChatContext` 和 trace-aware callback，交给第 9 章。
- **主要源码**：`RAGChatController`、`RAGChatServiceImpl`、`ChatQueueLimiter`、`FairDistributedRateLimiter`、`StreamTaskManager`、`SseEmitterSender`。
- **Source Map**：`SM-022`、`SM-023`。
- **讲解证据**：QueueLimiter、TaskManager、Emitter 和 cancel 方法体；用源码时序表还原 normal/timeout/reject/cancel 事件序列。
- **大胆舍弃**：Lua/ZSET 细节只在它解释公平、原子或泄漏时展开。
- **桥梁**：许可拿到后，Pipeline 第一件业务副作用是加载历史并保存 USER；第 9 章从这里继续。

## 第 9 章：用户说的话不等于该搜的词——会话记忆、改写与拆分

- **总体图位置**：`Memory → Rewrite/Split`。
- **上游输入**：question、conversation/user、已获得的 RAG task。
- **核心问题**：如何用有限历史消解指代并生成可检索子问题，同时避免把全部聊天无限塞给模型？
- **叙事主轴**：history load；USER append 与 replyTo；recent turns + persistent summary；标题/摘要边界；`rewriteWithSplit` 输入输出；原问题/改写问题/子问题；失败/空结果回退；Agent `KnowledgeSearchTool` 只取最近两轮的对照。
- **下游输出**：`RewriteResult` 交给意图树。
- **主要源码**：`StreamChatPipeline#loadMemory/rewriteQuery`、`ConversationMemoryService`、`QueryRewriteService`、MemoryProperties。
- **Source Map**：`SM-024`、`SM-034`。
- **讲解证据**：改写 Prompt/输出契约、三种输入在代码中的流向、消息/摘要表与现有契约测试。
- **大胆舍弃**：不完整复述 Prompt 文本；只展示决定行为的结构与失败处理。
- **桥梁**：子问题仍不知道查哪个库，第 10 章用意图树把“搜什么”变成 scope。

## 第 10 章：该查哪个库——意图树、歧义引导与多知识库路由

- **总体图位置**：`Rewrite → IntentResolver / Guidance → RetrievalScope`。
- **上游输入**：改写问题和子问题。
- **核心问题**：多个子问题、多个意图和多个知识库同时出现时，系统怎样决定收窄、引导或直接系统回答？
- **叙事主轴**：意图节点/层级/库绑定/MCP 工具；分类评分；NodeScore 过滤；歧义引导；system-only；多子问题合并；scope threshold/补充路；低置信全局检索。
- **下游输出**：每个子问题的 `SubQuestionIntent` 和检索范围。
- **主要源码**：`IntentResolver`、`IntentNodeRegistry`、`IntentGuidanceService`、`RetrievalScopeResolver`、Intent Tree Controller/表。
- **Source Map**：`SM-025`、`SM-027` 的 scope 相关部分。
- **讲解证据**：意图树结构、歧义/system/global/directed 四个源码分支、Trace 字段和现有 fixture。
- **大胆舍弃**：普通意图 CRUD；聚焦评分、范围和短路。
- **桥梁**：scope 决定“看哪些库”，第 11 章决定“用哪些检索方式和多少预算”。

## 第 11 章：多路召回怎样协作——检索范围、预算与并行通道

- **总体图位置**：`RetrievalEngine → MultiChannelRetrievalEngine → SearchChannel`。
- **上游输入**：SubQuestionIntent、scope、三段 budget。
- **核心问题**：子问题与检索通道怎样并行，同时让某一路超时不钳制整次回答？
- **叙事主轴**：子问题并行；KB/MCP 分流；共同 SearchContext；enabled+稳定派发；Vector 默认；Keyword/Graph/Web 条件；15s timeout；空结果降级；无通道配置事故；20/40/10 budget 不变式。
- **下游输出**：各通道带来源/分数/延迟的候选 Chunk。
- **主要源码**：`RetrievalEngine`、`MultiChannelRetrievalEngine`、`SearchChannel`、四通道、`SearchChannelProperties`。
- **Source Map**：`SM-026`、`SM-027`、`SM-029`。
- **讲解证据**：MultiChannel 编排代码、PG vector 默认实现、可选通道的 Bean 条件与 timeout/降级分支。
- **大胆舍弃**：不写四篇孤立搜索百科；所有通道都从共同输入、作用域、预算和失败协议比较。
- **桥梁**：候选只是“多而杂”，第 12 章沿有序后处理漏斗收窄到最终证据。

## 第 12 章：三十条候选怎样变成十条证据——去重、融合、精排与证据门

- **总体图位置**：`ChannelResults → PostProcessors → final evidence`。
- **上游输入**：多个通道候选和 SearchContext。
- **核心问题**：为什么检索返回 TopK 仍可能没有答案，系统怎样稳定地去重、融合、精排并整批拒绝低相关证据？
- **叙事主轴**：Processor 接口/enable/order；Dedup 1；RRF Fusion 5；Rerank 10；Evidence Gate 15；Metadata Enrichment 20；候选上限40；最终10；处理器异常跳过；阈值0.2需随模型重测。
- **下游输出**：最终 Chunk + 归因/eligible intent IDs。
- **主要源码**：五个 PostProcessor、`MultiChannelRetrievalEngine#executePostProcessors`、Rerank infra、Search properties。
- **Source Map**：`SM-027`～`SM-029`。
- **讲解证据**：后处理器顺序、固定候选 fixture 与 order/size/score 变化；不宣称未评测的质量提升。
- **大胆舍弃**：RRF 数学只讲影响当前 k=20 的最小公式；不铺陈信息检索教科书。
- **桥梁**：最终证据要变成模型可读且用户可追溯的上下文，第 13 章完成生成和收尾。

## 第 13 章：证据怎样变成答案——来源、Prompt、模型路由与流式收尾

- **总体图位置**：`Sources/Grounding → Prompt → LLMService → RAG EventHandler/Trace`。
- **上游输入**：RewriteResult、IntentGroup、RetrievalContext、history。
- **核心问题**：同一份证据怎样同时服务 Prompt、来源面板、落库和推荐追问，并在模型故障/取消后保持可解释终态？
- **叙事主轴**：来源唯一编号；citation enabled 的边界；内部 docId 清理；grounding 不进 Prompt但随消息保存；structured messages；MCP场景温度差；模型候选/首包/熔断；thinking/content；normal/cancel/error；Trace first packet/finish。
- **下游输出**：RAG assistant 消息、sources、grounding、Trace、终态 SSE。
- **主要源码**：`StreamChatPipeline#streamRagResponse`、Assemblers、`RAGPromptService`、`LLMService`/infra routing、`StreamChatEventHandler`、`StreamChatTraceRunner`。
- **Source Map**：`SM-030`、`SM-031`，并回用 `SM-025`。
- **讲解证据**：Prompt 组装、模型路由、正常/取消/error 回调、DB message 与 Trace 收尾方法体。
- **大胆舍弃**：不逐行展示全部系统 Prompt；只解释槽位、顺序、证据隔离和参数。
- **桥梁**：确定性 RAG 闭环完成。第 14 章对比为什么默认配置仍选择 ReAct Agent，而不是把固定 Pipeline 删除。

---

## 第 14 章：为什么还需要 Agent——确定性 Pipeline 与 ReAct Runtime

- **总体图位置**：RAG/Agent 两分支的分叉与 `KnowledgeSearchFacade` 汇合点。
- **上游输入**：已经理解的确定性 RAG 能力。
- **核心问题**：哪些任务适合固定短路和漏斗，哪些任务需要模型动态选择工具，二者怎样共享而不互相污染？
- **叙事主轴**：engine type类兜底/YAML默认；Agent conditional；副作用前 gate；persona+catalog fingerprint；ReAct iteration/retry/max-iters；AgentScope events；与 StreamChatPipeline 对照；动态性/确定性/成本/恢复权衡。
- **下游输出**：一次 ActiveAgent、RuntimeContext 和动态事件流。
- **主要源码**：`AgentChatController/ServiceImpl`、`AgentRunGate`、`ReActAgentProvider`、AgentProperties。
- **Source Map**：`SM-008`、`SM-011`、`SM-032`、`SM-033`。
- **讲解证据**：Agent 组装、gate、loop、tool call、max iteration 与收尾分支；现有测试用例补充竞态边界。
- **大胆舍弃**：不把 ReAct 写成泛化论文；只沿当前 AgentScope 适配。
- **桥梁**：Agent 有循环但没有行动能力，第 15 章打开工具目录。

## 第 15 章：Agent 拿什么行动——工具目录、知识检索、MCP 与参数校验

- **总体图位置**：`ReAct → AgentToolCatalog → knowledge/MCP/memory tools`。
- **上游输入**：persona、意图树、MCP registry、Prompt slots、RuntimeContext。
- **核心问题**：一个工具怎样从描述/Schema 变成可执行结果，目录变化为何会触发 Agent 重建？
- **叙事主轴**：ResolvedCatalog snapshot；fingerprint；KnowledgeSearchTool 固定注册；最近两轮；KnowledgeSearchFacade KB-only；MemoryFlush 可选；MCP配置与注册表交集；McpToolBridge；readOnly/default；参数三态和错误 block；展示名/轨迹。
- **下游输出**：ToolResultBlock 回注 ReAct，工具进度进入 Agent Block/SSE。
- **主要源码**：`AgentToolCatalog`、`KnowledgeSearchTool`、`KnowledgeSearchFacade`、`McpToolBridge`、`MemoryFlushTool`、rag MCP registry/executor、独立 MCP Server。
- **Source Map**：`SM-034`、`SM-035`、`SM-010`。
- **计划证据**：catalog/knowledge tool 单测；MCP schema fixture；clarify/failed/success；远端 MCP Live。
- **大胆舍弃**：示例天气/票务数据不包装成真实业务；MCP协议百科只保留影响工具执行的字段。
- **桥梁**：工具事件和回答只是可见输出，下一章解释 State、压缩、长期记忆和三路收尾怎样让 Agent 不失控。

## 第 16 章：Agent 如何不失忆也不失控——State、压缩、长期记忆与收尾

- **总体图位置**：`ReAct → Agent State/Memory` 与 `EventBridge → RunHandle`。
- **上游输入**：Agent event stream、业务会话、RuntimeContext。
- **核心问题**：业务消息、AgentScope State、上下文压缩和长期记忆分别解决什么，正常/取消/失败怎样统一释放？
- **叙事主轴**：四种状态对照；PgAgentStateStore opaque JSON；middleware顺序；cache/PG；EventBridge buffers/blocks；NORMAL/INTERRUPTED/error；RunHandle CAS/finally/hooks；gate release；local cache eviction；background memory extraction；多节点边界。
- **下游输出**：可回放业务消息、框架 State、长期记忆记录和已释放运行资源。
- **主要源码**：`PgAgentStateStore`、两个 Middleware、Memory Pipeline、`AgentStreamEventBridge`、`AgentRunHandle`、`AgentChatServiceImpl`。
- **Source Map**：`SM-036`～`SM-038`、`SM-032`。
- **讲解证据**：RunHandle/Bridge/ChatService 方法体与现有测试；AgentScope 依赖源码；DB/Redis/cache 所有者对照。
- **大胆舍弃**：不声称框架所有 State save 时点，除非当前项目或冻结依赖源码能够确认。
- **桥梁**：三条业务主链讲完，第 17 章把它们共同依赖的认证、幂等、MQ、Trace和审计整理成护栏，而非工具类清单。

---

## 第 17 章：业务主线之外的护栏——认证、幂等、并发、MQ、Trace 与审计

- **总体图位置**：横跨 API、写路径、RAG、Agent 和存储的共享基础设施。
- **上游输入**：前三条链的真实失败窗口。
- **核心问题**：每个横切机制究竟保护哪段主链，它的保护窗口在哪里结束？
- **叙事主轴**：Sa-Token/UserContext；资源归属；IdempotentSubmit同步窗口；分布式 ID；TTL上下文；Redis队列/锁/gate区别；RocketMQ事务消息与 Consumer；Trace Context/Run/Node；BizChangeLog快照；线程池；失败不互相拖垮原则。
- **下游输出**：一张“护栏→受保护箭头→剩余风险”表。
- **主要源码**：`framework` 对应包、`knowledge/mq`、RAG Trace、audit system、各 limiter/gate。
- **Source Map**：回用 `SM-004`、`SM-022`、`SM-023`、`SM-031`、`SM-032`。
- **讲解证据**：全仓 MQ use-point census；Q-005；认证/幂等/上下文调用点；Redis key owner 与状态机；实际审计注解范围。
- **大胆舍弃**：不按 Design Pattern 名称分类；只在解释真实护栏时提模式。
- **桥梁**：后端状态与事件已经清楚，第 18 章检查前端是否真的把这些终态和证据呈现出来。

## 第 18 章：控制台不是截图——前端状态、证据展示与管理闭环

- **总体图位置**：React 控制台 ↔ 两套聊天入口/管理 API。
- **上游输入**：RAG/Agent SSE 事件、服务端业务状态和管理 API。
- **核心问题**：页面临时态怎样与服务端持久状态对齐，断线/停止/刷新后能否恢复正确投影？
- **叙事主轴**：路由/权限；`useStreamResponse + chatStore`；`useAgentStream + agentChatStore`；事件逐项映射；sources/preview/feedback/recommended；Agent blocks/tools/hints；管理页到 API；loading/error/empty/permission；刷新重建。
- **下游输出**：前后端事件映射表、UI 状态转换表和管理页到 API 的导航图。
- **主要源码**：两 hook/store、类型/API层、Chat/Agent组件、Admin routes/pages。
- **Source Map**：`SM-039`，后端事件回用 `SM-023`、`SM-030`、`SM-038`。
- **讲解证据**：前端 hook/store/component 与后端 API/SSE 契约逐项对照；正常/reject/cancel/error/refresh 状态转换；不以浏览器复现代替源码状态分析。
- **大胆舍弃**：颜色/间距等视觉微调；只追踪会影响业务理解的交互状态。
- **桥梁**：UI/后端契约明确后，第 19 章解释配置怎样决定哪些实现被组装进系统。

## 第 19 章：配置如何改变系统——组装条件、默认选择与故障推演

- **总体图位置**：全部节点的配置与启动组装投影。
- **上游输入**：模块、状态、护栏和 UI 契约。
- **核心问题**：怎样从配置和 Bean 条件判断默认路径，而不是看到一个实现类就认为它一定会运行？
- **叙事主轴**：版本要求；PostgreSQL/pgvector Schema；Redis；S3 兼容存储；RocketMQ；模型供应商；主应用与 MCP Server；可选检索后端；`@ConditionalOnProperty`/工厂/注册表；故障在哪层可见。
- **下游输出**：默认拓扑、可选实现选择表和源码故障推演树。
- **主要源码**：POM、application YAML、database scripts、前端 package 与所有配置/工厂/注册类。
- **Source Map**：全表，重点 `SM-009`～`SM-012`、`SM-021`、`SM-026`、`SM-029`。
- **讲解证据**：配置绑定类、默认 YAML、Spring 条件、工厂选择和启动入口的交叉对照；显式登记 LightRAG 注释所述写入开关与冻结实现的漂移。
- **大胆舍弃**：供应商/中间件安装百科、密钥申请和运维手册。
- **桥梁**：读懂默认组装后，第 20 章把全书理解转成可口述的面试回答。

## 第 20 章：如何把源码理解讲出来——设计推演与面试叙述

- **总体图位置**：所有主链之上的口述与追问闭环。
- **上游输入**：全书的架构、调用链、状态、失败语义、配置与 Trace 理解。
- **核心问题**：怎样让面试官确信你真正读懂了项目，而不是只 clone、改名和背过 README？
- **叙事主轴**：空白纸画架构；三条主链口述；“为什么”和“如果失败”追问；去掉一层的影响推演；默认/可选/暂停能力辨析；项目归属与诚信表达；高频问题库。
- **下游输出**：项目口述模板、追问题库、参考回答、自我检查表和后续学习路线。
- **主要源码**：前 19 章的主链锚点，以及 README/NOTICE/UPSTREAM 的归属边界。
- **Source Map**：全表，重点 `SM-001`、`SM-040`、`SM-041`。
- **讲解证据**：每个参考回答都指回类/方法/配置/Schema；设计推断显式标注为推断。
- **大胆舍弃**：不背“企业级”营销话术；不伪造个人改造、用户量、性能、召回率或生产经验。
- **全书收束**：回到第一章总图，要求读者能沿任意箭头说清 owner、数据、状态、失败、设计价值和源码位置。

---

## 孤立章节检查

每章都必须满足：

```text
总体图节点
  + 上一章交付的对象
  + 一个核心问题
  + 源码入口
  + 状态/失败边界
  + 设计权衡/面试追问
  + 交给下一章的对象
```

检查结果：

- 第 4～7 章连续完成知识写路径，没有孤立的 Parser/向量数据库百科。
- 第 8～13 章沿一次 RAG 请求连续展开，没有把检索通道和后处理拆成无上下文清单。
- 第 14～16 章从 RAG/Agent 分叉到工具再到状态/收尾，KnowledgeSearchFacade 是显式共享点。
- 第 17～20 章分别承担护栏、用户投影、配置组装、面试收束，不重复业务主链。
- 章节 0～20 均能映射回第一章总体图或其源码/理解闭环。
