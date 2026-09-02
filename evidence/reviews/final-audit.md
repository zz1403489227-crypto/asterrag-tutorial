# AsterRAG 教程最终审计

> 日期：2026-09-01  
> 结论：**PASS**  
> 审计范围：教程与冻结源码的对齐、全书完整性、导航/图片/Markdown、归属和面试真实性。本审计不启动业务服务，不以再次证明项目正确为目标。

## 1. 发布内容完整性

| 产物 | 数量 | 行数 |
|---|---:|---:|
| 根导航 `README.md` | 1 | 181 |
| 正文第 0～20 章 | 21 | 10,711 |
| 附录：100 题、术语表、源码索引 | 3 | 944 |
| 发布阅读层合计 | 25 | 11,836 |

另有写作计划、执行进度、章节卡、详细提纲、Source Map、三条调用链、源码普查、测试矩阵、参考漂移和图审计等工作证据。

## 2. 冻结源码完整性

`scripts/verify-source-lock.sh` 最终结果：

| 资料 | HEAD | Tree | 工作树 |
|---|---|---|---|
| AsterRAG | `98894c2c42c015a3c874c6b3c986ac863c85b731` | `19b1702464b756670138554e70894ede5ba4198a` | CLEAN |
| ragent-upstream | `1cb684ed5df03f241d90c836466465f6aab37800` | `1fb1efdf6595f2406cc4822544d5819a09565864` | CLEAN |
| how-claude-code-works | `f4d6505ed9162a0ee6be089190f74c419ecacb19` | `36e3674cf0162e1d0547bca62e23eeef56edfd52` | CLEAN |
| Ragent `1.0.0` | `5500546c4e4742752adaaebf51c9423bef5f3497` | tag 对照 | PASS |

AsterRAG 的上游导入基线 `1cb684e...` 是教程目标提交 `98894c2...` 的 ancestor。三份冻结源都没有被教程写作修改。

## 3. 自动静态审计

执行：

```bash
python3 scripts/audit-tutorial.py
```

结果：

```text
checks=692
failures=0
warnings=0
```

692 项检查覆盖：

- 21 个正文文件和 3 个附录文件全部存在；
- 根 README 导航覆盖 0～20 章和三份附录；
- 每章 H1 编号与文件名一致；
- 发布层 Markdown fence 成对；
- 所有本地导航链接和图片引用有实际目标；
- 总体架构、入库时序、RAG 时序、Agent 时序、状态所有权 5 组图均有 `.mmd + .svg + .png`；
- 附录 A 精确包含连续 `Q1..Q100`；
- `source-map.csv` 有 41 条唯一 claim，39 条 `verified-source`、2 条 `reference-only`；
- 41 条 Source Map 的本地源码路径在冻结 AsterRAG 中全部存在；
- 正文/附录中使用反引号标注的精确仓库路径全部存在；
- README 保留冻结 SHA、`nageoffer/ragent`、Apache-2.0 和“非部署复现”学习目标；
- 第 20 章明确保留非从零原创边界。

## 4. P1/P2 证据链回归

### `scripts/verify-p1-evidence.sh`

PASS：

- 三份源码锁与 Ragent `1.0.0` tag；
- 7 份 P1 必需证据文件；
- 41 条 Source Map；
- 知识文档固定摄取、独立通用 Ingestion、确定性 RAG 和 Agent 三条主链边界。

### `scripts/verify-p2-evidence.sh`

PASS：

- 5 组图的源文件/可发布输出；
- 关键虚线和默认/可选边界；
- 0～20 章全书骨架；
- 41 条 chapter claim 对 0～20 章的分配。

## 5. 内容连贯性抽查

