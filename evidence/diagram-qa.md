# P2 架构图渲染与视觉检查

> 检查日期：2026-09-01  
> Mermaid CLI：`@mermaid-js/mermaid-cli 11.12.0`  
> 输出：SVG 用于教程正文，2400px 白底 PNG 用于视觉检查/兼容预览。

## 1. 产物

| 图 | Mermaid 源 | SVG viewBox | 作用 |
|---|---|---|---|
| 总体架构 | `assets/architecture/system-overview.mmd` | `0 0 3883.84375 2299.442138671875` | 第一章总图；控制面、两种入库、确定性 RAG、Agent、共享状态 |
| 知识文档入库时序 | `assets/diagrams/ingestion-sequence.mmd` | `-50 -10 3273 2358.5` | 上传/开始分块断点、MQ、固定内核、成功失败收尾 |
| 确定性 RAG 时序 | `assets/diagrams/rag-sequence.mmd` | `-50 -10 3576 2721` | 排队拒绝、短路、检索、模型流、三类终态 |
| ReAct Agent 时序 | `assets/diagrams/agent-sequence.mmd` | `-50 -10 3894 2779` | 副作用前 gate、工具循环、State 适配边界、三路释放 |
| 状态所有权 | `assets/diagrams/state-ownership.mmd` | `0 0 2864.7421875 661.5214233398438` | 业务事实、对象、派生索引、Redis 协调态和进程态 |

所有五份 `.mmd` 均实际生成 `.svg` 和 `.png`；渲染命令返回 0，不是只做语法猜测。

## 2. 视觉检查结果

### 总体架构图

- 无裁切，五个大区域有清晰边框和颜色区分。
- 顶部“用户→React→Spring MVC”后再分流，读者能先找入口。
- 知识文档主链和独立 `/ingestion/tasks` 分成两个区域；虚线 `ProcessMode PIPELINE 当前暂停` 可见。
- 固定内核的业务状态/日志由 `KnowledgeDocumentService` 收尾，不误画成内核直接写任务状态。
- Agent 通过 `KnowledgeSearchFacade` 汇入 `RetrievalEngine`，没有汇入完整 RAG SSE 链。
- 底部共享状态连线较多，但 SVG 可缩放；第一章正文将按区域分步讲解，三张时序图承接细节，不要求读者一次读完所有箭头。

### 三张时序图

- participant 标题、编号、alt/loop/par 区块和 Note 均完整，无重叠到不可读程度。
- 入库图明确把 upload 返回与后续 chunk 请求分开；PIPELINE 暂停与 direct 分块在 alt 中分离。
- RAG 图明确把 reject 放在 Trace/Pipeline 之前；正常、取消、流失败分别收尾；取消 Trace 标注“待运行证据确认”。
- Agent 图明确把 gate 放在 META/会话副作用之前；`PgAgentStateStore` 只画为框架适配边界，具体 save/load 时点标为未由应用层确定；正常/取消/失败最后都进入 RunHandle 释放。

### 状态所有权图

- 五种状态按颜色和区域分组，业务事实与 Redis/进程态不会被看成同一持久级别。
- pgvector 归入 PostgreSQL 物理存储，同时由箭头表达它是摄取派生向量。
- 对象存储原文件与知识文档元数据分离。
- Agent 业务消息、AgentScope State、压缩/长期记忆分成独立节点。

## 3. 已知展示边界

- PNG 是兼容预览，不适合在窄屏完整展示；正文优先嵌入 SVG，并允许点击/新标签放大。
- 第一章总图用于建立全局模型，不在图中塞入所有 Controller、表或配置键；细节由时序图、状态图和后续章节源码卡片承接。
- 图的“可选”表示源码/配置可选，不表示已完成真实运行验证。
- 当前图只通过结构和视觉检查；P3～P6 的真实运行结果可能要求为箭头补充证据状态，但不能在没有源码变化时随意重画责任边界。

## 4. 复现

执行：

```bash
./scripts/render-diagrams.sh
./scripts/verify-p2-evidence.sh
```

`render-diagrams.sh` 固定 Mermaid CLI 版本并同时生成 SVG/PNG；`verify-p2-evidence.sh` 检查五组产物、章节/论断覆盖和关键版本边界。

