# 第 11 章：多路召回怎样协作——预算、并行通道与局部降级

> 第 10 章为每个子问题算出了意图和检索作用域。本章进入真正的“取证”阶段：向量、关键词、图谱和 Web 怎样读同一份 `SearchContext`，怎样并行运行，怎样把某一路失败限制在该路，以及 20/40/10 三段预算为什么不能共用一个 topK。

## 11.1 两层并行，先看全图

`RetrievalEngine.retrieve(subIntents)` 先为每个子问题建立一个 future：

```text
子问题 1 ─┐
子问题 2 ─┼─ ragContextExecutor 并行 buildSubQuestionContext
子问题 3 ─┘
```

每个子问题的 KB 部分调用 `MultiChannelRetrievalEngine`，内部再并行启动启用通道：

```text
一个 SubQuestionIntent
        ↓
SearchContext(question + intents + scope + budget)
        ├── VectorSearch
        ├── KeywordSearch   可选
        ├── GraphSearch     可选
        └── WebSearch       可选
                ↓
        SearchChannelResult[]
                ↓
        有序后处理器链（第 12 章）
```

所以并行粒度有两层：子问题之间并行，同一子问题的 SearchChannel 之间并行。

但 KB 与 MCP 在一个 `buildSubQuestionContext` 内不是同时启动：源码先完成 `retrieveAndRerank`，再执行该子问题的 MCP 部分；多个 MCP tool 自身才由 `mcpBatchExecutor` 并行。这是方法顺序能直接确认的边界。

---

## 11.2 `SearchContext` 是通道之间的共同合同

对一个子问题，`buildSearchContext` 同时把 `originalQuestion` 和 `rewrittenQuestion` 设置为该 `subQuestion`，并挂入：

- 单个 `SubQuestionIntent` 的列表；
- `RetrievalBudget`；
- 第 10 章算出的 `RetrievalScope`；
- 可扩展 metadata。

所有本地知识通道读同一份 scope，不再各自根据 NodeScore 判断库范围。这样不会出现：

```text
向量通道认为应该全库
关键词通道却认为应该定向
图谱通道又按另一阈值选库
```

scope 解决“去哪些库”，channel 解决“用什么检索模态”，budget 解决“各阶段最多留下多少”。这是三个正交维度。

---

## 11.3 20、40、10：一个检索漏斗有三种 topK

当前默认配置：

```yaml
rag.search:
  recall-budget: 20
  fusion.rerank-candidate-limit: 40
  default-top-k: 10
```

`RetrievalEngine` 一次构造：

```java
new RetrievalBudget(
    recallBudget,   // 20
    candidateLimit, // 40
    contextTopK     // 10
)
```

| 预算 | 当前默认 | 谁使用 | 回答的问题 |
|---|---:|---|---|
| `recallBudget` | 20 | 各本地通道召回 | 每种模态先多找多少候选？ |
| `candidateLimit` | 40 | 融合后送 rerank 前截断 | 最贵的精排最多处理多少？ |
| `contextTopK` | 10 | 最终上下文格式化 | 最多多少条证据进入 LLM？ |

启动时 `SearchChannelProperties.afterPropertiesSet` 校验：

```text
recallBudget >= contextTopK
candidateLimit <= 0 或 candidateLimit >= contextTopK
```

还会校验 scope 阈值和 evidence 分数范围。配置矛盾直接使应用启动失败，而不是在线上悄悄只能返回少于产品期望的结果。

### 11.3.1 为什么不能只用一个 topK

如果全都写成 10：

- 每通道只召回 10 条，跨通道融合前候选可能太少；
- 精排成本无法单独控制；
- 想让最终 Prompt 更短时，会意外缩小初始召回。

三段预算把“要广”“最贵阶段上限”“最终要精”分开。`RetrievalBudget` 本身只是不可变值对象，单调不变式由配置类负责。

### 11.3.2 node.topK 只覆盖一条具体路径

意图节点可配置 `topK`，但当前源码并没有让它覆盖所有阶段。它只在**向量定向路**中覆盖默认 recall depth：多个命中意图取最大 node.topK，再被 candidateLimit 钳制，之后才按主路/补充路切配额。

全局向量、关键词和图谱仍读公共 recallBudget；最终 contextTopK 也不会被 node.topK 抬高。准确说法不是“每个意图都能控制最终返回条数”，而是“意图节点可调定向向量召回深度”。

---

## 11.4 哪些通道在默认配置下真的存在并启用

