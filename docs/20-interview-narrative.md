# 第 20 章：如何把源码理解讲出来——设计推演与面试叙述

> 当前推荐：以 Agent / RAG 为主要面试方向时，优先使用 [第 25 章的简历、30 秒与两分钟叙事](25-agentic-rag-interview-focus.md)，并用 [第 21～24 章](21-hnsw-vector-index.md) 支撑检索追问。本章保留原有完整工程叙事作为备查；Redis、RocketMQ 等不必成为开场重点。

> 面试官判断你是否真正理解一个项目，不靠你能背多少类名，而靠你能否稳定回答五件事：系统解决什么问题，核心调用链怎样走，状态由谁保存，失败时会发生什么，为什么选择这种设计以及它还存在哪些边界。
>
> 本章不是“标准话术大全”。同一句话必须能回到前 19 章的冻结源码；上游已有实现、AsterRAG 当前改造、你的源码理解和未来设想必须分开。你不需要声称自己复现过系统，更不能虚构性能、用户量或生产事故。你的可信度来自对 owner、顺序、终态和边界的精确掌握。

## 20.1 面试目标：证明“我能解释系统”，不是假装“我从零原创”

AsterRAG 的 README、NOTICE 与 `docs/UPSTREAM.md` 已明确：它基于 Apache-2.0 的 `nageoffer/ragent`，不是从零原创；完整上游历史和归属仍保留。

冻结 fork 相对上游基线有三个提交，diff 主要覆盖：

- AsterRAG 项目身份、README、Banner、NOTICE、UPSTREAM 边界；
- 前端可见品牌与项目链接；
- CI 分层，把 hermetic 测试与需要外部依赖的集成套件区分开。

核心 RAG、Agent、状态、记忆、检索和入库能力来自上游。最可信的开场不是回避这一点，而是主动说明：

> 这是我基于 Apache-2.0 开源项目做的学习与二次整理项目。核心 RAG/Agent 实现来自上游，我保留了历史和 NOTICE。我的工作重点是建立自己的项目身份与 CI 边界，并对冻结源码做系统性拆解：从总体架构、三条调用链、状态所有权、失败终态一直跟到配置装配。面试中我只把实际 diff 范围说成自己的改造，其他能力按“我掌握并能解释的上游实现”来讲。

这段话有三层价值：

1. 归属诚实，面试官不需要先花时间戳穿“从零写了几万行”；
2. 立刻把评价重点转到你的源码深度；
3. 给后续所有追问建立事实边界。

### 20.1.1 四种陈述标签

建议在脑中给每个回答贴标签：

| 标签 | 句式 | 证据 |
|---|---|---|
| 上游能力 | “上游源码实现了……” | 上游已有 commit/path |
| AsterRAG 当前实现 | “冻结版本当前默认……” | 当前 YAML、条件 Bean、Schema、调用点 |
| 我的改造/产出 | “我实际修改/整理了……” | `upstream/main..main` diff、教程文件、提交 |
| 设计推演 | “如果继续演进，我会……” | 明确是假设，说明取舍与验证方法 |

不能把第四类用过去式说成已经完成，也不能把第一类改成“我设计并实现了”。

---

## 20.2 一套回答骨架：结论 → 主链 → 状态 → 失败 → 取舍

面对任何项目问题，都可以用同一五步骨架：

```text
1. 结论：一句话回答问题，不绕术语
2. 主链：入口 → 核心 owner → 输出
3. 状态：哪些持久、哪些派生、哪些进程内
4. 失败：最关键的失败窗口和终态
5. 取舍：为什么这样做、没有解决什么
```

例如“这个项目的 RAG 有什么特别？”：

> 它不是把向量检索结果直接塞给模型，而是把问题理解、作用域、多通道召回、融合、Rerank、证据门和引用拆成明确阶段。请求从 `RAGChatController` 进入，经全局排队和 Trace 后由 `StreamChatPipeline` 加载记忆、保存 USER、改写并解析意图，再交给 `MultiChannelRetrievalEngine`；结果按去重、RRF、Rerank、证据门、元数据回表收窄，最后才生成回答和 sources。会话消息与 Trace 在 PostgreSQL，运行任务和并发协调在 Redis/进程态。单通道失败按空结果降级，但模型首包发出后不再跨模型 fallback；失败路径不持久化一条虚假的 assistant error。这个设计提升了可解释性和局部降级能力，代价是阶段和状态更多，需要严格的终态与 Trace 约束。

