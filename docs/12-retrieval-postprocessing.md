# 第 12 章：三十条候选怎样变成十条证据——去重、融合、精排与证据门

> 增补衔接：[第 24 章](24-hybrid-retrieval-to-evidence.md) 提供三路排名的 RRF 手算、20 / 40 / 10 预算与批级证据门例子。面试准备可先读该章建立直觉，再回来查本章的完整分支。

> 多通道返回的是候选，不是可以直接喂给模型的可靠证据。不同通道可能重复命中同一块，原始分数量纲不同，候选数量过多，而且“最像的十条”在知识库根本没有答案时仍可能满额返回。
>
> 本章沿当前源码中的五个后处理器逐步解释候选集合怎样变化，以及每个处理器失败时系统保留哪一版结果。

## 12.1 一条有序、可跳过的处理链

`MultiChannelRetrievalEngine.executePostProcessors` 收集所有 `SearchResultPostProcessor`，过滤 enabled 后按 `getOrder()` 升序执行：

```text
1   Deduplication
5   Fusion (RRF + candidate truncation)
10  Rerank
15  EvidenceGate
20  MetadataEnrichment
```

每个处理器接收：

- `chunks`：上一处理器的输出；
- `results`：不可变语义上的各通道原始结果；
- `context`：问题、scope 和三段 budget。

单个处理器抛异常时，引擎记录错误并跳过它，继续把异常前的 `chunks` 交给下一位。这里没有全链事务或“一个处理器失败就清空所有结果”。

可以先用一个示意例子看数据变化：

```text
Vector 20 + Keyword 20 + Graph 20
        ↓ 扁平化/去重
若干唯一候选
        ↓ RRF + candidateLimit
最多 40
        ↓ Rerank(contextTopK)
最多 10，带 rerankScore
        ↓ Evidence Gate
整批 10 或整批 0
        ↓ metadata 回表
补 docId/chunkIndex/docName，顺序不变
```

数字只是按照默认预算展示；默认配置实际只开启 Vector，因此常见输入是单通道最多20条。

---

## 12.2 `RetrievedChunk` 中其实有两种分数

候选对象包含：

```text
id / text
score          当前排序分：可能是余弦、BM25、Web名次、RRF或精排分
rerankScore    只有真实精排客户端写入，供证据门判断
collectionName
docId / chunkIndex / docName
```

`score` 会被多阶段覆写，读到 0.03 时不能仅凭字段名判断是 RRF 还是别的分数。`rerankScore` 专门保存 0～1 精排相关度；null 表示没有得到真实精排分。

这个双字段设计正是为了让 EvidenceGate 不把余弦、BM25 或 RRF 误当作 rerank 阈值输入。

---

## 12.3 第一步：按稳定 Key 去重，但保留原始多路名次

`DeduplicationPostProcessor` 总是启用。它遍历每个 `SearchChannelResult`，用 `RetrievedChunkKey.of(chunk)` 做 key：

```text
id 非空 → id
id 为空 → sha256(text)
```

同 key 多次出现时，`LinkedHashMap.putIfAbsent` 保留首次出现的对象。

### 12.3.1 “首次出现”不代表某通道分数更高

去重器不比较跨通道 score，因为余弦和 BM25 本来不可比。通道已经按枚举顺序稳定排列，所以首次对象的字段形态可预测；真正的多通道贡献由下一步从**原始 results**重新读取各通道名次。

也就是说：

```text
去重后的 chunks：一条实体
原始 results：仍记得它在 Vector 第2、Keyword 第1
```

去重没有抹掉“多路共同命中”信号。

### 12.3.2 Key 的边界

- 两个通道使用同一 chunkId：能稳定去重；
- 无 ID 的两条完全相同文本：按哈希去重；
- 同一内容被不同后端赋予不同非空 ID：不会仅因文本相同而合并；
- 同一 ID 却携带不同文本：首次对象保留，后续差异不会在这里仲裁。

因此去重契约依赖各本地索引沿用第 7 章同一 `chunkId`。它不是通用语义去重模型。

---

## 12.4 第二步：RRF 用名次统一量纲

