# AsterRAG 源码级面试教程

> 学习目标：不以部署复现为目标，而是能从总体架构、真实调用链、状态 owner、失败语义和设计权衡五个层次，准确解释 AsterRAG 如何工作。

## 教程讲的是哪个版本

| 资料 | 冻结版本 | 作用 |
|---|---|---|
| AsterRAG | `98894c2c42c015a3c874c6b3c986ac863c85b731` | 唯一产品实现事实基准 |
| `nageoffer/ragent` 上游 | `1cb684ed5df03f241d90c836466465f6aab37800` | fork 来源与同源历史 |
| Ragent `1.0.0` | `5500546c4e4742752adaaebf51c9423bef5f3497` | 作者旧课程版本对照 |
| how-claude-code-works | `f4d6505ed9162a0ee6be089190f74c419ecacb19` | 只参考教学信息架构 |

完整资料锁见 [SOURCES.lock.md](evidence/SOURCES.lock.md)。

AsterRAG 基于 Apache-2.0 的 `nageoffer/ragent` 学习和二次开发。本教程保留上游归属，并在面试章中明确区分“上游能力、当前 fork 改动、个人理解和未来设计”。

## 一句话主线

> 一份文档怎样变成可检索证据，一次问题怎样经过理解、路由、检索、生成或工具调用，最终成为有来源、可追踪、可取消并能正确收尾的回答。

![AsterRAG 总体架构](assets/architecture/system-overview.png)

这张图的读法是：

```text
左侧写路径：Document → MIME/Parse → Chunk/Embedding → Index
                                      ↓
                              可检索证据合同
                                      ↑
中部 RAG： Question → Memory/Intent → Retrieval → Prompt/Model/SSE

右侧 Agent：Question → ReAct → Knowledge/MCP/Memory Tools
                                      ↓
                              State/Memory/Finalizer

底部 owner：PostgreSQL | Object Storage | Redis | Derived Index | Process/UI State
```

## 三条学习路线

### 30 分钟全景线

```text
0 → 1 → 3 → 20
```

目标：能画总体图，能说清三条主链、状态 owner、项目归属和当前边界。

### 核心 RAG 线

```text
0 → 1 → 3 → 4 → 5 → 6 → 7
          → 8 → 9 → 10 → 11 → 12 → 13
          → 17 → 19 → 20
```

目标：连通“原资料进入”和“有证据答案输出”，能解释每个中间状态和失败窗口。

### Agent 与工程深入线

```text
0 → 1 → 2 → 3 → 11 → 12
          → 14 → 15 → 16 → 17 → 18 → 19 → 20
```

目标：理解 ReAct 与固定 RAG 的边界，以及工具目录、AgentScope State、上下文压缩、长期记忆和三路收尾。

## 正文目录

### 第一部分：建立系统地图

| 章 | 问题 | 产物 |
|---|---|---|
| [第 0 章：怎么使用这份源码级教程](docs/00-reading-contract.md) | 一句话凭什么可信 | 冻结版本、证据等级、归属与阅读路线 |
| [第 1 章：总体架构与三条主调用链](docs/01-system-architecture.md) | 整个系统怎样流动 | 总体图、写/RAG/Agent 主链和失败收敛 |
| [第 2 章：模块边界、依赖与运行拓扑](docs/02-modules-and-runtime.md) | 代码和进程住在哪里 | 7 个 Maven 模块、2 个启动边界和四层配置证据 |
| [第 3 章：领域对象与状态所有权](docs/03-state-ownership.md) | 什么状态还在，谁能恢复 | 31 表领域地图、四类 owner 和关键生命周期 |

### 第二部分：沿知识写路径下钻

| 章 | 问题 | 产物 |
|---|---|---|
| [第 4 章：文档从哪里来](docs/04-document-entry.md) | 原文件/URL 怎样进系统 | 上传限流、对象/元数据、远程刷新和失败窗口 |
| [第 5 章：文档怎样变干净](docs/05-parsing.md) | 字节怎样变成结构化 Block | MIME/Profile 路由、Parser 注册、多格式与 provenance |
| [第 6 章：入库主循环](docs/06-ingestion.md) | 固定内核和通用 Pipeline 有什么边界 | RocketMQ、固定五步、单根链 Engine 和当前未接通点 |
| [第 7 章：从 Chunk 到可检索证据](docs/07-chunking-and-indexing.md) | 分块/Embedding/多落点怎样合作 | Chunk 不变式、展示/向量双文本、sink 一致性矩阵 |

### 第三部分：沿确定性 RAG 读路径下钻

| 章 | 问题 | 产物 |
|---|---|---|
| [第 8 章：请求、并发闸门与 SSE](docs/08-request-sse-lifecycle.md) | 请求怎样被接受/拒绝/取消 | Controller、limiter、task、emitter 和完整事件寿命 |
| [第 9 章：会话记忆、改写与拆分](docs/09-memory-and-rewrite.md) | 上下文怎样变成可检索问题 | USER 持久、摘要/历史、改写失败边界 |
| [第 10 章：意图、引导与检索范围](docs/10-intent-and-scope.md) | 哪些请求不该检索，又该查哪里 | guidance/system-only 短路与 KB scope |
| [第 11 章：多通道检索](docs/11-multi-channel-retrieval.md) | 子问题和通道怎样并行 | vector/keyword/graph/web 合同、超时和降级 |
| [第 12 章：检索后处理](docs/12-retrieval-postprocessing.md) | 异构候选怎样变成最终证据 | 去重、RRF、Rerank、证据门、富化和预算 |
| [第 13 章：回答生成、来源与 Trace](docs/13-answer-generation-and-trace.md) | 证据怎样变成回答并正确收尾 | grounding/prompt/model stream、sources、assistant 和 Trace |