这比“用了 pgvector、RRF、Rerank、SSE”更像真正读过源码，因为它有顺序、owner 和边界。

---

## 20.3 30 秒项目介绍

适合面试官刚看到简历、只问“简单介绍一下”：

> AsterRAG 是我基于 Apache-2.0 开源 Ragent 学习和整理的 Agentic RAG 项目。我重点研究外层 AgentScope ReAct 如何调用知识、记忆与 MCP 工具，以及知识工具内的检索和合成链。检索方面包括默认 pgvector HNSW，以及可选的 ES/BM25 和 LightRAG 如何补充证据，再经 RRF、精排与证据门收窄。核心实现来自上游，我的重点是源码级分析与教程产出，不把尚未做过的功能开发或效果调优说成自己的成果。

30 秒里不要塞：

- 31 张表的全清单；
- 20 个配置数值；
- 所有中间件名；
- 未经运行证明的性能和“高并发”结论。

短介绍的目标是让面试官知道下一步可以追问哪三条链。

---

## 20.4 两分钟架构介绍

两分钟版本按“入口—三条链—共享状态—默认配置—边界”组织：

> 前端有 Workflow 和 Agent 两套独立 hook/store，后端 `/rag/settings` 决定默认进入哪套；随仓库 YAML 默认是 Agent，但确定性 RAG HTTP 入口仍存在。
>
> 写路径从知识文档上传开始。上传只把原件放到 S3 兼容存储并写 PENDING 元数据；显式开始分块后，通过 RocketMQ 事务消息切 RUNNING，由 Consumer 调固定五步 `DefaultIngestionKernel`：识别 MIME、结构化解析、分块、Embedding、索引替换。Chunk 关系数据和向量是不同落点，默认向量后端是 PostgreSQL/pgvector。源码里另有通用 IngestionEngine，但知识文档的 PIPELINE 模式当前明确暂停，不能混为默认主链。
>
> 确定性读路径从 `/rag/v3/chat` 进入，先走全局公平限流和 Trace，再加载会话记忆并保存 USER；问题改写后解析意图和知识库作用域，默认只启用向量通道，可选 ES、LightRAG、Web Search。多路结果不直接拼接，而是去重、RRF、Rerank、证据门和元数据富化，再生成带 source index 的回答。正常、拒绝、取消和失败有不同 SSE/持久化终态。
>
> Agent 路径从 `/agent/v1/chat` 先抢每用户 RunGate，再创建/恢复会话与 task，AgentScope ReAct 根据工具目录动态调用 `search_knowledge`、记忆工具或 MCP。它不复制检索，而是通过 KnowledgeSearchFacade 复用 RAG 核心。AgentScope State、产品消息、上下文压缩和长期记忆由不同表/组件负责，最终由 AgentRunHandle 保证 complete/cancel/fail 三出口互斥收尾。
>
> 共享基础设施方面，PostgreSQL 保存业务事实和 Agent State，Redis 做 ID 与跨节点协调，对象存储保存原件，RocketMQ承载三类异步动作；RAG Trace、变更审计和前端 raw frames 是三种不同证据。配置上默认 Agent + pgvector + S3，只开向量通道；“代码支持”与“默认启用”必须通过条件 Bean 和运行期开关区分。

这段口述的关键不是一字不差背诵，而是每一段都能被打断追问。

---

## 20.5 五分钟白板：先画 owner，再画技术名词

在白板上按下面顺序画，避免一上来堆 Redis、MQ、PostgreSQL 图标：

### 第一步：画三个入口与三个目标

```text
文档/URL ───────────────→ 可检索证据
用户问题 ───────────────→ 带来源的确定性回答
用户任务 ───────────────→ Agent 动态行动与回答
```

### 第二步：补核心 owner

```text
文档 → KnowledgeDocumentService → MQ Consumer → DefaultIngestionKernel → Sinks

问题 → RAGChatService → StreamChatPipeline → RetrievalEngine → LLM → EventHandler

任务 → AgentChatService → ReActAgent → AgentToolCatalog → AgentRunHandle
```

