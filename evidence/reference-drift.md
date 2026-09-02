# 作者资料、上游版本与 AsterRAG 的漂移登记

> 采集日期：2026-09-01  
> 实现目标：AsterRAG `98894c2c42c015a3c874c6b3c986ac863c85b731`  
> 教学参考：Ragent `1.0.0`、作者公开主页/知识星球专栏、`how-claude-code-works`  
> 原则：参考资料可以帮助安排学习顺序，不能覆盖冻结源码。网页内容会继续变化，因此这里只记录本次采集快照。

## 1. 版本关系

| 对象 | 冻结身份 | 用途 | 结论 |
|---|---|---|---|
| AsterRAG | `98894c2c...` | 本教程唯一实现事实目标 | 当前教程所有类、配置和运行验证必须对齐它 |
| nageoffer/ragent 当前上游 | `1cb684ed...` | 追踪改名前的最近上游实现 | 是 AsterRAG 的祖先；AsterRAG 在其上多 3 个提交 |
| nageoffer/ragent `1.0.0` | `5500546c...` | 作者课程稳定学习基线 | 是当前上游的祖先，但模块、依赖和功能已经明显演进 |
| how-claude-code-works | `f4d6505e...` | 教学结构参考 | 只借鉴“架构先行、围绕主循环、专题下钻、分路线阅读”；其 Claude Code 事实不能移植到 AsterRAG |

AsterRAG 相对当前上游的 3 个提交主要涉及项目身份、文档/前端命名和 CI 分层。产品实现仍与当前上游高度同源，但教程必须引用 AsterRAG 自己的冻结 SHA，不能用“差不多一样”替代证据。

## 2. 作者课程自己声明的版本边界

作者知识星球专栏的 2026-08-12 更新日志明确说明：

- 当时正在更新 Agent 相关代码，项目结构和功能将有较大调整；
- 代码稳定后才正式演进到 2.0 架构；
- 建议学习者切换到 `1.0.0` 分支，当前课程资料也以 `1.0.0` 为准。

这与 Git 历史吻合：`1.0.0` 是 `5500546c...`，而当前上游和 AsterRAG 已经继续加入 `system`、`rag`、`agent` 等模块及新的 Agent 状态/记忆链。结论不是“作者教程错误”，而是**它描述的版本与本教程目标不同**。

作者专栏的内容编排覆盖 RAG 基础、启动、知识库建设、模型基础设施、知识问答、评测和面试问题。它提供了有价值的专题清单，但评论区也反复出现“文章多、抓不住主线”的学习反馈。因而本教程保留其关键主题，同时用一张总图和三条调用链重排，不能按文章列表逐条搬运。

## 3. 已确认的实现漂移

### D-001：Maven 模块从 4 个演进到 7 个

| 资料 | 事实 |
|---|---|
| 作者公开主页（页面显示 2026-07-28 更新） | `framework`、`infra-ai`、`bootstrap`、`mcp-server` 四模块 |
| Ragent `1.0.0` 根 POM | 同样声明四模块 |
| AsterRAG 冻结根 POM | `framework`、`infra-ai`、`system`、`rag`、`agent`、`bootstrap`、`mcp-server` 七模块 |

教程处理：第 1、2 章画七模块依赖图；解释 `mcp-server` 是独立应用，其余是模块化单体，不把七个 Maven 模块说成七个微服务。

### D-002：Spring Boot 从 3.5.7 演进到 4.1.0

| 资料 | 版本 |
|---|---|
| 作者公开主页 | Spring Boot 3.5.7 |
| Ragent `1.0.0` 根 POM | 3.5.7 |
| AsterRAG 冻结根 POM | 4.1.0 |

教程处理：运行命令、依赖语义和源码链接均按 4.1.0；作者教程中与 Boot 3 绑定的结论只能在验证后迁移。

### D-003：数据库规模已经变化

| 资料 | 计数口径/结果 |
|---|---|
| 作者公开主页 | “当前全量脚本 22 张业务表” |
| Ragent `1.0.0` 的 `schema_pg.sql` | 静态扫描 21 个 `CREATE TABLE` |
| AsterRAG 冻结 `schema_pg.sql` | 静态扫描 31 个 `CREATE TABLE` |

公开页面的“业务表”可能有自己的口径，不能仅用数值判断对错；但它显然不能作为 AsterRAG 当前 Schema 清单。教程按 31 张表分领域列出，并把“业务表”“全部 CREATE TABLE”“派生索引表”口径分开。

### D-004：默认向量后端已经从课程迁移叙事稳定到 pgvector

作者知识星球总览写出“Milvus 2.6.6 → PostgreSQL Pgvector”；公开主页写“PostgreSQL + pgvector（默认）/ Milvus 2.6”。AsterRAG 的 `application.yaml` 明确配置 `rag.vector.type=pg`，与迁移后的结论一致。