| 通道 | Bean 注册条件 | 运行时 enabled 条件 | 当前 YAML |
|---|---|---|---|
| Vector | `VectorSearchChannel` 总是组件；底层 PG/Milvus 二选一 | `channels.vector.enabled` | true，后端 `rag.vector.type=pg` |
| Keyword | `rag.keyword.type=es` 才注册 | `channels.keyword.enabled` | type=none，enabled=false |
| Graph | `rag.graph.type=lightrag` 才注册 | `channels.graph.enabled` | type=none，enabled=false |
| Web | 组件始终注册 | enabled=true 且能解析 API key | enabled=false |

因此当前默认实际是纯向量召回。源码中“实现了 ES/LightRAG/Web 通道”不等于默认问答会调用它们。

`SearchChannelType.GRAPH` 枚举注释仍写着“预留，尚未实现”，但当前已有 `GraphSearchChannel`、`LightRagClient` 和条件装配。这里应以实现和 Bean 条件为准，把枚举注释视为漂移，不能照抄。

---

## 11.5 通道怎样并行，顺序又意味着什么

引擎先过滤 `isEnabled(context)`，再按 `SearchChannelType.ordinal()` 稳定排序，随后为每个通道提交 `CompletableFuture.supplyAsync`。

排序只稳定日志和派发顺序，不代表 Vector 优先、Graph 次要。真正执行是并行的，后续 RRF 也依据各通道内部名次，而不是 future 列表位置。

每个结果统一为：

```text
channelType
channelName
chunks
latencyMs
metadata
```

异常、无数据和超时都能转成同形状的 `emptyResult`，下游不需要用异常类型猜通道身份。

---

## 11.6 15 秒超时：放弃结果，不中断底层工作

默认 `channels.timeout-ms=15000`。引擎为 future 调用：

```java
future.orTimeout(timeoutMs, TimeUnit.MILLISECONDS)
```

超时后返回该通道的空结果，其余通道继续融合。记录的 latency 是从启动到放弃的真实等待时间，便于区分“秒回但无数据”和“等满 15 秒被放弃”。

但源码注释也明确：**只放弃结果，不中断执行。** `orTimeout` 使包装 future 异常完成，并没有把数据库查询、HTTP 请求或底层任务可靠 cancel；原任务可能继续占用线程和外部资源直到自行结束。

因此：

- 用户响应不会被最慢通道无限钳制；
- 过小超时可能造成后台白算；
- 不能看到空结果就断言底层查询已停止；
- 通道内部自己的 HTTP timeout 仍然重要，例如 Web 默认 10 秒。

若 `timeout-ms<=0`，不加通道级超时，整次子问题检索会等待最慢 future。

---

## 11.7 Vector：一条通道内部切换全局与定向

项目没有把“全局向量”和“意图向量”注册成两个并列 SearchChannel。`VectorSearchChannel` 读取 scope，在内部选择：

```text
directed=false → 全部 active collections
directed=true  → target 主路 + supplement 保底路
```

如果拆成两个并列通道，同一向量证据可能同时出现两次，在后续 RRF 里被误认为“多模态共同命中”而自我加权。

### 11.7.1 全局向量路径

1. 对子问题生成并归一化查询向量；
2. 在所有 target collections 中召回 recallBudget=20；
3. PG 后端支持跨库查询时，一条 SQL 使用 `collection_name IN (...)`，LIMIT 是整个范围总量；
4. 返回按余弦分数排序的候选。

`PgVectorRetrieverService` 还设置 `hnsw.ef_search=200` 和 `hnsw.iterative_scan=relaxed_order`，随后用：

```sql
1 - (embedding <=> query_vector)
```

作为 score。通道出口仍会重新按 score 排序再截断，因为 relaxed order 不应被当作严格最终排序保证。

### 11.7.2 定向主路与补充路

定向路径只算一次 query embedding，然后：

```text
primary:    targetCollections
supplement: supplementCollections
```

补充路在同一个 `innerRetrievalExecutor` 异步执行，主路当前线程执行；补充路异常只丢补充结果，不能把已拿到的主路证据一起带走。

默认 budget=20、ratio=0.25 时，`ScopeQuota.split` 计算：

```text
supplement = round(20 × 0.25) = 5
primary    = 15
```

它保证主路至少留 1 个名额；总额度只有 1 时补充为 0。两路结果按 score 混排，但各自出口先兑现固定条数，所以补充证据至少有“进入通道候选”的机会，不保证活过后续融合和精排。

### 11.7.3 后端不支持跨库单查时

`CollectionParallelRetriever` 对每个 collection 并行取候选，单库失败返回空，再合并按 score 降序。`retrieveOver` 最终仍截断为总 budget，避免“每库 20 条”悄悄把通道总预算膨胀为 `库数 × 20`。

---

## 11.8 Keyword：同 scope 的 BM25 补充模态

`KeywordSearchChannel` 只在 `rag.keyword.type=es` 时注册，并依赖 `channels.keyword.enabled=true` 才执行。它适合精确词、编号和专有名词等向量语义可能弱化的查询。

