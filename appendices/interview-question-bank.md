# 附录 A：AsterRAG 分层面试追问题库

> 使用方式：先遮住答案口述，再核对“必答点”和源码锚点。每题不追求背全文；能说出 owner、顺序、状态和边界才算掌握。题目中的“项目”均指冻结 AsterRAG `98894c2c42c015a3c874c6b3c986ac863c85b731`。

## A.1 项目定位与架构

### Q1：这是你从零写的项目吗？

不是。核心来自 Apache-2.0 的 `nageoffer/ragent`，AsterRAG 保留上游历史、LICENSE、NOTICE 和来源说明。当前 fork 的真实改造主要是项目身份/首页/前端品牌与 CI 分层；核心能力应表述为“我深入跟踪并掌握的上游实现”。

源码锚点：`README.md`、`NOTICE`、`docs/UPSTREAM.md`、`git log upstream/main..main`。

### Q2：七个 Maven 模块是不是七个微服务？

不是。`bootstrap` 把 framework、infra-ai、system、rag、agent 装进一个 Spring Boot 主应用；`mcp-server` 才是独立入口。准确模型是模块化单体 + 独立 MCP Server。

源码锚点：根 `pom.xml`、`bootstrap/pom.xml`、两个 `*Application.java`。

### Q3：系统最重要的三条主链是什么？

1. 文档/URL → 对象与元数据 → MQ → 固定摄取内核 → Chunk/索引；
2. 问题 → 记忆/改写/意图 → 多通道检索/后处理 → LLM/SSE；
3. Agent 请求 → RunGate → ReAct → 工具 → State/Memory → 三路 finalizer。

### Q4：默认是 RAG 还是 Agent？

随仓库 YAML 是 `ragent.engine.type=agent`，所以 Agent 专属 Bean 装配，前端 EngineGate 默认进入 Agent 页。Java Properties 字段兜底是 workflow，只在配置键缺失/覆盖时生效。确定性 RAG 后端入口仍存在。

### Q5：Agent 与 Workflow 能不能理解为同一条链的两个 UI？

不能。它们有不同 Controller、Service、编排、SSE enum、消息表和前端 hook/store。Agent 会通过 `KnowledgeSearchFacade` 复用 RAG 检索窄口，但不复用完整 StreamChatPipeline 与 RAG SSE finalizer。

### Q6：PostgreSQL 只存聊天记录吗？

不是。31 张表覆盖用户、RAG 会话、知识/Chunk、入库任务、意图、Trace、Agent 配置/会话/State/压缩/长期记忆和 pgvector。

源码锚点：`resources/database/schema_pg.sql`。

### Q7：Redis 只是缓存吗？

不是。默认还负责 Snowflake 节点 ID、分布式 gate/queue/semaphore、任务 owner/cancel、pub/sub 和初始化锁。Snowflake `@PostConstruct` 失败会阻止启动。

### Q8：RocketMQ 是业务事实的 owner 吗？

不是。它承载异步触发/传递；文档、状态和反馈事实最终在业务表/对象存储。发送成功也不能等同于 Consumer 已完成。

### Q9：RAG Trace、审计日志、Agent raw frames 有什么不同？

- RAG Trace：确定性 RAG run/node 诊断；
- BizChangeLog：管理对象的 before/after 与操作者；
- raw frames：当前浏览器连接收到的最近 2000 条 Agent SSE 帧。

owner、寿命和回答的问题都不同。

### Q10：如何从源码判断一个能力是否真的启用？

按四级证据：POM 有依赖 → YAML/Properties 有值 → 条件 Bean 进入容器 → 本轮 `isEnabled`/工厂真正选中。仅看到实现类最多证明“支持”，不能证明“默认运行”。

---

## A.2 文档入库与索引

### Q11：上传成功后能立即检索吗？