教程处理：把 pgvector 写成**随仓库 YAML 默认值**；同时说明 Milvus Bean 的条件兜底与 YAML 显式选择是两个层次，不能只看 `matchIfMissing=true` 得出相反结论。

### D-005：公开主页的“可编排入库 Pipeline”不能直接等同于知识文档当前主链

作者公开主页把“可编排入库 Pipeline、节点日志”列为知识闭环和扩展能力。AsterRAG 源码确实存在：

- `IngestionPipelineController` / `IngestionTaskController`；
- `PipelineDefinition` / `IngestionEngine`；
- Fetcher、Parser、Enhancer、Chunker、Enricher、Indexer；
- Pipeline、Task 和 Node Log 数据表。

但是当前知识文档路径是：`startChunk` → RocketMQ → `DefaultIngestionKernel` 固定五步；而 `KnowledgeDocumentServiceImpl.runChunkTask` 对 `ProcessMode.PIPELINE` 明确抛出“重构中，暂不可用”。

教程处理：将两者画成并列子系统。可配置 Pipeline 是“存在但有入口边界的能力”；不能宣传为当前知识文档默认入库方式。

### D-006：检索实现“支持多通道”与默认运行“启用多通道”不是一回事

作者主页写向量、关键词、图谱、联网搜索并行召回。AsterRAG 源码存在四类 `SearchChannel` 和并行/超时/后处理编排，因此“支持”成立；但随仓库 YAML 只启用向量通道，关键词、图谱、联网通道默认关闭，关键词和图谱后端类型也为 `none`。

教程处理：第 11 章先讲共同接口和可选通道，再用配置矩阵明确当前默认只有向量通道；只有改配置、补服务并真实验证后，才能声称某次运行完成多路召回。

### D-007：执行架构从课程的确定性 RAG 主线演进到默认 Agent 档

作者课程的大量章节围绕确定性 RAG 八阶段、SSE、并发和 MCP 参数提取。它们在 AsterRAG 中仍存在；但随仓库 YAML 的 `ragent.engine.type=agent` 会额外装配 Agent Controller、AgentScope ReAct Runtime、Agent State/压缩/长期记忆，并把知识检索作为 `search_knowledge` 工具提供给 Agent。

教程处理：不能删除确定性 RAG 主线，也不能把 Agent 说成它的改名。第 8～13 章讲确定性读路径；第 14～16 章讲 Agent 怎样通过窄门面复用检索，以及两套 SSE/持久化的差别。

### D-008：前端大版本目前与作者主页基本一致

作者主页写 React 18、Vite、TypeScript；AsterRAG `frontend/package.json` 为 React `^18.3.1`、Vite `^5.4.3`、TypeScript `^5.5.4`。这条当前属于“一致”，但仍应引用冻结 package.json，而不是把网页当锁文件。

## 4. 可借鉴但不能移植的教学设计

`how-claude-code-works` 的结构价值在于：

- README 先给系统架构图，再给主循环和关键设计；
- 专题围绕主循环、上下文、工具、记忆、安全和可观测性逐层下钻；
- 提供 10 分钟、核心原理、构建/定制、安全等不同阅读路线；
- 对源码快照、后续黑盒推断和声明边界做区分。

AsterRAG 教程采用这些组织原则，但不复用其中任何 Claude Code 数值、组件或机制。尤其不能因为参考教程有多 Agent、Skill、Hook、权限纵深等章节，就声称 AsterRAG 也实现了同名能力。

## 5. 教程写作约束

1. 每条作者资料引用都标明页面/课程日期和用途，不与源码锚点混写。
2. 遇到版本冲突时，正文先写 AsterRAG 冻结事实，再用“版本漂移”侧栏解释旧教程为什么不同。
3. 作者页面说“支持”时，必须继续核对实现类、条件装配、默认配置和运行证据。
4. 课程列出一个主题不等于 AsterRAG 当前一定实现；源码存在一个类也不等于默认链路会执行。
5. 公开页面、README、GitHub Star、截图或 HTTP 200 都不作为功能闭环证明。

## 6. 参考锚点

- 作者公开主页：`https://nageoffer.com/ragent/`（页面显示 Last updated on Jul 28, 2026；本次采集 2026-09-01）。
- 作者知识星球专栏：`https://wx.zsxq.com/columns/51121244585524?column_id=281884884411`（总览最后编辑 2026-08-12；本次通过用户已登录的内置浏览器只读采集）。
- 冻结 Ragent `1.0.0`：`5500546c4e4742752adaaebf51c9423bef5f3497`。
- 冻结 `how-claude-code-works`：`f4d6505ed9162a0ee6be089190f74c419ecacb19`。
- 冻结 AsterRAG：`98894c2c42c015a3c874c6b3c986ac863c85b731`。