| 区域 | 抽查点 | 结果 |
|---|---|---|
| 总体架构 | 知识写路径、确定性 RAG、ReAct Agent、共享 owner 并列；后续章节有映射 | PASS |
| 入库主链 | upload 与 chunk 分开；固定五步是知识文档真实主链；通用 Pipeline 独立；文档 PIPELINE 模式暂停 | PASS |
| 检索主链 | 记忆→改写→意图/scope→多通道→后处理→grounding/prompt/model→收尾无跳步 | PASS |
| RAG 短路 | 排队拒绝、歧义引导、system-only、空检索、取消和错误均区分用户可见/持久/Trace/释放 | PASS |
| Agent 主链 | gate 在副作用前；provider/catalog/ReAct/tool/bridge/finalizer 连续；知识复用仅经窄门面 | PASS |
| Agent 状态 | 业务消息、AgentScope State、RuntimeContext、Compaction 和 LTM 的 owner/寿命已分开 | PASS |
| 配置 | POM→YAML/Properties→Conditional Bean→runtime branch 四层；workflow Java 兜底 vs YAML agent；Milvus matchIfMissing vs YAML pg | PASS |
| 前端 | RAG/Agent 两套 hook/store 和 SSE 分开；临时投影不冒充持久真相；DEMO_TURN 不冒充执行证据 | PASS |
| 章节桥接 | 写路径 4～7、RAG 8～13、Agent 14～16、工程 17～19 均由前章输出引出后章 | PASS |

## 6. 归属、隐私和面试真实性

### 归属

- 根 README 明确 AsterRAG 基于 Apache-2.0 的 `nageoffer/ragent`。
- 冻结源中保留 LICENSE、NOTICE、`docs/UPSTREAM.md` 和完整上游历史。
- 第 0 章和第 20 章都明确“上游核心能力不是个人从零原创”。
- 个人改造只根据 AsterRAG 对上游的真实 Git diff 描述：项目身份/首页/前端品牌与 CI 分层。

### 受限参考资料

- 作者知识星球只用于版本声明和教学主题线索；教程未复制受限文章正文、图片或评论。
- how-claude-code-works 只提供“架构先行、主循环、阅读路线”的教学组织参考，未被当成 AsterRAG 功能证据。

### 隐私/密钥扫描

对 `README + 21 章 + 3 附录` 扫描以下高风险模式，命中均为 0：

- 本机 `/Users/...` 私有路径；
- 服务器个人工作路径；
- OpenAI 密钥样式；
- AWS access key 样式；
- RSA/OpenSSH private key 头。

### 不夸大运行结果

- 教程不宣称自己部署并复现了全系统。
- 已有 27 个聚焦 Hermetic 用例只作为边界理解的辅助证据，不扩张成整个项目、集成依赖、浏览器路径或生产效果已验证。
- 未运行的选项保留为源码/配置事实或设计推演，不写成真实线上现象。

## 7. 有意保留的实现边界

以下不是教程遗漏，而是教程按冻结源码明确保留的当前边界：

1. 知识文档 `ProcessMode.PIPELINE` 主链当前显式暂停，不冒充已接通能力。
2. 单检索通道 `orTimeout` 放弃迟到结果，不无条件宣称已取消底层任务。
3. RAG 前端 emitter 断开与后端 `StreamTaskManager.cancel` 的显式接线边界已如实记录。
4. 模型首包提交后不再跨模型 fallback。
5. 当前 RAG/Agent 失败路径均不保存 assistant 错误行。
6. Agent 取消链只按实现证明业务 INTERRUPTED/finalizer，不无条件宣称每次都经 AgentScope interrupt-save。
7. YAML 注释中的 LightRAG `ingestion.enabled` 未在冻结源码接线，教程按实际 type/query 分支解释。
8. Schema 不由主应用自动迁移；YAML/Schema/Embedding 维度需一致；HNSW 两处索引名差异只记为静态源码事实。
9. RocketMQ starter 的精确启动连接时机不在项目源码中武断推定。
10. 前端 `/admin` 路由守卫不替代后端统一角色授权，欢迎页 `DEMO_TURN` 不冒充真实 Agent 执行证据。

## 8. 最终结论

教程已满足当前目标：

- 第 1 章先给出经源码核验的总体架构图，并将后续 20 章放回统一坐标；
- 不按技术名词堆砌，而是连续讲完写路径、确定性 RAG、Agent 和横切保护；
- 核心链详细到真实类/方法/对象/状态，普通 CRUD 和样板代码被压缩为导航；
- 状态 owner、正常/短路/拒绝/取消/失败和设计权衡贯穿全书；
- 附录 A 提供 100 道追问，第 20 章提供不同时长口述，且不伪造原创、运行、性能或生产经验。

审计结论为 **PASS**。