不能。上传只保存原文件并插入 PENDING 元数据；显式开始分块后才异步解析、分块、Embedding、写关系 Chunk 与向量，最终 SUCCESS 才表达当前固定内核完成。

### Q12：为什么先写对象存储再写数据库？失败怎么办？

服务先获得持久对象 key，再创建可引用它的文档元数据。如果后续元数据或 MIME/配置校验失败，源码有删除刚保存对象的补偿分支。它是补偿，不是对象存储与 DB 的全局事务。

### Q13：开始分块为什么用事务消息？

它协调本地文档状态切 RUNNING 与异步消息提交，避免只改状态未发消息或只发消息未改状态。Consumer 重复/失败仍有独立边界，事务消息不等于 exactly-once 全链保证。

### Q14：当前知识文档使用可配置 Pipeline 吗？

默认不是。知识文档 `ProcessMode.FIXED` 走 `DefaultIngestionKernel` 固定五步；`ProcessMode.PIPELINE` 当前明确抛暂停异常。`/ingestion/tasks` 是另一套可按 `PipelineDefinition` 执行的通用子系统。

### Q15：固定五步是什么？

MIME 识别 → 结构化解析 → 分块 → Embedding → 索引替换。具体 sink 又把结果扇出到关系 Chunk 与向量落点。

### Q16：Parser 怎样选择？

`ParserRegistry` 按实际 MIME 与 ParseProfile 双键找实现；解析结果是带结构/provenance 的 Block 集合，不只是一个大字符串。无匹配与解析异常沿摄取失败分支上抛。

### Q17：为什么要保存 MIME，而不是只看扩展名？

扩展名可错或缺失，实际 MIME 参与 Parser 路由与支持性校验。文件名/扩展仍作为来源与显示信息，但不能独自决定解析器。

### Q18：`content` 与 `embeddingText` 有什么区别？

content 面向展示、引用和原文；embeddingText 可加入标题/父级结构上下文，面向语义向量化。两者来自同一 Chunk，但责任不同。

### Q19：Chunk ID 为什么重要？

它跨关系 Chunk、向量、ES 等派生索引用作稳定标识，支持去重、元数据回表、更新/删除与来源定位。不同后端同步同一 ID 能减少融合歧义。

### Q20：`ChunkIndexWriter` 的事务能保证向量库原子吗？

不能自动保证。TransactionOperations 能约束同一数据库事务中的关系写；外部向量/ES/LightRAG 不受同一个本地事务控制。当前默认 pgvector 与关系表同库更接近同一事务边界，但 best-effort 装饰器仍是外部派生写。

### Q21：重新摄取为什么用整文 replace？

它先清理旧文档相关索引再写新 Chunk，避免旧新版本混存。失败窗口仍需按各 sink 的事务与补偿判断，不能说所有外部索引原子替换。

### Q22：文档 SUCCESS 的准确含义是什么？

表示当前固定摄取任务走完并完成其主落点，不等于所有可选外部派生系统永远一致，也不等于前端预览/检索质量已经人工验收。

### Q23：MinerU 失败会发生什么？

Parser 在业务调用期申请上传链接、上传、轮询、下载/解包；瞬时轮询异常会继续到 deadline，最终异常进入文档处理失败语义。Redis 许可初始化与 MinerU SaaS 可用性是两层不同检查。

### Q24：关系 Chunk 与向量为什么分开？

关系 Chunk 服务管理、回表、来源与修改；向量服务近邻搜索。把完整产品事实只存在向量后端会让 CRUD、审计与元数据约束困难。

---

## A.3 会话、记忆与问题理解

### Q25：RAG 会话有哪些持久对象？

会话列表、消息、增量摘要和反馈分表。USER/assistant 消息、summary 边界、sources/recommended/status 各有自己的持久字段或关联表。

### Q26：为什么保留 8 轮原文还要摘要？

近期原文保留细节，旧轮次通过摘要压缩上下文成本。默认第 9 轮开始满足摘要条件，配置校验要求 summaryStartTurns 大于 historyKeepTurns。