`FusionPostProcessor` 在 strategy 为 `rrf` 时启用，当前默认如此。多通道时，对每个 key 计算：

```text
RRF(chunk) = Σ channelWeight / (k + rank + 1)
```

当前：

- `k=20`；
- Vector 1.0；
- Keyword 1.0；
- Graph 0.8；
- Web 0.5。

假设一个 Chunk 在 Vector 第1、Keyword 第3：

```text
1.0 / (20 + 1) + 1.0 / (20 + 3)
```

另一个只在 Vector 第1出现，则只有第一项。前者会因多路命中得到更高融合分，而不需要比较余弦和 BM25 的原始数值。

### 12.4.1 k 和权重分别改变什么

- k 越大，不同名次的差异越平滑；
- channel weight 改变某一模态在所有名次上的话语权；
- 多路命中会累计多项；
- 原始 score 数值被丢弃，只保留每个通道的名次。

当前 k=20 是配置事实。YAML 注释认为候选池20～40时 k=60过于平滑，但这属于项目配置说明，不是本教程声称已经通过质量实验得出的普适最优值。

### 12.4.2 单通道不会做伪 RRF

当 `results.size()<=1`，Fusion 保持原通道顺序，只执行候选池截断。默认只有 Vector 时，不会把余弦排名再无意义地改写成倒数名次分。

### 12.4.3 候选池上限在这里生效

RRF 后按 `candidateLimit=40` 截断，只有前40条进入 reranker。若 limit<=0 则不截断。

弱势通道可能在这里全部消失，因此代码记录“融合池按通道”和“送入 Rerank 按通道”的归因日志。补充路在第 11 章只保证进入通道出口，不保证穿过这个截断点。

---

## 12.5 第三步：Rerank 重新判断“问题—证据”相关性

`RerankPostProcessor` 默认启用，调用：

```java
rerankService.rerank(
    context.getMainQuestion(),
    chunks,
    contextTopK // 默认10
)
```

它把最多40条候选交给路由式精排服务，最终取最多10条。

### 12.5.1 模型路由与 noop 后备

当前 YAML 的 rerank candidates：

```text
qwen3-rerank / bailian / priority 1
rerank-noop  / noop    / priority 100
```

`RoutingRerankService` 使用公共 `ModelRoutingExecutor.executeWithFallback` 尝试候选。真实客户端失败后可以降级到 `NoopRerankClient`，后者只按现有顺序截取 topN，不生成 `rerankScore`。

因此“rerank.enabled=true”不等于每次结果都有真实精排分；它也可能走到 noop fallback。

### 12.5.2 真实精排客户端怎样回写

`BaiLianRerankClient`：

1. 先按 id 再去一次重；
2. 即使候选数不超过 topN，也仍调用精排，因为证据门需要分数；
3. 发送 query、documents、top_n；
4. 按返回 index 找回原 `RetrievedChunk`；
5. 用 `toBuilder()` 完整复制其他字段；
6. 同时把 relevance score 写入 `score` 和 `rerankScore`；
7. 返回不足 topN 时，用未出分候选补齐，并把 `score=0`、`rerankScore` 留空。

完整复制而不是白名单逐字段重建，可以避免新增 `collectionName` 等字段后在精排阶段静默丢失。

### 12.5.3 Rerank 失败的链级行为

- 模型候选内部失败：路由器尝试 fallback；
- fallback 到 noop：保留粗排顺序并截到10，无 rerankScore；
- 所有路由仍抛异常：后处理引擎跳过 Rerank，继续使用最多40条 pre-rerank 候选。

后一个分支甚至可能让最终条数暂时多于 contextTopK，因为最终 top10 正常由 Rerank 负责截断。系统选择“保留已有候选继续”而不是因精排故障整批归零。

---

## 12.6 第四步：证据门按整批最高分决定去留

默认：

```yaml
rag.search.evidence.min-rerank-score: 0.2
```

`EvidenceGatePostProcessor` 读取这一批所有有限 `rerankScore` 的最大值：

```text
至少一条有分，最高分 >= 0.2 → 整批保留
至少一条有分，最高分 < 0.2  → 整批丢弃
全批没有可读精排分          → warn 并放行
```

### 12.6.1 为什么不是逐条过滤0.2以下的块

