# 第 10 章：该查哪个库——意图树、歧义引导与知识库作用域

> 第 9 章把一句自然语言变成一个主问题和若干子问题。本章继续回答：每个子问题属于哪类需求，是查知识库、调用 MCP、直接系统回应，还是先请用户澄清？如果要查知识库，范围应收窄到哪些 collection？
>
> “识别意图”和“计算检索作用域”是相邻但不同的两层：前者给节点打分，后者把可靠的 KB 节点映射成有效知识库范围。

## 10.1 一次意图解析的输入和输出

`IntentResolver.resolve(RewriteResult)` 对每个 `subQuestion` 并行分类，输出：

```java
public record SubQuestionIntent(
    String subQuestion,
    List<NodeScore> nodeScores
) {}
```

可以把它理解成：

```text
“产品 A 如何退款？”
    ├── [KB: 产品A/退款, 0.91]
    └── [KB: 通用售后,   0.48]

“查一下今天汇率”
    └── [MCP: exchange-rate-tool, 0.94]
```

`NodeScore` 不是最终检索分数，它是“子问题与意图叶子节点”的匹配分。后续向量相似度、RRF 和 rerank 都是另一类评分，不能混用。

---

## 10.2 意图树到底保存什么

持久配置在 `t_intent_node`，运行时映射为 `IntentNode`。节点包含：

- `id`、name、description、examples；
- level、parentId、fullPath；
- kind：`KB`、`SYSTEM` 或 `MCP`；
- KB 绑定的 `collectionNames`，以及兼容旧字段 `collectionName`；
- MCP 的 `mcpToolId`；
- 可选 node-level `topK`；
- prompt snippet/template 和 MCP 参数提取模板。

只有叶子节点参加分类。中间节点用于组织“根 → 分类 → 主题”的路径，不直接成为本次 `NodeScore`。

### 10.2.1 三种 kind 是三条业务路由

| kind | 表达什么 | 后续去向 |
|---|---|---|
| `KB` | 文档知识类需求 | 映射 collection，进入多通道知识检索 |
| `MCP` | 需要实时工具/外部交互 | 进入参数提取和 MCP 工具调用 |
| `SYSTEM` | 问候、身份、反馈等系统交互 | 全部子问题均为纯 SYSTEM 时跳过检索，直接生成系统回应 |

分类树不是“知识库目录”的别名。一个 KB 节点可以绑定多个 collection；SYSTEM 没有知识库；MCP 的关键绑定是 tool ID。

---

## 10.3 树从数据库到分类 Prompt 的路径

`DefaultIntentClassifier` 同时实现 `IntentClassifier` 和 `IntentNodeRegistry`。每次调用会：

```text
IntentTreeCacheManager 从 Redis 取树
        ↓ 缓存为空
数据库 t_intent_node 加载并回填 Redis
        ↓
临时扁平化 allNodes / leafNodes / id2Node
        ↓
把所有叶子的 id、path、description、examples、type、toolId 写入 Prompt
```

源码注释将其称为“串行实现”：单个子问题的一次分类把所有叶子放进一份 Prompt，请 LLM 一次性选择和打分；多个子问题之间由 `IntentResolver` 并行。

分类请求 temperature 0.1、topP 0.3、thinking false，使用 `LLMService.chat(request)` 的标准调用，而不是第 9 章明确指定的 FAST 档。

### 10.3.1 模型不能创建不存在的节点

期望结果是 JSON 数组，元素含 `id` 和 `score`。解析器只接受当前 `id2Node` 中存在的 ID，未知 ID 被跳过；返回对象外包一层 `{"results": [...]}` 也能容错。

LLM 调用失败、JSON 格式异常或没有意图树时，分类器返回空列表，不随便选择“最像”的节点。

这是一种闭集分类：模型负责在已配置叶子中打分，不拥有修改路由表的权力。

---

## 10.4 两级数量与分数约束

分类器先按 score 降序返回。`IntentResolver.classifyIntents` 再执行：

```text
score >= 0.35
每个子问题最多取 3 个
```

其中 0.35 是 `RAGConstant.INTENT_MIN_SCORE`，3 是 `MAX_INTENT_COUNT`。

多个子问题汇总后，如果意图数超过 3，`capTotalIntents` 尝试：