### Q27：Query Rewrite 会改掉用户历史吗？

不会。original question 持久化；rewrite/main/sub questions 供本轮检索/生成。它们是三个不同对象。

### Q28：改写模型失败后请求一定失败吗？

不一定。改写有 LLM 路径与规则/清洗兜底，具体异常分支会回退可用问题表达；不能把所有 LLM 失败都说成整个 RAG 失败。

### Q29：术语映射在哪一层？

查询词归一化发生在问题改写/理解阶段，把业务别名替换或扩展为目标术语；它不修改文档原文，也不等于 embedding 模型同义词能力。

### Q30：意图分类只用于选 Prompt 吗？

不是。意图节点可能决定知识库作用域、SYSTEM-only 短路、歧义引导，以及 MCP/Prompt 相关配置。需要按节点类型与路径解释。

### Q31：歧义问题为什么在检索前短路？

多个高分业务路径无法确定时，直接检索可能混入错误库。系统先生成澄清引导，避免为错误问题做昂贵召回/生成。

### Q32：SYSTEM-only 意图是什么？

它表示答案来自系统配置/意图内容，不需要知识检索。Pipeline 在检索前短路，仍要走相应消息与 SSE 收尾。

### Q33：全库、定向和补充路怎样选？

最高有效 KB 意图分低于 confidence threshold 时全库；高置信时主路搜命中库，并按 supplement ratio 给未命中库保底名额，防意图误判完全饿死正确证据。

### Q34：为什么 supplement ratio 不能为 1？

取 1 会把所有名额给未命中库，使“定向优先”主路清零。启动校验要求 <1；0 表示关闭补充路。

---

## A.4 多通道检索与后处理

### Q35：默认启用了哪些检索通道？

只启用 pgvector 向量通道。关键词 type=none/enabled=false，图谱 type=none/enabled=false，Web enabled=false。

### Q36：四类 SearchChannel 为什么还需要 `isEnabled`？

Bean 存在只表示实现可用；每轮仍按配置/key/context 决定参与。例如 ES/LightRAG backend 可用于写入/管理而 query channel 关闭。

### Q37：单通道失败会拖垮整次检索吗？

设计上不会。各通道 CompletableFuture 捕获异常，超时包装按空结果降级，其他通道继续融合。但 `orTimeout` 放弃迟到结果不等于取消底层任务。

### Q38：为什么原始分数不能直接合并？

向量、ES、图谱和 Web 的评分尺度不同。RRF 使用各通道内部 rank，减少量纲依赖，再由统一 Rerank 精排。

### Q39：RRF 公式中的 k 有什么作用？

每条结果按 `weight/(k+rank)` 累加。k 越大头部 rank 差异越平滑；当前默认 20，配合约 20–40 的候选池强调头部差异。它不是 final topK。

### Q40：去重发生在 RRF 前还是后？

后处理 order 为去重 1、融合 5、Rerank 10、证据门 15、元数据富化 20。去重先建立稳定候选，RRF 仍读取不可变 channel result 计算通道归因。

### Q41：为什么 Rerank 候选是 40，最终 TopK 是 10？

40 给精排足够候选空间，10 控制进入 LLM 的证据量；recall 20 是每通道扇出。三段预算分别控制召回、精排候选和上下文，启动校验保证不倒置。

### Q42：Rerank 失败会怎样？

RoutingRerankService 按候选 fallback，配置最后有 noop client。Noop 只截断、不打真实 rerankScore；Evidence Gate 发现整批无分时 warning 并放行。

### Q43：Evidence Gate 为什么不逐条删低分？

它当前是批级可信度闸门：看最高真实 rerank 分判断是否整批无关。过线后保留其他证据；逐条清洗不是它的责任。

### Q44：Metadata Enrichment 为什么最后做？