当前源码把它设计成“批级资格门”：只判断这批证据是否至少有一条足够相关。过线后，其他较弱证据也保留；不过线时，系统认为知识库整体没有可靠回答基础。

可以这样理解：逐条阈值更激进，容易把补充背景切掉；按最高分只阻止“整批都弱”的情况。代价是弱块会随强块一起进入 Prompt，质量还要靠 top10排序和生成约束。

### 12.6.2 为什么无分时放行

noop fallback 和被跳过的 Rerank 都可能留下无 `rerankScore` 候选。若无分就全拒绝，精排服务最不稳定时 KB 侧会恒为空，而且表现与“库里没有资料”完全相同。

所以代码选择告警并放行，保持粗排可用性。启动校验只阻止“显式关闭 rerank 却配置正阈值”；它不能阻止运行时 fallback 到 noop。

### 12.6.3 0.2 是配置，不是本教程宣称的实测质量结论

阈值随 reranker 的分数分布变化。换模型后同样相关性的数值可能不同。源码专门记录本批最高/最低精排分用于校准；没有项目实验数据时，不能把0.2说成已证明的最优阈值或准确率指标。

---

## 12.7 第五步：只为最终存活证据回表补元数据

`MetadataEnrichmentPostProcessor` 默认通过 `rag.context.enrich.enabled=true` 启用，顺序20。它不重排，只补：

```text
docId
chunkIndex
docName
```

普通向量/关键词 Chunk 的 id 等于 `t_knowledge_chunk.id`，可批量回表；图谱证据的 id 可能不是 chunk 主键，但若已经带 docId，还能按 docId 补标题。

Web 结果以 URL 为 id，在本地块表查不到时保持 doc fields 为空，后续仍可作为无本地文档标题的证据渲染。

把回表放在最后可以只查最多10条正常结果，而不是为初始几十条候选都访问关系库。

### 12.7.1 富化不决定证据是否有效

找不到 doc metadata 时，该 Chunk 不会在这里被删除。元数据用于文档分组、标题和来源面板；相关性去留已经由前四步决定。

这意味着派生索引和关系库不一致时，可能出现有证据正文却缺标题/归属的降级形态。

---

## 12.8 处理器异常时究竟保留哪一版

| 异常点 | 引擎继续使用 | 可能结果 |
|---|---|---|
| Dedup 异常 | 原始扁平 chunks | 重复候选仍在 |
| Fusion 异常 | 去重结果 | 未统一多通道尺度，也未按40截断 |
| Rerank 异常 | RRF/单通道粗排候选 | 可能多于10，无精排分 |
| EvidenceGate 异常 | Rerank 输出 | 不执行整批低分拒绝 |
| MetadataEnrichment 异常 | 已通过证据门的排序结果 | 正文可用，但 doc metadata 可能缺失 |

这种策略优先“尽量给下游已有候选”。它提升故障可用性，也意味着调用方不能只看数组非空就断言每个质量阶段都成功执行；Trace/日志需要区分处理器状态。

---

## 12.9 从候选到空结果的三种不同原因

主 Pipeline 看到 `RetrievalContext.isEmpty()` 时会输出固定无结果提示。但在后处理层，空可能来自：

1. 所有通道本来就没有候选；
2. 候选经过处理后为空，例如去重输入为空；
3. Rerank 有分，但整批最高分低于0.2，被 EvidenceGate 清空。

三种前端表现可能相同，治理动作不同：第一种看索引/scope，第二种看通道与处理链，第三种看问题覆盖和阈值校准。源码中的 latency、通道统计、精排分布和证据门日志正用于区分它们。

---

## 12.10 一条候选的分数生命史

假设同一 Chunk 经过完整多通道链：

```text
Vector 返回 score=0.81
Keyword 返回同 id，score=12.4
        ↓ Dedup
保留一条对象；原始 results 仍有两份名次
        ↓ RRF
score=0.09（示意），覆盖原分
        ↓ Rerank
score=0.73
rerankScore=0.73
        ↓ EvidenceGate
读取 rerankScore，不读 score
        ↓ Metadata
只补归属字段，分数与顺序不变
```