它与 Vector 共读：

- 同一个 mainQuestion；
- 同一个 target/supplement scope；
- 同一个 recallBudget 和 supplementRatio。

主路同步查 ES，补充路异步；补充失败只丢自己。返回 BM25 通道内顺序，后续融合不会把 BM25 数值直接与余弦分数比较。

关键词写入在第 7 章是向量服务的 best-effort 装饰器。因此即使检索通道配置开启，ES 索引也可能因先前同步失败而缺少部分文档；“通道 Bean 存在”不等于派生索引完全一致。

---

## 11.9 Graph：全图查询后的结果侧归属过滤

`GraphSearchChannel` 只在 `rag.graph.type=lightrag` 时注册，且还需 `channels.graph.enabled=true`。

当前 LightRAG `/query` 没有 per-request workspace；一个实例是一张共享图。因此 scope 不是在查询前选择独立子图，而是：

1. 向整张图发查询；
2. 依赖 `file_path`/`GraphFileSource` 识别证据归属；
3. 在结果侧按目标 collection 过滤。

定向时，请求 `topK = recallBudget × 3`，默认 60，再在过滤后按 ScopeQuota 截为主路/补充路。上浮是为了缓解“跨库结果先占据 LightRAG topK，过滤后命中库所剩太少”。

全局 scope 也传 active collections 做结果过滤；不属于任何有效库的 unmatched 证据会被丢弃并告警，它们可能是已删库残留或来源解析失败。

这不是物理图隔离。若面试官问“多租户图谱如何隔离”，当前准确回答是：源码按 file source 做结果侧逻辑过滤，真正子图隔离需要多实例或后端 workspace 能力，当前类注释也明确留待后续。

---

## 11.10 Web：独立于本地知识库 scope 的外部补充

`WebSearchChannel` 的启用条件缺一不可：

- `channels.web-search.enabled=true`；
- 配置 `api-key` 或环境变量 `YDC_API_KEY` 非空。

它把子问题发送给 You.com Search，默认 count=5、上限20、HTTP timeout=10秒。响应的 web 和 news 合并后统一截到 count，总结果转换为 `RetrievedChunk`：

- id 优先取 URL；
- text 组合标题、描述、snippets 和来源；
- 初始 score 为 `1/(rank+1)`，只表示通道内名次。

Web 不读取 KB `targetCollections`，也不使用本地 recallBudget=20，而是自己的 count。它是公开网络补充，不属于“在选中的企业知识库中换一种检索方式”。

非 2xx、网络异常、解析失败或内部超时都返回空结果，且日志不输出 API key。

---

## 11.11 原始分数为什么不能直接混排

四个通道的 score 量纲不同：

| 通道 | 原始排序信号 |
|---|---|
| Vector | 余弦相似度 |
| Keyword | ES/BM25 相关度 |
| Graph | LightRAG 返回名次/映射分数 |
| Web | 人工设定的 `1/(rank+1)` |

不能把 0.8 余弦、12.5 BM25 和 0.5 Web 分数放在一个列表里按数值排序。项目先保留每个通道的相对名次，再由下一章的 RRF 融合统一尺度，随后用 reranker 重新对“问题—证据”打分。

多通道的价值不是“分数相加越大越好”，而是不同模态提供互补候选和重复命中信号。

---

## 11.12 空通道和空检索怎样收敛

每个通道内部捕获异常并返回 `emptyResult`；引擎外层也捕获异步异常/超时。空结果仍参与统计，但没有 Chunk 进入后处理。

若没有任何 `isEnabled` 通道：

1. 引擎记录配置事故警告；
2. 返回空通道列表；
3. KB 结果为空；
4. 若也没有 MCP context，主 Pipeline 的 `handleEmptyRetrieval` 输出“未检索到与问题相关的文档内容。”并完成；
5. 不静默退化为没有证据的普通 LLM 回答。

若只有一个通道失败，其他通道仍可形成证据。若所有本地通道为空但 MCP 返回了有效上下文，`RetrievalContext` 仍不一定整体为空，后续可以基于 MCP 回答。

---

## 11.13 “并行”不等于“无限并发”或“完全隔离”

源码用三个不同 executor 层次：

- `ragContextExecutor`：子问题；
- `ragRetrievalExecutor`：SearchChannel；
- `innerRetrievalExecutor`：通道内部的逐库或 supplement fan-out。

线程池容量、队列和底层连接池仍是共享约束。子问题数、通道数、collection 数相乘可能产生较多任务；代码层的 parallel future 只是调度模型，不等于资源无限。

