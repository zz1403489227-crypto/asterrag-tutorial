# AsterRAG 教程开发进度

> 工作区：私有远程教程工作区  
> 当前阶段：全部完成  
> 最后核验：2026-09-10（本地静态文档检查）

## 状态摘要

- P0 建立计划与冻结边界：**完成**。
- P1 源码普查与事实地图：**完成**。
- P2 总体架构章与全书骨架：**完成**。
- P3 知识写路径源码导读：**完成**。
- P4 RAG 请求与记忆源码导读：**完成**。
- P5 Agent 与工程保障源码导读：**完成**。
- P6 配置组装、设计推演与面试材料：**完成**。
- P7 全书连贯性与发布前审计：**完成**。
- 当前阻塞：无。用户已明确不要求运行或复现项目，后续不搭建专属集成环境。

## 已完成

### 2026-09-01：计划与版本边界

- 创建 `TUTORIAL_DEVELOPMENT_PLAN.md`，规划第 0～20 章和 P0～P7 执行阶段。
- 明确事实权威顺序：冻结源码与真实验证高于项目说明、作者教程和外部教学参考。
- 明确教程目标源码为 AsterRAG `98894c2c42c015a3c874c6b3c986ac863c85b731`。
- 记录作者课程以 Ragent `1.0.0` 为主要版本参考，而 AsterRAG 当前实现已经继续演进。

### 2026-09-01：P0 源码冻结

- 冻结 `sources/AsterRAG` 到 detached HEAD `98894c2c42c015a3c874c6b3c986ac863c85b731`。
- 冻结 `sources/ragent-upstream` 到 detached HEAD `1cb684ed5df03f241d90c836466465f6aab37800`。
- 核对 Ragent `1.0.0` tag 为 `5500546c4e4742752adaaebf51c9423bef5f3497`。
- 冻结 `sources/how-claude-code-works` 到 detached HEAD `f4d6505ed9162a0ee6be089190f74c419ecacb19`。
- 三个工作树均为干净状态；详细 commit/tree/URL 见 `evidence/SOURCES.lock.md`。
- 创建 `docs/`、`assets/`、`scripts/`、`evidence/runtime/` 和 `evidence/reviews/` 目录。

### 2026-09-01：P1 源码普查与事实地图

- 完成 `evidence/source-census.md`：7 个 Maven 模块、664 个主 Java 文件、77 个测试文件、24 个 Controller、19 个配置类、31 张表以及默认配置矩阵。
- 完成 `evidence/test-matrix.md`；明确测试文件/方法存在不等于已执行通过。
- 完成 `evidence/call-chains.md`：知识文档入库、确定性 RAG、ReAct Agent 三条主调用链及其正常、拒绝、取消、失败和持久化边界。
- 修正入库主线：知识文档当前使用 RocketMQ 触发的固定五步 `DefaultIngestionKernel`；`/ingestion/tasks` 是独立通用子系统；知识文档 `ProcessMode.PIPELINE` 当前明确暂停。
- 完成 `evidence/architecture-node-map.md`，为总体图每个节点登记 owner、输入、输出、状态、正常路径、失败边界和源码锚点。
- `evidence/source-map.csv` 当前登记 41 条论断：39 条 `verified-source`、2 条 `reference-only`。
- 完成 `evidence/reference-drift.md`：登记作者 1.0.0 课程与 AsterRAG 当前 7 模块、Boot 4.1.0、31 表、默认 Agent 档及入库/检索默认值的漂移。
- 更新 `evidence/reviews/open-questions.md`：Q-001、Q-002、Q-007 已由源码/参考对照关闭；Q-003、Q-004、Q-006 保留运行或依赖级核验；Q-005 仍开放。
- 运行 `scripts/verify-p1-evidence.sh`，三份源码锁、7 份 P1 证据文件、41 条 Source Map 路径和计划边界全部通过；输出见 `evidence/runtime/p1-static-2026-09-01.txt`。

### 2026-09-01：P2 总体架构章与全书骨架