### 第三步：补共享状态，不要把所有线都画到一个 DB

```text
PostgreSQL：会话/消息/知识/Chunk/Trace/Agent State/Memory/pgvector
对象存储：源文件与资产
Redis：ID、gate、queue、cancel、semaphore、init lock
进程态：SSE emitter、ActiveAgent cache、raw callback
RocketMQ：异步触发，不是持久业务事实的唯一 owner
```

### 第四步：用虚线画可选能力

```text
ES keyword       （默认 type=none）
LightRAG graph   （默认 type=none）
Web Search       （默认 disabled）
MCP Server       （连接失败跳过远程工具）
Milvus           （实现存在，默认 YAML 选 pg）
```

### 第五步：给三条链各标一个失败终态

- 写链：对象/元数据已在，但解析/索引失败，文档状态 ERROR；
- RAG：USER 已保存但生成失败，不伪造 assistant error；取消保存非空部分回答为 INTERRUPTED；
- Agent：complete/cancel/fail 经互斥 finalizer，失败不保存 assistant 失败消息。

白板画完后，面试官看到的是责任图，而不是依赖清单。

---

## 20.6 主链一：文档怎样变成可检索证据

### 20.6.1 一分钟口述

> 上传入口先经过分布式许可，`KnowledgeDocumentServiceImpl.upload` 校验知识库与摄取配置，把原文件写对象存储，再写 PENDING 文档元数据；上传成功不等于已经有 Chunk。用户显式开始分块后，事务消息把本地状态切到 RUNNING，Consumer 收到后调用 `runChunkTask`，当前 FIXED 模式进入 `DefaultIngestionKernel`。内核按 MIME/Profile 选择 Parser，输出结构化 Blocks，再用结构感知 Chunker 生成展示正文和 embeddingText，批量 Embedding 后由 `ChunkIndexWriter` 在事务中扇出到关系 Chunk Sink 和向量 Sink。完成后文档才变 SUCCESS。解析、Embedding、关系写或向量写任一异常都会进入 ERROR；对象文件、元数据、Chunk 与向量是不同事实，必须分别判断。

### 20.6.2 面试官继续追问时补四个点

1. 上传与开始分块分开：避免把网络接收、对象持久化和耗时解析绑在一个 HTTP 事务里。
2. 事务消息解决的是“本地状态切 RUNNING 与异步消息发送”的协调，不等于 Consumer exactly-once。
3. 固定五步主链与通用 IngestionEngine 并列存在；知识文档 PIPELINE 当前显式抛“重构中”。
4. Chunk 的 content 用于展示/引用，embeddingText 可带结构上下文用于向量化；二者不能完全等同。

### 20.6.3 “如果去掉这一层会怎样”

| 去掉 | 直接后果 | 深层问题 |
|---|---|---|
| 对象存储元数据分离 | DB 可能存大文件或无法独立流式读取 | 原件生命周期与业务状态耦合 |
| 结构化 Parser | 只得到扁平文本 | 表格/标题层级和 locator 丢失 |
| embeddingText | 只向量化局部正文 | 短 Chunk 缺少标题/父级语义 |
| MQ | HTTP 线程承担长解析 | 超时、重试和状态可见性更难 |
| 整文 replace | 新旧 Chunk 可能混存 | 重新摄取后的索引一致性难判断 |
| 分离的关系/向量 Sink | 难以同时服务管理展示与检索 | 向量库不适合承载全部产品元数据 |

这里的答案是设计推演；要说“会怎样”，不要说“我已经改过并压测”。

---

## 20.7 主链二：确定性 RAG 怎样生成可解释回答

### 20.7.1 一分钟口述