### 第四部分：ReAct Agent 与工具

| 章 | 问题 | 产物 |
|---|---|---|
| [第 14 章：Agent 与 Workflow 的真实边界](docs/14-agent-vs-workflow.md) | 两种编排模型如何分工 | engine 选择、RunGate、Provider 与 ReAct 入口 |
| [第 15 章：Agent 工具系统](docs/15-agent-tools.md) | 知识、MCP 和记忆工具怎样进入目录 | Catalog、工具合同、MCP 交集和 Knowledge Facade |
| [第 16 章：Agent State、Memory 与统一收尾](docs/16-agent-state-memory-finalization.md) | 动态循环怎样恢复并在三种终局释放 | State Store、Compaction、LTM、EventBridge 和 RunHandle |

### 第五部分：工程边界、配置与面试

| 章 | 问题 | 产物 |
|---|---|---|
| [第 17 章：工程保护网](docs/17-engineering-guardrails.md) | 认证、幂等、限流、审计和敏感信息如何横切 | owner/token/TTL、审计 vs Trace、后端授权边界 |
| [第 18 章：前端状态与证据](docs/18-frontend-state-and-evidence.md) | UI 怎样投影两套 SSE 协议 | hooks/stores、sources、blocks、刷新与示例数据边界 |
| [第 19 章：配置组装与故障推演](docs/19-configuration-and-failure-reasoning.md) | 某能力到底是存在、装配还是运行 | POM/YAML/Bean/分支四层证据和默认拓扑故障树 |
| [第 20 章：把源码理解变成面试叙事](docs/20-interview-narrative.md) | 怎样在 30 秒、2 分钟和 5 分钟讲清项目 | 口述模板、技术难点、追问、权衡和诚实边界 |

## 附录

| 附录 | 用法 |
|---|---|
| [附录 A：100 道分层面试追问](appendices/interview-question-bank.md) | 遮住答案口述，再核必答点和源码锚点 |
| [附录 B：术语表](appendices/glossary.md) | 快速区分名字相似但 owner/寿命不同的概念 |
| [附录 C：源码导航索引](appendices/source-index.md) | 从“想回答什么问题”反向找入口、主链和终局 |

## 图表索引

| 图 | 用途 | 源文件 |
|---|---|---|
| [总体架构](assets/architecture/system-overview.png) | 全书中央地图 | `assets/architecture/system-overview.mmd` |
| [知识入库时序](assets/diagrams/ingestion-sequence.png) | 上传/分块断点、MQ、五步内核和终态 | `assets/diagrams/ingestion-sequence.mmd` |
| [RAG 时序](assets/diagrams/rag-sequence.png) | 排队、短路、正常/取消/失败收尾 | `assets/diagrams/rag-sequence.mmd` |
| [Agent 时序](assets/diagrams/agent-sequence.png) | RunGate、工具、State 和三路 finalizer | `assets/diagrams/agent-sequence.mmd` |
| [状态所有权](assets/diagrams/state-ownership.png) | 持久事实、原对象、派生索引、协调态和进程态 | `assets/diagrams/state-ownership.mmd` |

## 每章的学习方法

```text
第 1 遍：看本章在总体图的位置和核心结论
第 2 遍：关掉教程，口述 5～10 个关键调用节点
第 3 遍：对每个副作用问 owner、寿命、失败和恢复
第 4 遍：用附录 A 的对应问题进行追问压测
```

掌握一章的标准不是背下所有类名，而是能完整说出：

1. 本章的 owner 是谁；
2. 输入、主顺序和产物是什么；
3. 哪一步首次产生外部副作用；
4. 持久事实、派生索引、协调态和进程态各是什么；
5. 正常、短路/拒绝、取消和错误如何收尾；
6. 哪些结论是源码事实，哪些只是设计推断。

## 证据与写作过程

`evidence/` 是教程的事实底座，不是读者必须从头阅读的第二本手册：

| 文件 | 回答的问题 |
|---|---|
| [source-map.csv](evidence/source-map.csv) | 每个核心论断的 commit/path/symbol 是什么 |
| [source-census.md](evidence/source-census.md) | 模块、文件、Controller、配置、测试和表的静态普查 |
| [call-chains.md](evidence/call-chains.md) | 三条主链的类/方法调用骨架 |
| [architecture-node-map.md](evidence/architecture-node-map.md) | 总体图每个节点的 owner、输入、输出与失败边界 |
| [reference-drift.md](evidence/reference-drift.md) | 作者旧课程/页面与冻结源码的版本漂移 |
| [test-matrix.md](evidence/test-matrix.md) | 测试类存在、聚焦测试和 Live/集成边界 |
| [diagram-qa.md](evidence/diagram-qa.md) | 5 张图的源文件、渲染与视觉检查 |

详细写作计划见 [TUTORIAL_DEVELOPMENT_PLAN.md](TUTORIAL_DEVELOPMENT_PLAN.md)，实际执行记录见 [PROGRESS.md](PROGRESS.md)。

## 最后的诚实边界

这份教程的主产物是对冻结源码的系统理解。它不宣称：

- 你亲自从零实现了上游 RAG/Agent 核心；
- 所有可选后端默认同时运行；
- 文档 SUCCESS 就保证所有问题召回；
- 单元测试通过就等于集成环境、浏览器路径和生产质量全部通过；
- 源码中可以合理推断的设计考量，就是原作者明示说过的意图；
- 未来可改进点已经由当前 fork 完成。

这些边界不会削弱面试叙事，反而让你的回答更精确、更经得起追问。