1. 每个子问题至少保留一个最高分意图；
2. 剩余总配额按全局分数从高到低分配。

这避免第一个子问题占光全部名额。但源码还有一个应准确说明的边界：当**有意图的子问题本身超过 3 个**时，“每个子问题保底一个”已经可能超过 MAX=3，当前方法不会再砍掉这些 guaranteed intents。因此常规少量子问题下它是总量上限；不能无条件宣称任何输入都严格最多 3 个。

若某个子问题分类抛异常，`IntentResolver` 捕获后只让该子问题降级为空意图，其他并行子问题照常 join。

---

## 10.5 歧义引导：不是“两个分数接近就弹窗”

意图解析后，Pipeline 先调用：

```java
guidanceService.detectAmbiguity(
    rewrittenQuestion,
    subIntents
)
```

当前 `IntentGuidanceService` 的真实判定比简单阈值复杂：

1. `rag.guidance.enabled` 必须为 true；YAML 未显式覆盖时类默认 true；
2. 必须恰好只有一个子问题；
3. 至少有两个 score ≥ 0.35 的 KB 候选；
4. 以最高分候选为主，沿 parentId 构造根到叶路径；
5. 候选叶子同名，或分叉后的路径出现用户问题实际提到的同名节点；
6. FAST 档 `AmbiguityLLMChecker` 再确认确有歧义。

例如“数据安全怎么做”可能同时命中：

```text
集团信息化 > OA系统 > 数据安全
集团信息化 > 保险系统 > 数据安全
```

规则层先发现分叉后的“数据安全”同名，LLM 再判断用户是否真的需要二选一。若确认，系统生成最多 6 个路径选项的澄清 Prompt。

### 10.5.1 失败时选择放行，而不是阻断

歧义确认返回非法 JSON、缺少 `ambiguous` 或调用失败时，`AmbiguityLLMChecker` 返回 false。也就是跳过澄清，继续联合检索，而不是反复要求用户确认。

这是源码事实；可以把它解读为只读 RAG 中“误阻断”比“多查几个库”代价更高。

### 10.5.2 两个旧阈值当前不参与判断

`GuidanceProperties` 仍保留：

- `ambiguityScoreRatio=0.8`；
- `ambiguityMargin=0.15`。

字段注释明确说明它们当前不参与判定，仅用于兼容旧 YAML。现在的歧义逻辑是“路径重名规则 + LLM 确认”。面试中若照着配置字段说“两个分数差小于 0.15 就引导”，就是与源码不一致。

---

## 10.6 引导是 Pipeline 的第一次业务短路

若 `GuidanceDecision.isPrompt()`：

```text
callback.onContent(guidancePrompt)
callback.onComplete()
return
```

后面不会执行 SYSTEM 判断、知识检索或最终 RAG Prompt。这个澄清文本由规则模板直接生成，再经正常 `StreamChatEventHandler` 保存为一条 `NORMAL` assistant 消息。

因此“没有检索”不一定是故障：可能是系统主动判定问题需先澄清。

---

## 10.7 SYSTEM-only 是第二次业务短路

`IntentResolver.isSystemOnly` 的条件非常严格：一个子问题必须恰好只有一条 NodeScore，且 node kind 为 SYSTEM。Pipeline 要求所有子问题都满足，才进入 SYSTEM-only 路径。

此时：

1. 从这些 SYSTEM 节点中取第一个非空 `promptTemplate`；
2. 没有自定义模板则用 `AgentPromptSlot.SYSTEM_CHAT`；
3. 加入完整 history 和 `rewrittenQuestion`；
4. temperature 0.7、thinking false，直接流式调用 LLM；
5. 把返回的 cancellation handle 绑定到 task。

它不执行知识检索，但仍是模型生成，不是把 SYSTEM 节点模板原样回给用户。

混合情况不会走该短路：若一个子问题同时有 SYSTEM 和 KB，或多个子问题中只有部分是 SYSTEM，`allSystemOnly` 为 false。后续检索层只抽取 KB/MCP 意图，SYSTEM 节点不形成知识通道。

---

## 10.8 从意图分到检索 scope，还要过两道闸门

对每个 `SubQuestionIntent`，`MultiChannelRetrievalEngine.buildSearchContext` 单独调用：