> `/rag/v3/chat` 进入后，提交防重只覆盖 Controller 同步窗口，真正长流先通过 `ChatQueueLimiter` 获取全局许可，再由 Trace runner 包住 Pipeline。`StreamChatPipeline` 创建或校验会话、加载 8 轮原文与增量摘要，并先保存 USER；随后做术语归一化、LLM/规则改写和意图解析。意图既能触发歧义引导或 SYSTEM-only 短路，也决定检索作用域是全库还是命中库加补充路。`MultiChannelRetrievalEngine` 默认执行 pgvector，其他通道按配置可选；结果依次去重、加权 RRF、候选截断、Rerank、证据门和元数据回表。之后 Prompt 把来源编号与证据注入模型，首包前支持候选 fallback，首包后锁定模型。EventHandler 累积回答，正常保存 NORMAL assistant 并发 finish/done，取消保存非空部分为 INTERRUPTED，失败只发错误并收尾 Trace，不保存虚假 assistant error。

### 20.7.2 为什么要先保存 USER

它让服务端拥有本轮提问的持久事实，后续失败或取消仍能回看用户问过什么；但也意味着异常后可能出现孤立 user 消息。前端临时 error assistant 刷新后消失，正好与这个后端语义一致。

### 20.7.3 多通道为什么不能直接拼接

不同通道的原始分数量纲不可直接比较：向量相似度、ES 分数、图谱/联网结果各有语义。项目先按稳定 key 去重，再用通道内排名做 RRF，随后才用统一 Rerank 模型重排。RRF 解决跨通道名次融合，Rerank 解决 query-document 相关性精排，二者不是重复。

### 20.7.4 Evidence Gate 为什么按整批最高分

它回答“这批证据里是否至少有可用证据”，不是逐条清洗器。最高真实 rerank 分低于阈值就整批丢弃；有一条过线则保留后续批次。真实 Rerank 降级为 noop 时没有分，Gate 选择 warning + 放行，避免在模型最不稳时把知识侧恒关掉。

### 20.7.5 三份问题不要混

```text
original question  → 展示、持久化、用户真实表达
main question      → 改写后的主要检索/回答问题
sub questions      → 扩充召回视角
```

改写服务改变检索表达，不应篡改历史里用户原话。

---

## 20.8 主链三：Agent 怎样动态行动又能收尾

### 20.8.1 一分钟口述

> `/agent/v1/chat` 首先由 `AgentRunGate` 按 user 抢完整运行位，在创建会话、保存 USER 和发送 meta 之前就拒绝重复运行。成功后创建 task、Emitter 和 `AgentRunHandle`，`ReActAgentProvider` 按人设内容与工具目录指纹取得或懒重建 ReActAgent。工具目录固定包含 `search_knowledge`，按长期记忆配置加入 `memory_flush`，再把意图树配置与 MCP 实际注册工具取交集。AgentScope 在 reasoning、tool call、observation、next reasoning 之间循环，`search_knowledge` 通过窄门面复用改写、意图、检索和同步答案合成，不复用完整 RAG SSE Pipeline。State 由 `PgAgentStateStore` 按 user/session/key 保存，业务消息、上下文压缩与长期记忆分别持久化。AgentStreamEventBridge 把框架事件投影成 message/tool/hint SSE 和持久 blocks；`AgentRunHandle` 用 CAS 保证 complete/cancel/fail 只收尾一次，finally 注销任务并释放 gate。

### 20.8.2 为什么先抢 gate 再创建副作用

如果先创建会话、保存 USER、发送 meta，再发现已有运行，拒绝请求会留下半轮业务事实。当前顺序把重复运行挡在所有这些副作用之前。

### 20.8.3 Agent State、业务消息和长期记忆为什么分开

| 对象 | 服务谁 | 内容 | 生命周期 |
|---|---|---|---|
| AgentScope State | 模型继续推理 | 框架不透明 JSON | 每会话持续，按 state key |
| AgentMessage | 产品/用户 | content、thinking、blocks、status | 会话历史 |
| Context Compaction | 上下文预算 | 摘要与覆盖边界 | 会话内逐步演进 |
| Long-term Memory | 跨会话个性信息 | 判断、抽取、合并后的记忆 | 用户级，受容量/冲突控制 |
| RuntimeContext | 本轮工具执行 | user/session/回调等 | 进程当前运行，结束清理 |

把它们合成一张 messages 表，会让模型恢复、产品展示、跨会话记忆和运行注入互相污染。

### 20.8.4 取消边界怎样诚实表达