- 完成 `assets/architecture/system-overview.mmd/.svg/.png`：第一章正式总体架构图，分离固定知识文档主链、独立通用入库子系统、确定性 RAG、ReAct Agent 和共享状态。
- 完成三张主时序图：`ingestion-sequence`、`rag-sequence`、`agent-sequence`；显式标注正常、拒绝、短路、取消、失败及未决证据边界。
- 完成 `state-ownership` 状态图：持久业务事实、对象、派生索引、Redis 协调态和进程态分层。
- 使用 Mermaid CLI 11.12.0 实际渲染 5 组 SVG/PNG，并完成视觉检查，详见 `evidence/diagram-qa.md`。
- 完成 `docs/00-03-detailed-outline.md`，按“证据契约→系统全局→模块/运行→状态所有权”建立前四章详细叙事合同。
- 完成 `docs/04-20-chapter-cards.md`，每章均登记总体图位置、上游输入、核心问题、源码入口、证据计划、取舍和下一章桥梁。
- 完成 `evidence/chapter-claim-map.csv`，41 条 Source Map 论断逐条分配到主章节/辅助章节，并覆盖第 0～20 章。
- 运行 `scripts/verify-p2-evidence.sh`：5 组图源/SVG/PNG、21 章骨架、关键边界和论断分配全部通过；输出见 `evidence/runtime/p2-static-2026-09-01.txt`。

### 2026-09-01：P3 知识写路径源码导读

- [x] 编写第 4～7 章正文并逐章完成源码卡片。
- [x] 执行知识写路径相关 Hermetic 测试并保存日志：两次 Maven 执行共 27 个用例，0 failure/error/skipped。
- [x] 沿上传→分块→索引调用链讲清对象、业务表、Chunk、向量和可检索性的区别。
- [x] 补齐 RocketMQ 全仓使用点、事务回查和默认启动依赖边界；不再要求真实 Broker 复现。

正文交付：

- `docs/04-document-entry.md`：上传限流、对象与元数据双写、远程 URL、定时刷新相位机和失败窗口。
- `docs/05-parsing.md`：MIME/Profile 双键路由、Parser 注册与回退、结构化 Block、各格式解析路径和 provenance 边界。
- `docs/06-ingestion.md`：RocketMQ 事务消息、固定五步内核、业务失败与消息重试边界、独立通用 IngestionEngine 及当前未闭合路径。
- `docs/07-chunking-and-indexing.md`：结构感知分块、展示/向量双文本、VectorTarget、多落点写入、一致性矩阵和 SUCCESS 的准确含义。

四章共 1401 行；每章均包含责任边界、设计解读、面试追问、源码定位卡和读后自检。测试记录只作为辅助理解证据，没有继续扩建运行或复现环境。

### 2026-09-01：P3 环境与 Hermetic 基线

- 宿主默认 Java 11 与项目 Java 17 要求不匹配；建立 `runtime-work/AsterRAG` 同 commit 工作副本，并使用 `maven:3.9.11-eclipse-temurin-17` 和独立缓存卷执行测试。
- `RocketMQProducerAdapterTest` 4 个用例全部通过；`ChunkingFixtureTest`、`IngestionSpecCodecTest`、`ScheduleRefreshProcessorTest`、`RemoteFileFetcherTest`、`IngestionTaskServiceImplTest`、`IngestionEngineTest` 共 23 个用例全部通过。
- 完成 `evidence/p3-hermetic-test-report.md`、`evidence/p3-environment-census.md` 和 `evidence/mq-census.md`；Q-005 更新为 `resolved-source-dependency`。
- 测试中的 `broker unavailable`、`boom` 和 `heartbeat rejected` 是用于验证失败分支的预期注入；Maven 两次均以 0 退出并报告 `BUILD SUCCESS`。

### 2026-09-01：目标边界调整

- 用户明确教程用于深入理解项目和应对面试，不会自己运行项目。
- 停止计划中的专属集成环境、真实上传/召回复现和故障注入；不把证明项目正确作为交付目标。
- 已有 27 个聚焦测试结果保留为辅助证据，教程正文以责任、调用链、状态、失败语义、设计权衡和面试追问为主。
- `TUTORIAL_DEVELOPMENT_PLAN.md` 升级为 v1.1，第 19～20 章、章节模板、P3～P7 与验收门槛已同步改为学习/面试导向。

### 2026-09-01：P4 确定性 RAG 读路径

- [x] 编写第 8～13 章正文并逐章完成源码卡片。
- [x] 沿 `/rag/v3/chat` 追踪 SSE、并发闸门、取消、会话记忆、查询改写、意图与作用域。
- [x] 明确 HTTP/流生命周期、持久消息/摘要、进程任务和 Redis 协调态的所有权差异。

正文交付：