先在轻量候选上完成去重/排序/截断，最后只为最终少量 Chunk 批量回表补 docName/url/excerpt 等，减少数据库开销并保证 sources 完整。

### Q45：检索为空时还会调用答案 LLM 吗？

确定性 Pipeline 有 LLM 前空检索短路，返回固定无资料语义；不会为了形式完整而让模型无证据自由回答。

### Q46：Graph type=lightrag、query=false 时系统会做什么？

LightRagClient 与写同步装饰器仍装配，后台图谱能力也可使用；GraphSearchChannel 不参与问答召回。冻结源码没有接线 YAML 注释所说的独立 ingestion.enabled。

---

## A.5 生成、引用、SSE 与取消

### Q47：sources 在什么时候产生？

检索后元数据回表形成来源对象，生成前按唯一编号注入 evidence/prompt，完成 payload 和持久 assistant 消息保存 sources。正文 citation 通过 index 与 sources 对齐。

### Q48：`docId` 和 citation index 是同一个东西吗？

不是。index 是本次回答内的展示编号；docId 是跨请求定位文档的稳定标识。相同文档在另一轮可能拿不同 index。

### Q49：为什么模型输出引用还需要前端校验？

模型可能漏写规范链接或把普通 `[N]` 当编号。前端只有发现规范 `[N](#cite-N)` 模式后才扩展识别裸编号，并按 source.index 查真实来源。

### Q50：模型 fallback 为什么只允许在首包前？

首个正文一旦发给用户，再换模型会把两套输出拼成一个回答，语义与引用不可控。首包探测在提交前失败可切候选，提交后错误走当前流失败收尾。

### Q51：finish 与 done 有什么区别？

finish 携带 messageId、title、sources、messageStatus 等业务完成信息；done 只表示 SSE 生命周期结束并清理连接状态。

### Q52：RAG 有哪些业务终态？

- NORMAL：保存 assistant，finish + done；
- REJECTED：保存拒绝 assistant，meta/reject/finish/done；
- INTERRUPTED：保存非空部分回答，cancel + done；
- error：不保存 assistant error，走错误/Trace 收尾。

### Q53：为什么 USER 可能孤立？

Pipeline 在生成前先保存 USER。后续模型/链路失败时不写虚假 assistant error，所以历史可能只有 user。前端临时 error 刷新后消失，与此一致。

### Q54：用户点击停止为什么前端不立刻 abort fetch？

它发送 task stop 并继续等后端 finalizer 的 cancel/done，以取得可能的持久 messageId 和 INTERRUPTED。meta 尚未到时先记 cancelRequested，meta 到后补发 stop。

### Q55：断线重试是断点续传吗？

不是。前端重新 GET，没有 event id/Last-Event-ID。Agent 新请求可能被 RunGate 拒绝，Workflow 可能触发另一轮；这叫新请求重试，不是 resume。

### Q56：停止提示为什么刷新后消失？

`（已停止生成）` 是前端 cancel handler 临时追加，后端保存部分正文与 `messageStatus=INTERRUPTED`，不保存该后缀。刷新按服务端事实重建。

---

## A.6 ReAct Agent、工具与状态

### Q57：为什么 AgentRunGate 要放最前面？

它在创建会话、保存 USER、注册 task、发送 meta 前按 user 抢完整运行位，避免重复请求先留下副作用再被拒绝。

### Q58：ReAct 循环是什么？

模型基于上下文输出 reasoning 或 tool use；工具执行结果作为 observation 回到模型；模型继续 reasoning/调用，直到 final answer、maxIters、失败或取消。

### Q59：`max-iters` 与 `max-retries` 有什么区别？

maxIters 限制 reasoning/tool 循环轮数；maxRetries 是单次模型调用失败在同一 Agent 模型上的重试。都不代表跨模型 fallback。

### Q60：Agent 工具目录从哪里来？