面试中能说清这条生命史，比笼统说“项目会重排序”更能证明你真正读过实现。

---

## 12.11 责任边界与设计解读

| 组件 | 负责 | 不负责 |
|---|---|---|
| Dedup | 稳定 key 去重 | 不做语义近重复 |
| Fusion | 多通道名次融合、权重和40条候选上限 | 不判断绝对相关性 |
| Rerank | query-doc 精排并取最终10条 | 不决定知识库 scope |
| EvidenceGate | 判断整批是否有合格精排证据 | 不逐条删除弱块 |
| MetadataEnrichment | 回表补文档归属 | 不改变排名和证据资格 |
| Engine | 有序执行、单处理器异常跳过 | 不保证所有质量阶段都成功 |

从实现可以解读：

- 保留原始 channel results 让“去重实体”和“多路命中信号”可以同时存在；
- `score + rerankScore` 分离避免一把字段承载多种尺度后无法判别；
- 真实精排即使候选少也出分，是为了给证据门提供资格信号；
- 无分放行和处理器异常跳过偏向可用性，代价是需要观测区分降级答案。

---

## 12.12 面试追问与回答骨架

### 问：为什么先去重再做 RRF，不会丢掉多路命中吗？

去重后的 chunks 只保留一个实体，但 Fusion 不靠该列表推断通道贡献，而是重新读取每个 `SearchChannelResult` 的原始名次，所以同一 key 在多路出现仍累计多项 RRF 分。

### 问：RRF 为什么适合混合检索？

余弦、BM25、图谱和 Web 分数量纲不同。RRF只使用各通道相对名次，再用配置权重调话语权，不需要错误地归一化并比较原始值。

### 问：rerank 开启是否一定会有精排分？

不一定。模型路由可 fallback 到 noop，只截断不写 `rerankScore`；若整个处理器抛错，Engine 还会跳过。EvidenceGate 对全批无分采取告警放行。

### 问：EvidenceGate 是逐条阈值吗？

不是。它看本批最高 rerankScore：最高低于0.2时整批丢弃，至少一条过线则整批保留。这是在“库里没答案也会返回最像TopK”之后增加的批级资格门。

### 问：为什么 Metadata Enrichment 最后执行？

只为最终最多10条回表，减少查询；同时元数据不参与相关性排序。普通 chunkId 补 docId/index/name，图谱可按已有 docId 补标题，Web 查不到本地行则保持空。

### 问：后处理器失败会不会整次检索失败？

不会直接失败。引擎捕获单个处理器异常，保留上一阶段 chunks 继续。但结果可能缺去重、精排、证据门或元数据，因此需要 Trace/日志识别降级阶段。

---

## 12.13 源码定位卡

- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/MultiChannelRetrievalEngine.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/postprocessor/SearchResultPostProcessor.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/postprocessor/DeduplicationPostProcessor.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/postprocessor/FusionPostProcessor.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/postprocessor/RerankPostProcessor.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/postprocessor/EvidenceGatePostProcessor.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/postprocessor/MetadataEnrichmentPostProcessor.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/convention/RetrievedChunk.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/convention/RetrievedChunkKey.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/rerank/RoutingRerankService.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/rerank/BaiLianRerankClient.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/rerank/NoopRerankClient.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/service/impl/ChunkMetadataResolver.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/SearchChannelProperties.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/RAGConfigProperties.java`
- `bootstrap/src/main/resources/application.yaml`

---

## 12.14 读完本章，你应该能自己回答

1. `score` 与 `rerankScore` 为什么必须分开？
2. 去重后，RRF 仍怎样知道一个 Chunk 被两条通道命中？
3. k=20 和各通道 weight 分别怎样影响融合？
4. 40条 candidateLimit 与10条 contextTopK 在哪里生效？
5. 真实 rerank、noop fallback、Rerank 处理器异常的结果有何不同？
6. EvidenceGate 为什么可能把10条候选全部清空，也可能在无分时全部放行？
7. 哪些元数据只有最后回表才能得到？

下一章将把这批最终证据变成两种输出：一份进入 Prompt 帮助模型回答，另一份变成 sources/grounding 随消息持久化并供前端追溯。