```java
retrievalScopeResolver.resolve(List.of(subIntent))
```

所以不同子问题可以得到不同 scope，不是整次请求只能选一组库。

当前默认配置：

```yaml
rag.search.scope:
  min-intent-score: 0.4
  confidence-threshold: 0.6
  supplement-ratio: 0.25
```

前面 `IntentResolver` 已先过滤到 0.35；scope 再只取：

- kind=KB；
- score ≥ 0.4；
- 实际绑定至少一个 collection；
- 同一意图节点跨子问题重复时保留最高分（当前每次只传单子问题，但 Resolver 本身支持列表）。

然后只看这些 KB 意图的**最高分**：

```text
没有有效 KB 意图                 → global
最高分 < 0.6                    → global
最高分 ≥ 0.6 且存在有效绑定库     → directed
```

意图个数不参与“要不要收窄”的判断。多一个低分候选不会让分类凭空更可信。

---

## 10.9 全局 scope 与定向 scope

`RetrievalScope` 保存：

```text
directed
topScore
intents
targetCollections
supplementCollections
```

### 10.9.1 全局模式

`targetCollections` 是全部有效知识库 collection，`supplementCollections` 为空，directed=false。以下情况都走全局：

- 意图分类失败或为空；
- 只有 SYSTEM/MCP，没有有效 KB；
- KB 分数未达 0.6；
- 意图绑定的库已经全部失效。

“无意图”不会直接等于“无检索”。当前策略是低置信时宁可全库查找。

### 10.9.2 定向模式

系统先取意图绑定 collection，再与 `KbCollectionProvider.listActiveCollections()` 求交：

- 交集成为 `targetCollections`；
- 其他仍有效库成为 `supplementCollections`；
- 悬空绑定被记录警告并排除；
- 若交集为空，退回 global。

求交是必要的，因为删除知识库不会自动回写意图节点。若继续把悬空库名传给图谱通道，甚至可能命中未清干净的外部图谱残留。

---

## 10.10 补充路不是再次全库自由竞争

定向模式下，`supplementCollections` 保存“全部有效库减去命中库”。下一章的具体 SearchChannel 会按 `supplement-ratio=0.25` 从自己的召回预算中划出固定份额，给这些未命中库一条保底路。

目的不是把 scope 又变回全局：

```text
75% 左右名额：命中意图库主路
25% 左右名额：其余库保底路
```

如果意图路由判错，正确证据仍有一个固定进入候选池的机会；若所有库自由混排，补充库的弱初始分数可能一个名额也抢不到。

当 `supplement-ratio<=0` 或命中库已经覆盖全部有效库时，补充路关闭。具体取整和每通道预算在第 11 章讲。

---

## 10.11 意图归属和检索来源也不是一回事

定向检索后，系统会根据最终存活 Chunk 的 `collectionName` 推导它属于哪些命中意图：

- 一个库被多个意图绑定，Chunk 可以多归属；
- 补充路库不属于命中意图，证据可以被使用但没有 directed intent 归属；
- 全局 scope 没有 directed intent 归属；
- 归属与 Chunk 是由向量、关键词还是图谱通道捞到无关。

这层归属后续用于 Prompt 规划和 eligible intent IDs。通道回答“怎样找到”，意图归属回答“证据支持哪个业务意图”，不要用 channel name 代替 intent ID。

---

## 10.12 四种主分支一张表收住

| 分类结果 | Guidance | Scope/后续 |
|---|---|---|
| 单子问题、多条同名路径 KB，LLM 确认歧义 | 输出澄清 Prompt | Pipeline 立即完成，不检索 |
| 所有子问题各自仅一条 SYSTEM | 无澄清 | 系统 Prompt + history 直接流式回答 |
| KB 最高有效分 ≥ 0.6 且绑定有效库 | 无澄清 | 定向 target + 可选 supplement |
| 空意图或 KB 置信不足 | 无澄清 | 全部有效库 global 检索 |
| MCP 意图 | 无澄清 | RetrievalEngine 另行提参和调用工具 |
| KB + MCP 混合 | 无澄清 | 同一子问题同时构建知识库与 MCP 上下文 |

---

## 10.13 责任边界与设计解读