- `docs/08-request-sse-lifecycle.md`：同步防重与业务限流边界、公平 Ticket 状态机、SSE 终态、跨节点主动停止及当前 RAG 断线取消接线边界。
- `docs/09-memory-and-rewrite.md`：三张会话表、8 轮原文+增量摘要、USER 先落库、术语归一化、LLM/规则改写与三份问题。
- `docs/10-intent-and-scope.md`：闭集意图树、数量/分数约束、路径歧义确认、SYSTEM-only 短路、global/directed/supplement scope。
- `docs/11-multi-channel-retrieval.md`：20/40/10 预算、多级并发、四通道组装条件、局部超时、主/补配额与原始分数量纲。
- `docs/12-retrieval-postprocessing.md`：去重、RRF、40→10 候选漏斗、真实/Noop Rerank、批级 Evidence Gate 和最终元数据回表。
- `docs/13-answer-generation-and-trace.md`：来源唯一编号、引用/docId 边界、grounding、结构化 Prompt、首包前模型 fallback、三路流式终态和 Trace 时间语义。

六章共 2519 行。源码复核中新增四项必须显式讲解的当前边界：RAG emitter 断线未显式接到 `StreamTaskManager.cancel`；通道 `orTimeout` 只放弃迟到结果、不取消底层任务；首包提交后不再跨模型 fallback；当前显式取消链没有证明顶层 `rag-stream-chat` Run 一定收尾。

## P5：Agent 与工程保障源码导读（已完成）

- [x] 完成 `docs/14-agent-vs-workflow.md`：配置装配、RunGate、副作用顺序、ActiveAgent 重建、ReAct 循环、RAG Tool 窄口、maxIters/maxAttempts 和取消接线。
- [x] 冻结核对 `io.agentscope:agentscope-core:2.0.2:sources` 的循环语义，记录于 `evidence/agentscope-2.0.2-source-note.md`；未把依赖中的未接线能力扩写成项目能力。
- [x] 完成 `docs/15-agent-tools.md`：ResolvedCatalog 快照、三类工具契约、MCP 双重门控、Knowledge Search 窄口、无参记忆工具、MCP bridge 与错误标准化。
- [x] 区分两套 MCP 参数控制流：Workflow 的独立 LLM 提参三态，与 Agent 的原生 ToolUse + JSON Schema 校验；未把 NEED_CLARIFICATION 错套到 Agent 路径。
- [x] 明确随仓库提供的天气、工单、请假、资产和销售工具使用生成的演示数据；不宣称接入真实企业系统。
- [x] 完成 `docs/16-agent-state-memory-finalization.md`：业务消息、AgentScope State、RuntimeContext、上下文两级减负、长期记忆事务管道、事件投影与三路收尾。
- [x] 明确当前取消接线只能证明业务 INTERRUPTED 轨迹的 finalizer；因 dispose 先于 interrupt，不无条件宣称每次取消都走 AgentScope interrupt-save。
- [x] 说明当前 100k 字符预算导出的 50k trim、80k compact、20k 近期保留、6k 摘要和 1.5k 长期记忆成品上限。
- [x] 完成 `docs/17-engineering-guardrails.md`：登录/UserContext/资源归属、四种并发窗口、Redis 协调协议、事务消息、线程池、RAG Trace 与业务变更审计。
- [x] 明确当前 permission 列表为空、显式 admin check 仅见用户管理四处；`/admin` 路径名本身不构成角色授权。
- [x] 明确当前 YAML `eval.enabled=true` 会绕过提交防重，且 `@IdempotentSubmit` 即便开启也只覆盖 Controller 同步窗口；AgentRunGate 才覆盖完整 Agent 流。
- [x] 核对三个实际 RocketMQ Consumer 均未接入通用 `@IdempotentConsume`，不把未使用的基础设施写成当前消费保证。
- [x] 区分 RAG Trace 的执行诊断、BizChangeLog 的管理变更追责、业务消息的产品投影和 Agent State 的模型连续性。
- [x] 完成 `docs/18-frontend-state-and-evidence.md`：EngineGate、两套 hook/store、SSE 解析与新请求式重试、正常/拒绝/取消/失败/刷新投影、来源/反馈/推荐、Agent blocks 与管理 API 导航。
- [x] 明确前端临时 ID、当前连接事件、服务端持久消息三层 owner；停止提示、hint、raw frame 和 live duration 不冒充刷新可恢复事实。
- [x] 明确后端持久 AgentBlock 有 `toolCallId`，当前实时前端按同名工具 LIFO 配对结束事件；不把后端更丰富字段误写成前端已使用能力。
- [x] 明确 EngineGate 默认选 Agent，Agent meta 是身份探针不是完整运行证明，欢迎页 `DEMO_TURN` 是示例不是工具执行证据。
- [x] 明确客户端 `/admin` 守卫不等于后端管理 API 统一角色授权，系统设置页是掩码后的只读配置投影。
- [x] 沿 Agent 入口→运行闸门→ReAct→工具目录→状态/记忆→工程边界讲清动态主链。
- [x] 区分 RAG Pipeline、ReAct Runtime、MCP 工具、Agent State 和持久化会话的责任。