固定知识检索工具；长期记忆配置开启时加入 memory flush；MCP 工具必须同时存在于意图/配置和实际 McpToolRegistry。每次 resolve 形成目录快照与 fingerprint。

### Q61：为什么工具目录要做 fingerprint？

ReActAgentProvider 用人设内容 + 工具目录指纹判断是否懒重建 Agent；控制台配置变化能在下一次取 Agent 时生效，同时在途 run 继续使用原实例/快照。

### Q62：Agent 的知识检索会再开一条 RAG SSE 吗？

不会。`KnowledgeSearchTool` 调同步 `KnowledgeSearchFacade`，复用改写、意图、检索和答案合成窄口；Agent 自己的 SSE bridge 统一对外输出。

### Q63：Workflow MCP 的参数澄清与 Agent 工具调用一样吗？

不一样。Workflow MCP 路径有独立 LLM 参数提取三态；Agent 使用模型原生 ToolUse 与 JSON Schema 校验。不能把 NEED_CLARIFICATION 直接套到 Agent。

### Q64：MCP Server 不可达会阻止主应用启动吗？

当前不会。McpClientAutoConfiguration catch 连接异常并跳过该 server；结果是远程工具不注册。对象存储/Redis 等默认依赖的策略不同。

### Q65：内置天气、工单、请假等工具是真实企业系统吗？

不是。随仓库 executor 使用生成/演示数据，应表述为工具协议和编排示例，不宣称接入真实公司业务。

### Q66：Agent State 与 AgentMessage 有什么区别？

State 是 AgentScope 持续推理所需的不透明 JSON，按 user/session/key 存储；AgentMessage 是产品展示历史，含 content/thinking/blocks/status。一个服务模型恢复，一个服务用户产品。

### Q67：上下文压缩与长期记忆有什么区别？

压缩是当前会话内降低上下文长度，保留近期窗口和旧内容摘要；长期记忆从对话判断/抽取/合并用户级信息，跨会话注入，受容量/冲突控制。

### Q68：默认 100k 字符预算怎样分层？

源码派生出约 50k trim 阈值、80k compact 触发、20k 近期保留、6k 摘要上限、1.5k 长期记忆成品上限。需要说明是字符启发式预算，不是 tokenizer 精确 token。

### Q69：MemoryFlushTool 为什么可以无参数？

它读取 RuntimeContext 中本轮 user/session 与 pending memory，触发记忆管道；参数不来自用户 JSON。无参数不等于无上下文依赖。

### Q70：AgentRunHandle 解决什么竞态？

complete/cancel/fail 可能由不同回调竞争。CAS 确保只有一个终态执行，finally 始终注销 StreamTask 并运行 gate/cache 等 release hooks。

### Q71：Agent 取消一定保存框架 interrupt checkpoint 吗？

不能无条件宣称。业务 finalizer 可证明 INTERRUPTED 消息/blocks 与资源释放；dispose/interrupt 顺序使框架 interrupt-save 是否每次发生仍是已记录边界。

### Q72：前端实时 tool start/end 怎样配对？

当前 payload/TS 不使用 toolCallId，按 name 从后往前找最近 running block（LIFO）。后端持久 AgentBlock 有 toolCallId，因此并发同名调用的实时 UI 仍有歧义空间。

### Q73：hint 会写数据库吗？

不会。hint 是当前 Agent SSE/前端时间线提示，刷新后消失；reasoning/answer/tool blocks 才随持久 assistant 保存。

### Q74：raw frames 是完整 Agent Trace 吗？

不是。它只记录本次浏览器已解析 SSE，最多 2000 条，切会话/刷新清空；不含后端所有模型上下文、State 或 RAG node timings。

---

## A.7 工程护栏、配置与真实性

### Q75：登录、角色、资源归属是一回事吗？

不是。Sa-Token 检查登录，UserContext 提供身份/角色，服务/Mapper 以 userId 限制会话与任务 owner；admin 角色检查当前只明确出现在用户管理四处。