当前业务 finalizer 能证明 cancel 会持久化部分轨迹为 INTERRUPTED、发 cancel/done 并释放资源。Agent dispose 与 interrupt 的具体先后存在第 16 章记录的边界，所以不要无条件声称“每次取消都成功保存 AgentScope 框架 checkpoint”。

---

## 20.9 五个真正值得讲的技术难点

### 难点一：异步写入的一致性不是一个事务解决

对象存储、PostgreSQL、RocketMQ、关系 Chunk、向量/ES/图谱属于不同系统。源码使用：

- 上传失败补偿删除对象；
- 事务消息协调本地状态与异步触发；
- 整文 replace；
- 关键词/图谱 best-effort 装饰器；
- 文档状态和日志暴露失败。

它没有伪装成全局 ACID。面试时价值在于说清每个一致性窗口，而不是一句“分布式事务保证一致”。

### 难点二：检索质量是漏斗，不是一个 TopK

默认预算是每通道 20、融合后最多 40 送 Rerank、最终 10 进 LLM。作用域、补充路、去重、RRF、Rerank、Evidence Gate 各解决不同问题。启动校验保证预算单调收窄，避免配置把漏斗倒置。

### 难点三：SSE 同时有业务终态与连接终态

finish/cancel/reject 带业务语义，done 只结束流。前端保留 fetch 等待取消 finalizer，而不是立刻 abort。正常、拒绝、取消、失败的消息持久化策略不同。理解这点才能解释刷新后的 UI 为什么变化。

### 难点四：Agent 动态性需要更强的边界

动态工具选择增加了：工具 Schema、目录快照、MCP 发现、同名冲突、RunGate、迭代上限、State 恢复、上下文压缩与三路 finalizer。Agent 不是把 RAG Controller 换个名字，而是新的执行架构。

### 难点五：默认能力必须从装配条件证明

项目有 Milvus/ES/LightRAG/Web/MCP，不代表默认都运行。第 19 章用 POM→YAML→条件 Bean→runtime enabled 四级证据还原默认 Agent + pgvector + 仅向量通道。

---

## 20.10 六个“去掉一层会怎样”的设计推演

### 20.10.1 去掉 Query Rewrite

短问题仍可检索，但指代、口语、省略和多问题混合会直接进入检索；历史记忆不能转化为自足 query，召回更依赖 embedding 偶然性。

### 20.10.2 去掉意图与作用域

所有问题全库检索，流程更简单，但无法利用知识库意图收窄，也失去歧义确认和 SYSTEM-only 短路。误路由风险下降的同时，噪声与成本上升。

### 20.10.3 去掉 RRF，只按原始分排序

不同通道分数量纲不可比，某一通道的数值尺度会支配结果。若只启用一个通道，RRF 价值有限；打开多通道后才是关键。

### 20.10.4 去掉 Rerank

仍可按 RRF 排名回答，但无法用统一 query-document 模型精排，Evidence Gate 也没有真实分数依据；当前配置校验会要求把 evidence floor 关掉。

### 20.10.5 去掉 AgentRunGate

同一用户可并发启动多个 ReAct run，可能争用同一会话 State、重复调用有副作用工具、混淆 task stop。Controller 短窗口防重不能替代完整 run gate。

### 20.10.6 去掉 finalizer，只依赖 callback 自觉清理

complete/cancel/fail 可能重复保存、重复发终态或漏释放 gate。`AgentRunHandle` 的 CAS + finally 把一次性收尾集中在一个 owner。

面试回答这类问题时，先说“项目当前层解决什么”，再说“去掉后的具体状态风险”，不要只说“性能会变差”。

---

## 20.11 怎样讲失败，不虚构生产事故

你没有运行项目，也没有真实事故数据，可以用“源码故障推演”而不是“我们线上遇到过”：

### 写路径推演

> 如果对象已保存但文档元数据插入失败，上传方法有补偿删除；如果消息发送/本地事务失败，事务消息不会进入正常消费；如果 Consumer 解析或索引失败，文档进入 ERROR 并保留可诊断日志。ES/LightRAG 同步是向量写后的 best-effort，失败不会回滚主向量，所以派生索引可能滞后。

### RAG 推演