第 14～18 章共 3806 行。P5 已覆盖动态 Agent 主链、工具契约、状态/记忆、横切护栏与前端事件投影；没有以运行复现或页面截图替代源码契约分析。

## 已完成：P6 配置组装、设计推演与面试材料

- [x] 完成 `docs/19-configuration-and-failure-reasoning.md`：四级配置证据、默认装配拓扑、两进程边界、存储/向量/检索/模型/MCP 选择与源码故障推演树。
- [x] 明确 Java 字段兜底 workflow 与随仓库 YAML 默认 agent、Milvus `matchIfMissing` 与显式 pg、后端 type 与 query enabled 之间的优先级。
- [x] 明确 Schema 不由主应用自动迁移，pgvector 维度必须在 YAML、Schema 与 embedding 输出三方一致；记录两处 HNSW 索引名的源码差异，不冒充运行结果。
- [x] 明确 Redis/对象存储默认 fail-fast，MCP/LightRAG/Web Search 采用不同降级语义，RocketMQ starter 的精确启动连接时机不在项目源码中武断推定。
- [x] 核对 YAML 注释提到的 LightRAG `ingestion.enabled` 未在冻结源码接线；当前 `type=lightrag` 即织入 best-effort 写同步，query enabled 只控制问答召回。
- [x] 完成 `docs/20-interview-narrative.md`：贡献四标签、通用回答结构、30 秒/2 分钟/5 分钟口述、三条主链、技术难点、故障推演和“为什么不用 X”。
- [x] 完成 `appendices/interview-question-bank.md`：100 道连续编号追问，覆盖架构、入库、记忆/改写、检索、SSE、Agent、护栏、配置和压力问题。
- [x] 完成 `appendices/glossary.md` 和 `appendices/source-index.md`：按 owner 解释易混术语，并从“要回答的问题”反向导航真实源码入口。
- [x] 完成根 `README.md`：21 章、3 份附录、5 组图和三条学习路线的全书导航。
- [x] 将 `docs/00-03-detailed-outline.md` 扩写为第 0～3 章正文；第 1 章嵌入并详细解释总体图、状态图和三张主时序图。
- [x] 建立配置选择表与故障推演树。
- [x] 生成架构口述模板、三条主链口述模板和分层追问题库。
- [x] 面试回答明确区分上游能力、AsterRAG 当前实现、个人实际改动和未来设计推演。

## 已完成：P7 全书连贯性与发布前审计

- [x] `README + 21 章 + 3 附录` 共 25 份发布阅读文件，11,836 行；其中正文 10,711 行。
- [x] `scripts/audit-tutorial.py` 完成 692 项静态检查，0 failure，0 warning。
- [x] 21 章、3 附录、5 组 `.mmd/.svg/.png` 图、README 导航、Markdown fence 和本地链接全部通过。
- [x] 100 道追问精确为 `Q1..Q100`；41 条 Source Map 均可回到冻结源码，精确内联源码路径无缺失。
- [x] `verify-source-lock.sh`、`verify-p1-evidence.sh`、`verify-p2-evidence.sh` 全部 PASS；三份冻结源仓库仍位于预定 HEAD 且工作树干净。
- [x] 完成归属、受限参考、隐私/密钥样式、默认/可选/示例/未来能力和个人贡献语言审计。
- [x] 最终证据见 `evidence/reviews/final-audit.md`；结论 PASS。

## 2026-09-10：后端项目应用与基础追问增补

完成第 35～44 章，分成“项目怎么用”和“基础怎么答”两部分，正文约 2.4 万汉字。范围限定于简历中的 Java、Spring Boot、MyBatis-Plus、PostgreSQL、Redis、SSE 及必要的检索/外部服务边界。用一次问答、跨节点停止和删会话串联，不新增 RocketMQ 专项。

只读筛选面经库的 accepted、高质量记录，建立主题—项目章—基础章—公开题源对照；没有发布数据库或原题全集。补充 26 个源码定位条目、总体图与两张关键时序图，以及三组完整模拟追问。新的 Mermaid 图内嵌于 Markdown，未声称做过浏览器渲染验收。