### Q76：前端 `/admin` 守卫能保护 API 吗？

不能。RequireAdmin 只做客户端导航与菜单隐藏。后端权限必须有拦截器、注解、显式 checkRole 或 owner 查询。

### Q77：`@IdempotentSubmit` 能防完整 SSE 重复运行吗？

不能。切面只覆盖 Controller 同步返回 SseEmitter 前的短窗口；当前 eval.enabled=true 还会绕过。AgentRunGate 才覆盖完整 Agent 流。

### Q78：为什么项目需要多种 Redis 并发机制？

防重锁、上传许可、全局公平队列、Agent per-user gate、task cancel 分别保护不同对象和窗口；不能用一个“分布式锁”概括。

### Q79：`unique-name` 是多租户吗？

不是。它主要拼接 application/MQ topic/group，避免多套实例消息命名冲突；没有统一改变 DB、bucket、全部 Redis key 与权限边界。

### Q80：Schema 会随应用自动创建吗？

不会从冻结接线推出。仓库提供 SQL，README 用 psql 执行；没有 Flyway/Liquibase/spring.sql.init。表/extension 未建会在初始化或业务查询失败。

### Q81：为什么默认 pgvector，Milvus 注解却 `matchIfMissing=true`？

matchIfMissing 只在键缺失时生效；仓库 YAML 显式 `rag.vector.type=pg`，因此 PG 条件成立、Milvus 条件不成立。

### Q82：AI provider 配置存在是否表示 key 有效？

不表示。结构校验能确认 provider/url/endpoint 引用，key 和网络真实可用性通常在调用期暴露；settings 页只返回掩码或 configured 布尔。

### Q83：为什么 Rerank 开启也可能没有真实分数？

候选路由最后有 noop client，真实供应商失败时 noop 只截断不打分。Evidence Gate 遇到无分整批会 warning 并放行。

### Q84：你跑过项目吗？

按用户设定应诚实回答：本教程目标是源码级熟悉，不以复现为目标；已有聚焦 hermetic 测试只作辅助证据，不能声称完整集成/真实问答已运行。随后把话题转回你能精确解释的调用链与边界。

### Q85：你在这个项目里具体做了什么？

只说可由 diff/文件证明的工作：项目身份/首页/前端品牌、上游归属与 CI 分层，以及源码教程/证据地图。核心 RAG/Agent 能力来自上游，应说“深入掌握”，不说“从零实现”。

### Q86：如果让你下一步改造，选什么？

可选：SSE 可恢复协议、live toolCallId、Agent cancel checkpoint、派生索引重建、配置契约/维度校验、固定检索评测集。必须用未来时，并给验收证据。

### Q87：项目最大边界是什么？

没有唯一答案，但至少可说：默认只开向量通道；知识文档通用 Pipeline 尚未接主链；RAG 断线/重试不是 resume；Agent 取消 checkpoint 有顺序边界；前端 admin 不等于统一后端授权；无真实运行/性能/质量数据。

### Q88：如何证明你真的读过源码？

主动讲一个 README 无法给出的边界，例如：

- Milvus matchIfMissing 与 YAML pg 的优先级；
- LightRAG 注释的 ingestion.enabled 未接线；
- RAG cancel 后前端停止后缀刷新消失；
- Agent 持久 toolCallId 与 live name-LIFO 的差异；
- `done` 与业务 finish/cancel 的区别。

---

## A.8 压力追问：一句话不能答完的问题

### Q89：项目是否高可用？

不能整体下结论。可以逐层说局部机制：模型候选 fallback、单检索通道降级、Redis 跨节点 cancel、MQ 异步、初始化 fail-fast；同时说明对象存储/Redis/PG 等默认单点拓扑和无运行数据，不能据此宣称系统级高可用。

### Q90：项目是否强一致？