> 单检索通道异常/超时按空结果继续，所有通道为空会在 LLM 前短路；模型候选在首包前可 fallback，首包后不再换模型；失败时 USER 可能已保存，但不会伪造 assistant 错误消息。取消只保存非空累计回答为 INTERRUPTED。

### Agent 推演

> 重复 run 在任何会话副作用前被 gate 拒绝；工具或模型错误最终走 fail finalizer，当前不保存 assistant 失败消息；取消持久化已追踪内容/blocks 为 INTERRUPTED，运行资源经 finally 释放。框架 interrupt checkpoint 不做超出源码的承诺。

推荐句式：

- “从异常分支看，首次可见点是……”
- “当前 finalizer 保证的是……”
- “这段源码没有证明……，所以我不会宣称……”
- “如果要验证，我会观察……，但本教程目标不包含复现。”

禁用句式：

- “我们线上曾经……”（没有发生过）
- “支持百万并发……”（没有数据）
- “召回率提升 30%……”（没有固定集与实验）
- “所有失败都会自动恢复……”（源码并非如此）

---

## 20.12 怎样回答“为什么不用某某技术”

面试官可能问 Kafka、向量数据库、微服务、LangChain、Spring AI。不要防御性地说“这个更好”，而要回到当前约束：

### 为什么默认 pgvector 而不是 Milvus

> 当前默认把关系事实和向量放在 PostgreSQL，降低学习/部署拓扑复杂度，并且共享表按 collection 过滤；仓库仍保留 Milvus 条件实现。数据规模、向量吞吐和独立扩缩容需求上升时，Milvus 才更有理由。源码选择是默认配置，不是宣称 pgvector 在所有场景都优于 Milvus。

### 为什么模块化单体而不是微服务

> 核心域在一个 Spring Boot 进程内，模块边界先约束依赖方向，减少分布式调用和部署成本；MCP Server 因协议与零内部依赖需要而独立。若团队/负载要求独立扩缩容，可再拆模型/摄取等边界，但当前七模块不应包装成七服务。

### 为什么 RocketMQ 而不是 Kafka

> 当前源码使用事务消息协调知识状态与异步触发，这是选型事实。是否换 Kafka 要看事务消息语义、团队运维、吞吐与消费模型；没有对比实验时不下绝对结论。

### 为什么不用框架自带全部 MCP 客户端

> 根 POM 将 MCP SDK 统一到 1.1.2，而 AgentScope 传递的是 0.17.0；源码明确禁止使用 AgentScope MCP 客户端，统一复用 rag 既有桥接，避免版本冲突和重复连接层。

---

## 20.13 怎样讲“我的改造”而不越界

如果只按冻结 fork 的真实 diff，推荐这样说：

> 我没有把上游核心能力说成原创。当前三项可核对改造是：第一，重做项目身份、README、前端可见品牌，并保留 LICENSE/NOTICE/UPSTREAM；第二，避免全局替换包名、API 路径和运行时 key，因为它们已是协议，优先保持上游 diff 与兼容性；第三，重构 GitHub Actions，把不依赖外部服务的 hermetic tests 作为默认 CI，将 Redis/PostgreSQL/Milvus/真实模型相关集成套件明确分层。除此之外，我完成了源码级架构和调用链教程，把版本漂移、默认装配和失败边界做成可核对证据。

如果面试官问“为什么不大改核心”：

> 当前优先目标是先证明我能完整理解系统，避免为了改而改。真正有价值的后续改造应该先有问题和验收证据，例如固定评测集、取消链一致性或配置契约；我不会把改名包装成算法创新。

### 20.13.1 只有满足三条件才说“我实现了”

```text
diff 中能找到
  AND 你能解释设计与边界
  AND 有相称的验证/证据
```

缺一项时改用：

- “我阅读并跟踪了……”
- “我能够解释……”
- “我做了设计推演……”
- “这是后续改造方向，尚未实现……”

---

## 20.14 面试官从 README 发难时怎样纠偏

README 为展示会压缩细节，教程必须能补边界。

### README 说“多通道召回”

补充：实现支持四通道，但冻结 YAML 默认只启用 pgvector；ES/LightRAG/Web 需要额外装配与开关。

### README 说“可编排入库 Pipeline”