发布前静态检查：后端增补 406 项、全书 1005 项、评测增补 105 项、检索增补 135 项，均无失败；全书无警告，git diff --check 通过。源码基线未改变，没有启动项目、查询运行数据库、调用模型或运行评测。详见 [审读记录](evidence/reviews/backend-supplement-review.md)。正文提交 `da29c0055d464540aeada8845948c24023b952ce` 已推送现有私有教程仓库 main，git ls-remote 与本地提交一致，核验时教程和产品工作树均干净。

## 证据纪律

- 源码中存在一个实现类不能单独证明它是默认路径；还要核对配置条件、注册关系和实际调用入口。
- 无源码支撑的设计动机必须明确写成“可以这样理解”或“从实现推断”，不冒充作者明示原意。
- 教程正文开始前，P1 的每个总体架构节点必须至少有一个冻结源码锚点。
- 每次修改本进度文件时，只记录已经由当前远程状态证明的进展。

## 2026-09-08：发布第 21～25 章检索与 Agent 增补

根据读者反馈重写 HNSW、ES/BM25、LightRAG、检索融合与 Agent 五章。用统一的差旅审批例子讲原理、建库、查询和工具循环；源码细节集中到附录 D。首页与原章节导航同步补齐。

本次发布来自已同步服务器的修订稿，产品源码基线未变，未运行真实项目或评测。静态复核只说明文档与源码定位一致，不代替学习效果判断。此前增补记录中的“尚未推送”是本次发布之前的历史状态。

## 2026-09-08：发布第 26～31 章评测教程

按用户追加要求，本提交纳入评测全景、评估集、双接口录制、确定性指标、RAGAS 裁判、诊断与面试六章，以及三组流程图、附录 E、来源索引和相关导航。

内容来自已同步服务器的教程稿，评测源码基准为 `9d69c63cdca0bf730d8900c3076e0480e541360c`。没有运行真实评测，没有发布原评测仓库源码或完整数据集。此前“先供审阅、尚未推送”的记录描述首次交付阶段，不代表本次发布范围。

## 2026-09-09：发布第 32～34 章可观测性与问题闭环

按用户追加的推送要求，本提交纳入 Trace/日志/指标、故障诊断与回放、监控与评测闭环三章，以及首页、章节导航、总计划、增补计划、教学审读和文档检查脚本。

三章来自已同步服务器的教程稿，参考面试题库的主题归纳，以同一道手机参数问题串联理想方案。没有运行项目、真实评测或模型裁判；没有上传原始数据库、原始题目集合或私有来源信息。项目已有 Trace 机制与未来设计明确区分，示例不充当真实日志或评测成绩。

写作阶段本地和服务器文档检查均为全书 895 项、检索增补 135 项、评测增补 105 项通过；发布阶段复核同样检查。此前“未推送”属于初次交付阶段，本次发布仅包含教程材料。
# 2026-09-11：学习问答整理入库

- 新增第 45 章，归纳用户身份、Redis 运行槽、运行句柄收尾、SSE、Spring Boot/Maven 五组学习问答，并补入 token 传递和用户级并发的追问解释。
- 按一次具体请求串联数据流、状态所有者、正常与异常出口；提供总时序图、协议示例、版本对照和自测问答。
- 主实现继续冻结在 AsterRAG `98894c2c42c015a3c874c6b3c986ac863c85b731`；上游 `ca93991abe4ffd838e48d600d7ada24e010a884f` 只作五个文件的差异对照，没有更新产品代码。
- 修订点：UserContext 不保存浏览器 token；主流互斥不覆盖全部异步记忆任务；CAS 是单句柄至多一次收尾；落库内部返回 null 后仍可能发 finish/done；区分两版的错误收尾、重试、confirm 与 block；补正默认端口及 Maven 插件启用边界。
- README 与第 36、38、39 章加入入口；第 39 章补充具体落库失败语义。新增源码核对记录和 28 项文件/行号/SHA-256 锚点。
- 验证：已有 `audit-backend-supplement.py` 为 412 项检查、0 失败；本次 8 个内容文件的链接、锚点、围栏、敏感路径与源码哈希检查为 219 项、0 失败；`git diff --check` 通过。此记录在上述内容检查后补入。
- 产品冻结源码工作树保持干净；未执行应用构建、产品测试、登录请求、模型调用、数据库写入或故障实验。检查结果仅说明文档与读取的静态源码相符。