| 组件 | 负责 | 不负责 |
|---|---|---|
| `DefaultIntentClassifier` | 叶子闭集、Prompt、LLM 打分解析 | 不决定最终知识库有效性 |
| `IntentResolver` | 子问题并行、0.35 过滤、数量分配、SYSTEM 判定 | 不执行检索 |
| `IntentGuidanceService` | 路径冲突规则、LLM 二次确认、澄清选项 | 不用旧 score ratio/margin 判定 |
| `StreamChatPipeline` | 以 guidance 和 SYSTEM-only 明确短路 | 不改变意图树配置 |
| `RetrievalScopeResolver` | 0.4/0.6 两道 scope 门、有效库求交、target/supplement | 不选择检索通道 |
| `KbCollectionProvider` | 提供当前有效 collection | 不解释意图语义 |

从实现可以解读：

- 闭集 ID 解析防止 LLM 幻造路由目标；
- 低置信时 global 比强行定向更偏召回，代价是搜索范围扩大；
- 路径规则先筛、LLM 后确认，减少每个问题都额外调用歧义模型；
- target 与 supplement 分开，为“准确时收窄、判错时保底”建立显式预算接口。

---

## 10.14 面试追问与回答骨架

### 问：意图树是用向量匹配的吗？

当前默认分类器把所有叶子节点信息一次性写入 Prompt，由 LLM 返回闭集 ID 和 score。`IntentNode.embedding` 已标记 deprecated，只用于向量意图识别测试，不能说主路径使用意图向量库。

### 问：意图识别失败为什么还会检索？

分类失败降级为空意图；scope resolver 把“无有效 KB 意图”解释为低置信，全局检索全部 active collections。它选择召回优先，而不是空意图就裸 LLM。

### 问：系统如何处理歧义？

只对单子问题的多个 KB 候选检查：先寻找分叉后的路径重名，再用 FAST LLM 确认；确认后输出路径选项并短路。旧的 ratio/margin 字段当前不参与判定，LLM 失败则放行检索。

### 问：SYSTEM 意图和 RAG 有什么区别？

若所有子问题都唯一命中 SYSTEM，系统跳过知识检索，用节点自定义或默认 system prompt 加 history 直接流式生成。只要混有 KB/MCP，就不满足 SYSTEM-only 短路。

### 问：定向检索怎样避免意图误判导致零召回？

只有最高有效 KB 分达到 0.6 才收窄；命中库与 active collections 求交；定向后还把未命中有效库放入 supplement，由通道划 25% 左右预算保底。

### 问：为什么意图 score 和向量 score 不能直接比较？

意图 score 衡量问题属于哪个配置节点，决定路由和 scope；向量 score 衡量查询向量与 Chunk 的相似度，决定证据排名。对象、模型和下游用途都不同。

---

## 10.15 源码定位卡

- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/intent/IntentNode.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/intent/NodeScore.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/intent/DefaultIntentClassifier.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/intent/IntentResolver.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/intent/NodeScoreFilters.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/intent/IntentTreeCacheManager.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/guidance/IntentGuidanceService.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/guidance/AmbiguityLLMChecker.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/GuidanceProperties.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/channel/RetrievalScopeResolver.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/channel/RetrievalScope.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/MultiChannelRetrievalEngine.java`
- `rag/src/main/resources/prompt/intent-classifier.st`
- `rag/src/main/resources/prompt/guidance-ambiguity-check.st`
- `rag/src/main/resources/prompt/guidance-prompt.st`
- `bootstrap/src/main/resources/application.yaml`
- `resources/database/schema_pg.sql`

---

## 10.16 读完本章，你应该能自己回答

1. IntentNode 的 KB、MCP、SYSTEM 三种 kind 分别怎样路由？
2. 为什么中间节点不参加分类，模型返回未知 ID 会怎样？
3. 0.35、0.4、0.6 三个阈值分别在哪一层生效？
4. 歧义引导为什么不是简单比较两个 score 的差值？
5. SYSTEM-only 的严格条件是什么，为什么混合意图不会进入？
6. global 和 directed scope 的 target/supplement 分别是什么？
7. 删除知识库以后，为什么 scope 还要把意图绑定与 active collections 求交？

下一章接着展开 `SearchContext`：同一份 scope 和三段预算怎样交给向量、关键词、图谱和 Web 四个通道并行执行，并让单路超时只退化为该路空结果。