补充：独立 `/ingestion/tasks` 子系统可按定义执行；知识文档默认主链仍是固定五步，`ProcessMode.PIPELINE` 当前显式暂停。

### README 说“模型故障转移”

补充：Workflow chat 首包前支持候选 fallback；首包后锁定。Agent 是固定单模型 + maxRetries，不复用 chat tier 的跨模型 fallback。

### README 说“全链路 Trace”

补充：RAG Trace 跟踪确定性 RAG run/node，不等于 Agent raw frames、业务审计或所有外部系统的分布式 Trace。

### README 说“工程验证”

补充：测试文件/CI 存在只证明验证入口；本教程不以运行项目为目标，也不声称完整集成环境已通过。

这种主动补边界不会削弱项目，反而证明你知道文案和实现的距离。

---

## 20.15 从类名问题回到架构问题

有时面试官直接问某个类。回答时先定位责任：

| 类 | 一句话责任 | 上游/下游 |
|---|---|---|
| `DefaultIngestionKernel` | 固定五步摄取内核 | 输入 IngestionSpec，输出索引替换结果 |
| `StreamChatPipeline` | 确定性问答业务编排 | 记忆/改写/意图/检索/生成 |
| `MultiChannelRetrievalEngine` | 并行通道和有序后处理 | SearchContext → RetrievedChunk |
| `StreamChatEventHandler` | RAG SSE 与消息持久化终态 owner | callback → finish/cancel/error |
| `ReActAgentProvider` | 按人设/目录指纹提供 Agent 实例 | Prompt/Tools/State/Middleware |
| `AgentToolCatalog` | 决定本轮 Agent 可见工具快照 | 本地工具 + MCP 交集 |
| `AgentRunHandle` | 三出口一次性 finalizer | complete/cancel/fail → cleanup |
| `PgAgentStateStore` | 按 user/session/key 保存框架 State | opaque JSON，不负责产品消息 |
| `ChatQueueLimiter` | RAG 全局公平排队与拒绝终态 | Redis limiter → pipeline/reject |
| `StreamTaskManager` | 跨节点任务 owner/cancel 协调 | Redis key/pubsub + 本地 cancel |

先答责任，再讲方法；不要从字段列表开始。

---

## 20.16 分层追问路线

完整题库在附录，这里给面试官常见递进：

### 第一层：是什么

- RAG 与 Agent 有什么区别？
- Chunk、向量、source 是什么关系？
- Agent State 和消息历史有什么区别？

### 第二层：怎么走

- 上传后什么时候真正可检索？
- 一次问题从 Controller 到 SSE finish 怎么走？
- 一次工具调用怎样从模型 ToolUse 到前端 block？

### 第三层：为什么

- 为什么要 Query Rewrite、RRF、Rerank 都保留？
- 为什么取消不直接 abort fetch？
- 为什么 Agent 需要完整 RunGate？

### 第四层：失败

- USER 保存后模型失败怎么办？
- 单通道超时是否取消底层任务？
- MCP Server 不可达会不会阻止主应用？

### 第五层：边界与演进

- 默认到底启用了哪些能力？
- 哪些状态不能跨进程恢复？
- 如果要把项目变成生产系统，先补什么证据？

你需要能从第一层一路答到第五层，而不是背 50 个互不相干的问答。

---

## 20.17 后续改造题：只能以未来时回答

可以提出的源码导向改进包括：

### 改进一：Workflow SSE 重试协议

当前前端重试是新 GET，无 Last-Event-ID，存在重复生成风险。可选方向：

- 服务端事件编号与短期 replay buffer；
- 客户端携带 lastEventId 恢复；
- 或明确禁用自动重试，只让用户重新发起。

需要验证 normal/cancel/error 和跨节点恢复，不能只加一个 header。

### 改进二：统一实时 toolCallId

后端持久 AgentBlock 有 toolCallId，前端 live tool event 当前按 name LIFO 配对。可把 toolCallId 加入 SSE payload 与 TS 类型，按 ID 闭合工具块，测试并发同名调用。

### 改进三：取消链的框架 checkpoint 证据

围绕 dispose/interrupt 顺序建立测试，明确 AgentScope interrupt-save 是否每次执行；再决定调整顺序或单独保存 checkpoint。