不是全局强一致。PostgreSQL 本地事务内有强边界；对象存储用补偿；事务消息协调状态与异步触发；ES/LightRAG 是 best-effort 派生写。必须按数据 owner 回答。

### Q91：项目是否 exactly-once？

不能宣称。事务消息、业务状态和唯一键降低部分重复风险，但三个实际 Consumer 未使用通用 `@IdempotentConsume`；SSE retry 还是新请求。应说每个窗口的幂等策略。

### Q92：为什么不把所有状态放 Redis？

Redis 适合短生命周期协调与跨节点信号，业务历史、State、Trace 和知识事实需要持久查询/约束/审计，放 PostgreSQL。进程态 emitter/cancel handle 也无法简单序列化成可靠业务事实。

### Q93：为什么 Agent 要保存业务 blocks，还要保存框架 State？

blocks 服务产品回放，State 服务模型继续运行；业务 blocks 是 lossy projection，不包含框架全部消息与内部元数据，State 又不适合直接展示。

### Q94：为什么不直接用 LLM 判断所有意图、参数、记忆？

LLM 用于语义判断，但系统仍需要闭集约束、Schema 校验、规则兜底、容量/冲突控制和确定性终态。模型输出不是权限或状态机的 owner。

### Q95：如果单通道超时后底层还在跑，会有什么风险？

占用线程/连接并产生迟到副作用或日志；当前 `orTimeout` 只让上层不等结果。改进需要通道 API 返回可取消 handle 或底层 client 响应 cancellation，而不是只缩短 future timeout。

### Q96：如果模型首包后失败，为什么不切模型续写？

无法保证第二模型知道已输出边界、引用编号和语义计划，拼接可能自相矛盾。当前选择一致性优先，失败收尾而非无缝续写。

### Q97：为什么图谱单实例难做知识库隔离？

LightRAG workspace 是服务实例级，请求没有 per-request workspace；源码只能按返回 file_path 做结果归属过滤。真正子图隔离需要多实例/服务端能力，不是当前 client 参数能解决。

### Q98：为什么配置校验不是越多越好？

只应 fail-fast 于确定的结构矛盾。外部服务可选且有降级策略时，过度启动探活会让可选依赖变成强依赖。AsterRAG 对 Redis/Storage 与 MCP/Web/LightRAG采取不同策略就是这种权衡。

### Q99：怎样设计一套检索评测？

准备固定 query、相关 Chunk judgment 与知识库版本；测 recall@K/MRR/nDCG、作用域命中、citation correctness，并记录配置/模型/索引版本。回答质量再单独人工或 LLM-as-judge，但不能把合同阈值当已有结果。

这是一组设计选项，不代表配套评测器已实现所有指标。已有实现和公式演算见[第 26～31 章](../docs/26-evaluation-overview.md)，其中当前文档 Hit/Recall/MRR 与 RAGAS 的分工见第 29、30 章。

### Q100：面试结束前你希望面试官记住什么？

不是“我用了很多中间件”，而是：

> 我能把一个复杂开源 Agentic RAG 项目还原为三条主链和清晰状态 owner；能从配置证明默认拓扑，能准确讲 normal/reject/cancel/error，能区分上游能力、个人改造和未来推演。这是我把开源项目真正转化为工程理解的部分。

---

## A.9 自测评分

每题按 0～3 分：

- 0：不知道；
- 1：只会说技术名词；
- 2：能说主链和一个边界；
- 3：能说 owner、顺序、状态、失败、取舍和源码锚点。

建议门槛：

| 题组 | 目标 |
|---|---:|
| Q1～Q10 架构 | 至少 24/30 |
| Q11～Q24 写路径 | 至少 32/42 |
| Q25～Q56 RAG | 至少 72/96 |
| Q57～Q74 Agent | 至少 42/54 |
| Q75～Q100 工程/压力 | 至少 60/78 |

低分时不要继续背更多题，回到对应正文沿真实方法重新走一遍。