同样，局部降级只保证异常不会向上抛毁掉其他结果，不保证底层外部系统没有继续耗资源。解释工程鲁棒性时，要同时说“故障结果隔离”和“资源执行未必被取消”。

---

## 11.14 责任边界与设计解读

| 组件 | 负责 | 不负责 |
|---|---|---|
| `RetrievalEngine` | 统一预算、子问题并行、KB/MCP 上下文合并 | 不实现具体搜索算法 |
| `MultiChannelRetrievalEngine` | scope→SearchContext、通道并发、超时空结果、后处理入口 | 不真正中断超时底层任务 |
| `SearchChannel` | 模态启用判断、搜索、统一结果形状 | 不自行改变全局 scope |
| `ScopeQuota` | 主路/补充路固定名额 | 不保证补充证据通过后处理 |
| `VectorSearchChannel` | 查询向量、全局/定向、跨库、补充路 | 不做最终 rerank |
| `KeywordSearchChannel` | ES/BM25 召回 | 不在默认配置注册 |
| `GraphSearchChannel` | LightRAG 全图召回和结果侧归属过滤 | 不提供物理子图隔离 |
| `WebSearchChannel` | You.com 外部公开信息 | 不受 KB collection scope 控制 |

从实现可以解读：

- 统一 scope 避免各模态路由不一致；
- 三段预算把召回质量、精排成本和 Prompt 长度解耦；
- 通道空结果协议让局部故障可组合；
- 定向加 supplement 是对概率路由不确定性的显式补偿；
- 超时只放弃结果，换取较简单的并发组合，但需要底层 timeout/线程池共同控制资源。

---

## 11.15 面试追问与回答骨架

### 问：项目为什么做多路召回？

向量适合语义近似，BM25 擅长精确词，图谱适合关系，Web 补时效公开信息。它们并行产出不同量纲的候选，先按通道内名次用 RRF 融合，再统一 rerank，而不是直接比较原始 score。

### 问：默认会同时调用四个通道吗？

不会。默认只有 Vector enabled，后端是 PostgreSQL。Keyword/Graph 的 backend type 和 channel enabled 都关闭；Web enabled 关闭且还要求 API key。

### 问：20/40/10 分别是什么？

20 是每个本地模态的初始召回基数，40 是融合后最多送 reranker 的候选，10 是最终进入 LLM 的证据上限。启动校验保证漏斗不会在前面比最终需求还窄。

### 问：一个通道超过 15 秒会怎样？

包装 future 返回该通道空结果，其他通道继续。`orTimeout` 不可靠中断底层任务，所以迟到查询可能仍在后台运行；通道自己的数据库/HTTP timeout 和线程池仍需配置。

### 问：定向检索怎样分主路和补充路？

同一个 scope 给出 target 和其余 active collections。默认 20×25% 得到 15 个主路、5 个补充名额；向量主/补共用一次 embedding，补充异常不带走主路。名额只保证到通道出口。

### 问：Graph 如何按知识库过滤？

当前 LightRAG 单实例是一张全图，没有 per-request workspace。通道先查全图，再根据 file source 把证据映射到 collection，结果侧过滤；定向时 topK 上浮 3 倍以补偿过滤损失，这不是物理隔离。

### 问：没有任何通道时为什么不直接让 LLM 回答？

源码把它视为配置事故，返回空检索，主 Pipeline 输出固定无结果提示。这样不会把“知识问答”静默变成无证据生成。

---

## 11.16 源码定位卡

- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/RetrievalEngine.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/MultiChannelRetrievalEngine.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/RetrievalBudget.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/channel/SearchContext.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/channel/SearchChannel.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/channel/ScopeQuota.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/channel/VectorSearchChannel.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/channel/KeywordSearchChannel.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/channel/GraphSearchChannel.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/channel/WebSearchChannel.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/PgVectorRetrieverService.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/strategy/CollectionParallelRetriever.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/SearchChannelProperties.java`
- `bootstrap/src/main/resources/application.yaml`

---

## 11.17 读完本章，你应该能自己回答

1. 子问题并行、通道并行和通道内部 fan-out 分别使用哪一层 executor？
2. scope、channel、budget 为什么是三个独立概念？
3. recallBudget、candidateLimit、contextTopK 分别约束哪一段？
4. 默认为什么只有 Vector 真正执行？
5. 通道超时为什么不等于底层查询已取消？
6. Vector、Keyword、Graph 的 scope 实现有什么差别，Web 为什么不读 collection？
7. 余弦、BM25、图谱和 Web 原始分数为什么不能直接混排？

现在我们手上仍只是“多而杂”的候选。下一章将沿后处理器顺序解释：去重怎样识别同一块、RRF 怎样统一名次、rerank 怎样重新评分，以及证据门为什么可能把看似满额的候选整批清空。