### 改进四：派生索引恢复

ES/LightRAG 写同步 best-effort，增加可重放 outbox/CDC 或“按关系 Chunk 重建派生索引”任务，并给出漂移检测。

### 改进五：配置契约清理

修正 LightRAG `ingestion.enabled` 注释/实现漂移，统一 PG HNSW index 名，增加 vector dimension 与 Schema 的启动检查。

### 改进六：评测闭环

作者已有独立的配套评测项目，完整机制见[第 26～31 章](26-evaluation-overview.md)。在它已有的文档指标与 RAGAS 基础上，可以进一步固定对照配置、增加所需的 nDCG/引用正确性或 Agent 轨迹评估；没有自己的对应记录前，不声称取得检索调优提升。

这些方向必须说“我会/可以”，除非未来真的有 commit 和证据。

---

## 20.18 回答不知道的问题

真正专业的回答不是永远有答案，而是知道证据到哪里结束：

> 这个点我在冻结源码里能确认到 A，但 B 由外部 starter/服务实现，当前没有第一手运行证据，所以我不会直接下结论。若要继续核验，我会看 C 的源码/日志/状态表。

示例：

> RocketMQ broker 不可达时，项目 adapter 的第一次发送一定会抛并上抛；但 listener container 精确在哪个 Spring 生命周期点连接 broker 属 starter 行为，我没有在项目源码里看到自定义保证，所以不说“一定在某行启动失败”。

这不是示弱，而是在展示证据纪律。

---

## 20.19 源码定位卡

### 项目归属与真实改造

- `README.md`
- `NOTICE`
- `LICENSE`
- `docs/UPSTREAM.md`
- `.github/workflows/ci.yml`
- Git range：`1cb684ed5df03f241d90c836466465f6aab37800..98894c2c42c015a3c874c6b3c986ac863c85b731`

### 三条主链入口

- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/controller/KnowledgeDocumentController.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/service/impl/KnowledgeDocumentServiceImpl.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/core/ingest/DefaultIngestionKernel.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/controller/RAGChatController.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/pipeline/StreamChatPipeline.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/MultiChannelRetrievalEngine.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/controller/AgentChatController.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/service/impl/AgentChatServiceImpl.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/config/ReActAgentProvider.java`

### 状态与收尾

- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/handler/StreamChatEventHandler.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentRunHandle.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentStreamEventBridge.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/state/PgAgentStateStore.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/web/StreamTaskManager.java`
- `resources/database/schema_pg.sql`

### 默认装配

- `bootstrap/src/main/resources/application.yaml`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/config/ConditionalOnAgentEngine.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/validation/RetrievalConfigEnvironmentPostProcessor.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/model/ModelSelector.java`

---

## 20.20 最终口述自检

不看教程，尝试完成下面任务：

1. 30 秒说清项目、归属和三条主线。
2. 两分钟说清架构，不把七模块说成七微服务。
3. 空白纸画总体图，并给每条箭头说出调用或数据流。
4. 从上传讲到可检索，准确说出上传成功与 SUCCESS 的区别。
5. 从 `/rag/v3/chat` 讲到 finish/done，说明四种终态。
6. 从 `/agent/v1/chat` 讲到工具与 finalizer，说明 RunGate 为什么在最前。
7. 列出 PostgreSQL、对象存储、Redis、MQ、进程态各自 owner 的状态。
8. 解释 RRF、Rerank、Evidence Gate 为什么不能合并成“排序”。
9. 解释 Agent State、业务消息、压缩摘要和长期记忆为什么分开。
10. 说出默认 Agent + pgvector + 单向量通道的四级配置证据。
11. 给一个 fail-fast 依赖和一个降级依赖，指出差异来源。
12. 用真实 git diff 说明自己的改造，不把上游核心说成原创。
13. 给三个未来改进方向，每个都说清需新增的验证证据。
14. 遇到项目源码无法证明的问题，用证据边界句式回答。

如果能稳定完成这 14 项，你已经具备应对大多数项目面试追问的结构。附录会把这套结构继续展开成分层题库、术语辨析与源码索引；它们是复习导航，不替代本章的整体叙述。
