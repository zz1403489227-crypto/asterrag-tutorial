# 第 7 章：从结构块到可检索索引——分块、向量化与多落点写入

> 本章回答一个贯穿 RAG 的核心问题：解析器已经把文档变成 `Block`，系统怎样在尽量保留结构的前提下生成 `Chunk`，又怎样把同一批块写进关系库和检索后端？
>
> 阅读目标不是记住所有类名，而是能够从一次 `DefaultIngestionKernel` 调用出发，解释数据形态、分块决策、向量约束、写入顺序和一致性边界。

## 7.1 先把整条链路看成五次“形态变化”

上一章已经看到，固定摄取内核依次执行解析、分块、向量化、加工、索引写入。本章只把中间三段展开：

```text
ParsedDocument.blocks
        │
        ▼
按 Block 类型产生 ChunkDraft
        │  尚无 chunkId，也尚未最终拼好 embeddingText
        ▼
ChunkPacker 按章节边界打包
        │
        ▼
ChunkAssembler
        │  分配 ID / index，区分 content 与 embeddingText
        ▼
ChunkEmbeddingService
        │  用 VectorTarget 指定的模型生成并校验向量
        ▼
List<EmbeddedChunk>
        │
        ▼
ChunkIndexWriter
   ├── RelationalChunkSink → t_knowledge_chunk
   └── VectorChunkSink     → VectorStoreService 装饰器链
                                ├── PostgreSQL / Milvus
                                ├── 可选 Elasticsearch 同步
                                └── 可选 LightRAG 同步
```

这里有三个必须先记住的边界：

1. **解析块不是检索块。** `Block` 表达原文结构；`Chunk` 才是检索和展示的基本单元。
2. **展示文本不是向量文本。** `content` 尽量保留原貌，`embeddingText` 可以补章节上下文、去掉 URL 噪声或把表格改写成适合语义检索的文本。
3. **“一次调用多个落点”不等于所有外部系统都具备数据库事务原子性。** 这要在 7.8 节单独拆开。

---

## 7.2 用户选择的不是“切法”，而是一组预算

入口 `ChunkingService.chunk(blocks, budget)` 只有两个分支：

```java
if (budget.isWholeDocument()) {
    return wholeDocument(blocks);
}
return blockAwareChunkerDispatcher.dispatch(blocks, budget);
```

这意味着当前源码并没有暴露诸如“递归字符切分”“语义切分”“按标题切分”等并列策略供用户选择。用户能影响的是 `ChunkBudget`，切法由 `Block` 类型和固定调度规则决定。

### 7.2.1 `ChunkBudget` 的四个量

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `maxChars` | 1024 | 目标块大小，不是所有结构单元的绝对硬上限 |
| `overlapChars` | `maxChars / 8`，默认 128 | 长文本相邻片的重叠量，同时也是寻找自然断点的最大回看距离 |
| `rowsPerChunk` | 50 | 表格类块每片最多容纳的数据行数 |
| `toleranceFactor` | 3 | 为保护一个完整语义单元，最多允许目标大小按倍数放宽 |

源码还设置了构造期约束：普通模式下 `maxChars` 不得超过 8192，`rowsPerChunk` 不得超过 1000，`overlapChars` 必须落在 `[0, maxChars)`，容忍倍数必须在 1 到 8 之间。`toleranceChars()` 最终又被 8192 封顶。

因此默认预算的两条线分别是：

```text
目标线 maxChars       = 1024
完整性容忍线 tolerance = min(1024 × 3, 8192) = 3072
```

`maxChars` 指导“尽量多大”，`toleranceChars` 判断“为了不破坏完整结构，最多能容忍多大”。把二者都理解成硬切点，会误读后面的列表、代码和章节打包逻辑。

### 7.2.2 整文档模式是一枚哨兵

`ChunkBudget.wholeDocument()` 用 `Integer.MAX_VALUE` 表示“不分块”。在这条分支里，`BlockTextRenderer` 直接渲染所有 `Block`，然后 `ChunkAssembler` 生成唯一一个块。元数据只取首个 `Block` 的 provenance。

这不是另一套可扩展分块算法，而是入口里的一个特殊分支。面试时若被问“系统有哪些分块策略”，准确说法是：**当前入口有整文档单块和按 Block 类型分发两条路径；普通路径的细粒度切法由结构类型决定，用户配置的是预算。**

---

## 7.3 普通路径：先按结构切，再按章节装

`BlockAwareChunkerDispatcher` 在构造期收集所有 `BlockChunker<?>`，建立“精确 Block 类 → chunker”的注册表。若两个实现认领同一个类，应用启动时就抛出注册冲突；运行时遇到无人认领的 Block 类型也会失败。

它的主流程可以缩成三步：

```text
逐个 Block 分发 → 得到有序 ChunkDraft
        ↓
ChunkPacker 按节打包草稿
        ↓
ChunkAssembler 统一生成成品 Chunk
```

标题需要提前处理：`HeadingHandler` 先更新当前章节路径，再把标题本身交给 `HeadingChunker`。这样标题草稿与紧随其后的正文拥有同一条 outline path，后面的 `ChunkPacker` 才能自然把它们看成同一节。

### 7.3.1 为什么先产出 `ChunkDraft`

`ChunkDraft` 是切分和合并阶段的中间形态，包含：

- `content`：展示原貌；
- `embeddingBody`：可选的检索正文；为空时回落到 `content`；
- `metadata`：章节路径、资产、来源等；
- `piece`：是否是一个 Block 被切开的其中一片；
- `heading`：是否带标题，供后面的分节使用。

草稿阶段故意没有 `chunkId` 和最终 `embeddingText`。原因很具体：如果先给每个小片拼好章节前缀，再把多个成品块合并，前缀就会重复；如果先发 ID 和序号，合并后还要重新编号。于是源码把“切、并”和“定型”分成两个阶段。

---

## 7.4 不同 Block 为什么不能共用一种切法

下表是当前源码中的实际映射。它不是教学上的理想化分类，而是 `BlockChunker` 实现所表达的规则。

| Block 类型 | 当前切法 | 展示文本与检索文本的差异 |
|---|---|---|
| `HeadingBlock` | 一个标题生成一个标题草稿 | 展示保留 Markdown `#`；检索正文只保留标题文字 |
| `ParagraphBlock` | 体量不超过容忍线时保持完整；超出后交给 `TextSplitter` | 通常相同 |
| `ListBlock` | 以完整列表项为单位贪心分组，不从列表项中间切开 | 通常相同 |
| `TableBlock` | 重复表头，受行数和字符预算共同约束 | 展示为 Markdown 表格；检索正文将每行写成“列名: 值” |
| `HtmlTableBlock` | 以 `<tr>` 为切口，片段重复首行及开闭标签 | 保留 HTML，不从标签中间截断 |
| `ImageBlock` | 一张图片一个草稿 | 展示为描述加 Markdown 图片；检索正文优先用描述，避免 URL 噪声 |
| `CodeBlock` | 代码块作为完整结构单元处理 | 保留代码块表达 |

### 7.4.1 段落：只有真的过长才进入字符切分

`ParagraphChunker` 先看整个段落是否超过 `toleranceChars()`。没有超过就保持完整，即使它已经大于目标 `maxChars`；只有超过容忍线，才用 `TextSplitter.split(text, maxChars, overlapChars)` 切开。

`TextSplitter` 也不是裸 `substring`：它先规范化文本，修复被软换行打断的 URL 和 CJK 词语，再从目标位置向前寻找自然边界，优先级是：

```text
换行 → 中文句末标点（。！？）→ 英文句末标点（.!? 且后接空白）→ 目标下标
```

重叠量同时限制回看的距离。切完后的相邻片有重叠，并被标成 `piece=true`，告诉打包器不要擅自把它们重新粘回去。

### 7.4.2 表格：人要看表，向量更适合读键值

`TableChunker` 的价值不只是“按若干行切表格”。同一片会构造两份文本：

```text
content：
| 产品 | 保证金 |
| --- | --- |
| A | 1000 |

embeddingBody：
产品: A；保证金: 1000
```

前者适合前端预览和回填 LLM，后者给列名与单元格建立明确语义关系。每个切片都会重复表头，因此被单独召回时仍可解释列值。

HTML 表格则采取另一种保真路径：沿 `<tr>` 切分，重复首行和外层标签，避免从标签内部截断。由此也能看出“结构感知”的含义：不是所有结构都统一转成纯文本后再切。

### 7.4.3 图片：检索入口是描述，不是地址

图片块的展示文本可以包含 Markdown 图片 URL，但向量正文优先采用图片描述。URL 对用户查看资源有用，对语义向量通常是噪声。这个差异会一直保留到 `embeddingText`；若打包器在合并时一律取 `content`，图片块的优化就会丢失，所以 `ChunkDraft` 还专门提供 `hasExplicitBody()`。

---

## 7.5 `ChunkPacker`：章节边界是候选切口，不是见标题就切

逐 Block 切分以后，往往会得到许多过小草稿。`ChunkPacker` 负责把它们装成最终体量。它先以标题为界划分“节”：一个标题开始一节，首个标题之前的散块自成一节。

之后遵循两级规则：

1. **整节不超过容忍线时，整节是原子的。** 它可以和当前缓冲区合并；装不进目标大小时，章节边界才成为真正切口。
2. **整节超过容忍线时，才进入节内打包。** 已经由某个 chunker 切出的 `piece` 或自身达到目标大小的草稿会原样落块，避免取消表格行数限制或把带重叠的段落片又合回去。

最小块大小取 `maxChars / 4`，默认是 256 字符。结尾残留若太小，且和前一块合并后不超过容忍线，就向前合并，避免二十来字的碎屑单独消耗一个 topK 名额。

这里还存在一个很细但很实用的“前导语”规则：如果大表格或代码块前有一小段说明，例如“保证金单位为元”，打包器会尝试把这段说明捎进大块。否则检索入口与真正内容会被分到两个块里。

### 7.5.1 合并时怎样处理章节路径和资产

合并多个草稿时：

- `content` 和有效检索正文分别拼接；
- assets 取并集；
- outline path 取所有草稿的**公共前缀**；
- provenance 取第一份草稿的来源。

取公共前缀而不是取“最大块”的路径，是因为前导语可能来自上一节。如果强行使用后一节的完整路径，就会把上一节内容错误标到后一节名下。

---

## 7.6 `ChunkAssembler`：同一个块为什么要保留两份文本

打包完成后，`ChunkAssembler.assembleAll` 按列表顺序从 0 分配 `index`，并用雪花算法生成 `chunkId`。成品 `Chunk` 包含：

```text
chunkId
index
content          文档原貌，用于展示和回填上下文
embeddingText    用于嵌入和重建向量
metadata
```

构造器强制 `embeddingText` 非空，因此“忘了提供可嵌入文本”不会静默流到后端。

### 7.6.1 章节路径只补到向量文本

装配器把“正文尚未覆盖的章节路径前缀”补到有效检索正文之前。例如：

```text
outlinePath = [第三章, 退款规则]
content     = 申请需在七日内提交……

embeddingText = 第三章 / 退款规则
                申请需在七日内提交……
```

若块本身已经以“退款规则”标题开头，装配器不会再重复拼同一级标题。这样续块能得到章节语境，首块又不会浪费向量输入空间重复标题。

`content` 不加合成前缀，是为了保持原文展示；`embeddingText` 可以为检索做结构补偿。人工启停或更换嵌入模型时，`ChunkAssembler.restore` 直接读取关系库中保存的 `embedding_text`，不会仅凭展示正文重新猜一遍。

### 7.6.2 元数据有唯一序列化点

`ChunkMetadata.toMap()` 是当前源码的统一扁平化入口。它会输出资产、`source_file`、`sheet_name` 和 extras；结构化字段最后写入，因此不能被 extras 覆盖。`doc_id`、`chunk_index` 等文档级字段由具体索引后端补充。

需要注意：当前 provenance 只记录源码中实际存在的 `sourceFile` 和 `sheetName`，不能把页码、坐标框等尚未进入数据模型的信息说成已经可追溯。

---

## 7.7 向量化：模型、分区和维度是一份不可缺省的落点身份

`ChunkEmbeddingService` 不接受一个可空的模型名再回落系统默认值，而是要求完整 `VectorTarget`：

```java
public record VectorTarget(
    String partition,
    String embeddingModel,
    int dimension
) { ... }
```

三者的职责分别是：

- `partition`：逻辑分区键，来自知识库 `collection_name`；
- `embeddingModel`：该知识库选择的嵌入模型；
- `dimension`：部署级物理向量空间的硬约束。

`VectorTargetResolver` 把知识库配置与部署配置合成为这份目标。`ChunkEmbeddingService` 批量提交所有 `embeddingText` 后，逐项校验：返回条数是否与块数一致、每条向量是否存在、实际维度是否等于目标维度。任何一项不满足都会在写库之前失败。

这体现了一个重要分层：**知识库可以选择模型和逻辑分区，但底层物理空间的列宽仍受部署约束。** 当前 PostgreSQL 建表语句把 `embedding` 定义为 `vector(1536)`，默认配置 `rag.default.dimension` 也是 1536。若换成输出维度不同的模型，不是改一个模型名就够了，还要调整部署维度并重建物理向量空间。

面试官若问“为什么维度不直接从模型返回值推断”，可以回答：数据最终写入固定维度的物理空间，提前用显式契约校验能让错误停在业务边界，而不是漂移到数据库类型转换阶段。

---

## 7.8 多落点写入：顺序清楚，一致性边界也要讲清楚

`ChunkIndexWriter` 注入全部 `ChunkSink`，并在 `TransactionOperations` 回调中按顺序调用。当前两个一等落点是：

1. `RelationalChunkSink`，标为最高优先级；
2. `VectorChunkSink`，标为最低优先级。

### 7.8.1 关系库落点保存什么

`RelationalChunkSink.replaceDocument` 先删除该文档旧块，再把新块批量写进 `t_knowledge_chunk`，保存同一个 `chunkId`、顺序、展示正文、内容哈希、字符数、token 数和 `embedding_text`，并把 `enabled` 置为 1。

这张表不只是前端预览缓存。持久化 `embedding_text` 使系统以后可以在不重新解析文档的情况下重算向量，也使人工编辑块时能够明确更新检索文本。

### 7.8.2 向量落点的“先删后建”

`VectorChunkSink.replaceDocument` 先调用 `deleteDocumentVectors(partition, docId)`，若新块非空再调用 `indexDocumentChunks`。默认 `rag.vector.type=pg` 时，`PgVectorStoreService` 把数据写入 `t_knowledge_vector`：

```text
id               与关系库 chunkId 相同
collection_name  逻辑分区
content          展示文本
metadata         ChunkMetadata.toMap() + doc_id + chunk_index
embedding        1536 维向量（当前建表）
```

表上有 collection 索引、JSONB GIN 索引以及使用余弦距离的 HNSW 向量索引。后续向量召回并不是扫描 `t_knowledge_chunk`，而是由 `PgVectorRetrieverService` 在 `t_knowledge_vector` 中按 collection scope 查询，并计算余弦相似度。

### 7.8.3 装饰器链上的关键词和图谱同步

注入 `VectorChunkSink` 的 `VectorStoreService` 可能被装饰：

```text
GraphSyncingVectorStoreService
    ↓
KeywordSyncingVectorStoreService
    ↓
PgVectorStoreService 或 MilvusVectorStoreService
```

只有相应 Bean 存在时装饰器才注册。当前默认配置是 `keyword.type=none`、`graph.type=none`，因此默认不会同步 Elasticsearch 或 LightRAG。

两种同步在源码中都是尽力而为：主向量写入完成后，关键词或图谱失败只记录日志，不把主写入判为失败。图谱同步以文档为单位，删除后再写整篇；单块人工修改并不会同步图谱。

还有一处值得在面试中体现源码审慎：`application.yaml` 的图谱注释提到一个“下方 ingestion.enabled”，但当前 `GraphProperties` 和同段 YAML 并没有这个属性。实际写入装饰器由 `LightRagClient` Bean 是否存在决定，也就是 `rag.graph.type=lightrag` 是否使客户端生效。教程不能把这句已经漂移的注释当作现有配置事实。

### 7.8.4 一致性矩阵

| 落点组合 | 当前保障 | 不能承诺什么 |
|---|---|---|
| `t_knowledge_chunk` + 默认 PostgreSQL pgvector 表 | 两者都经 JDBC 写入同一 PostgreSQL 数据源，并处于 `ChunkIndexWriter` 打开的 Spring 事务中；异常可触发本地事务回滚 | 不能由此推导对象存储等其他资源也在同一事务 |
| 关系库 + Milvus | 方法仍在 Spring 事务回调中调用，但 Milvus 是外部系统 | Spring 数据库事务不能回滚已发给 Milvus 的远程副作用 |
| 主向量后端 + Elasticsearch 关键词 | 关键词装饰器为尽力同步 | ES 失败不会回滚主向量写入，也不保证强一致 |
| 主向量后端 + LightRAG 图谱 | 图谱装饰器为尽力同步 | LightRAG 失败不会回滚主向量写入；单块修改也不自动重建图谱 |
| 数据库/检索后端 + 对象存储 | 删除文档时还会尝试删除文件 | 文件删除不属于数据库本地事务，源码采用安静删除/补偿式处理 |

因此，`ChunkIndexWriter` 注释里的“全部落点在同一个事务里”必须结合具体资源理解：它对加入同一 Spring 数据库事务的本地 JDBC 资源成立；对 Milvus、Elasticsearch、LightRAG、S3/OSS 这类外部系统，不能扩大解释成分布式原子事务。

---

## 7.9 替换、删除、启停和人工编辑分别怎样维护索引

理解正常摄取还不够，面试官经常会反问：“文档后来被删了、停用了、块被改了，向量怎么办？”

### 7.9.1 整文档重新摄取

主链使用 replace 语义：关系块和文档向量都先删旧数据，再写同一批新 `chunkId`。不是在旧块上逐条猜测增量差异。

### 7.9.2 删除文档

`KnowledgeDocumentServiceImpl.deleteDocument` 会先拒绝正在 `RUNNING` 的文档，然后删除调度/日志、软删除文档记录，并经 `ChunkIndexWriter.deleteDocument` 清理关系块和向量，最后尝试删除对象存储文件。

这条流程明确体现了两类状态：数据库和默认 pgvector 可在本地事务中协作；对象文件的删除是外部副作用，不应被描述成同一原子事务。

### 7.9.3 禁用与重新启用

禁用文档会调整文档和块的 enabled 状态，并清理向量；启用时先从关系库读取已保存的 `embedding_text`，在事务外计算新向量，然后在事务中更新 enabled 并重建向量。把耗时的模型调用放在数据库事务外，可以避免长时间占用事务；但若向量后端是外部系统，依旧不能宣称跨系统绝对原子。

### 7.9.4 人工维护单块

`KnowledgeChunkServiceImpl` 支持人工新增、更新和删除单块。人工新增时 `embedding_text=content`；更新时同步刷新正文、哈希、计数、向量文本和向量记录；删除时先删关系记录再删向量。

这里要注意两个边界：

- 单块操作需要保持关系主键与向量主键使用同一个 `chunkId`；
- 图谱同步是文档级装饰路径，单块编辑不会自动同步整篇图谱。

---

## 7.10 文档显示 `SUCCESS`，到底说明了什么

在固定摄取内核的主路径中，只有 `ChunkIndexWriter.replaceDocument(...)` 正常返回以后，`KnowledgeDocumentServiceImpl.runChunkTask` 才会把分块日志和文档状态更新为 `SUCCESS`。因此在默认 PostgreSQL 路径下，它至少说明：解析、分块、向量化、加工以及本次关系块/pgvector 写入调用已经成功完成。

但 `SUCCESS` 仍不等于“以后任何问题一定能召回这篇文档”。实际召回还取决于：

- 文档和块是否仍处于 enabled 状态；
- 查询选中的知识库 scope 是否包含该 collection；
- 查询嵌入模型与索引向量空间是否相容；
- 相似度阈值、topK 和融合预算；
- 当前启用了哪些检索通道；
- 查询重写和意图路由有没有把作用域收窄到别处。

还要加上前述外部同步边界：关键词或图谱尽力同步失败时，主流程仍可能成功。准确表述是：**`SUCCESS` 是这次主摄取链成功完成的业务状态，不是对所有检索模态和所有未来查询结果的无限保证。**

---

## 7.11 谁负责什么：一张责任表收住本章

| 组件 | 负责 | 不负责 |
|---|---|---|
| `ChunkingService` | 选择整文档或 Block-aware 入口 | 不解析文件，不生成向量 |
| `BlockChunker` 实现 | 按具体 Block 结构产生草稿 | 不分配最终 ID，不跨章节打包 |
| `ChunkPacker` | 以章节为候选边界控制最终体量 | 不重做具体结构的切分规则 |
| `ChunkAssembler` | 分配 ID/index，组装 `embeddingText` | 不调用嵌入模型 |
| `ChunkEmbeddingService` | 批量嵌入并校验条数与维度 | 不决定知识库目标，也不落库 |
| `VectorTargetResolver` | 合成分区、模型、部署维度 | 不执行向量计算 |
| `ChunkIndexWriter` | 组织所有一等 `ChunkSink` 和本地事务边界 | 不创造分布式事务 |
| `RelationalChunkSink` | 保存可管理、可展示、可重嵌入的关系块 | 不做相似度检索 |
| `VectorChunkSink` | 把同一批块交给向量服务及可选装饰器 | 不保证所有外部副作用强一致 |

---

## 7.12 源码事实与设计解读要分开

下面是可以直接由代码确认的事实：

- 普通分块由 Block 类型注册表分发；
- 默认预算是 1024 字符、128 重叠、50 行、3 倍容忍；
- `content` 与 `embeddingText` 分开保存；
- `VectorTarget` 强制携带分区、模型和维度；
- 默认向量后端为 PostgreSQL，默认维度为 1536；
- 关系 sink 先执行，向量 sink 后执行；
- 关键词和图谱装饰器异常不会使主写入回滚。

下面是基于结构的设计解读，应使用“这样做可以……”而不是伪装成作者原话：

- 让用户只调预算，可以减少分块策略组合爆炸；
- 把结构切分和章节打包分层，可以避免通用打包器破坏表格、列表等结构规则；
- 分离展示文本与向量文本，可以同时维护可读性和检索语义；
- 显式 `VectorTarget` 可以把知识库级选择与部署级物理约束放在一个可校验契约里；
- 将 ES/LightRAG 设为尽力同步，可以让附加检索模态的故障不阻断主向量摄取，但代价是接受最终一致或缺失。

---

## 7.13 面试追问与回答骨架

### 问：这个项目是固定长度切分吗？

不是简单固定长度切分。用户设置字符、重叠和表格行数预算，但普通路径先根据 `Block` 类型选择切法，再以标题划节并打包。只有超长段落才进入带自然边界和重叠的字符切分。

### 问：为什么 `content` 和 `embeddingText` 要分开？

`content` 服务于展示和回填，应尽量保留原文；`embeddingText` 服务检索，可以补章节路径、把表格转成键值语义、去掉图片 URL 噪声。关系库保存两者，后续换模型时可直接重嵌入而不用重解析。

### 问：同一批块怎样保证关系库和向量库对应？

`ChunkAssembler` 先为每块生成唯一 `chunkId`，`EmbeddedChunk` 携带同一个块，两个 sink 都以该 ID 写入。默认 pgvector 与关系表同处 PostgreSQL JDBC 事务；若改用 Milvus，ID 仍对应，但外部副作用不受本地事务原子回滚保障。

### 问：为什么先删再写，而不是逐条更新？

当前摄取采用整文档 replace 语义：一次解析可能改变块数、边界和所有后续 index。先按文档删旧块，再写完整新集合，状态模型更简单。代价是外部后端需要认真处理失败补偿和一致性窗口。

### 问：为什么嵌入维度是显式参数？

模型是知识库级选择，物理列宽是部署级约束。显式 `VectorTarget` 在写库前校验二者是否兼容，可以避免到 pgvector/Milvus 类型阶段才暴露错误。

### 问：`ChunkIndexWriter` 用了事务，为什么还说可能不一致？

Spring 本地事务只能可靠管理加入该事务的资源。默认 PostgreSQL 关系表和 pgvector 表共享 JDBC 数据源，可以共同回滚；Milvus、ES、LightRAG、对象存储是外部系统，不会因为本地数据库回滚自动撤销远程副作用。源码里的 ES/图谱同步还明确是 best effort。

### 问：摄取 `SUCCESS` 是否等于一定能检索到？

不等于。它表示主摄取链和主索引写入已经完成；实际查询还受 enabled、collection scope、查询向量、topK、阈值和通道开关影响，附加关键词/图谱同步也可能独立失败。

---

## 7.14 源码定位卡

本章结论以以下源码为准：

- `rag/src/main/java/com/nageoffer/ai/ragent/core/chunk/ChunkingService.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/core/chunk/model/ChunkBudget.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/core/chunk/blockaware/BlockAwareChunkerDispatcher.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/core/chunk/blockaware/ChunkPacker.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/core/chunk/blockaware/`（`BlockChunker`、`ParagraphChunker`、`HeadingChunker`、`ListChunker`、`TableChunker`、`HtmlTableChunker`、`ImageChunker`、`CodeChunker`）
- `rag/src/main/java/com/nageoffer/ai/ragent/core/chunk/text/TextSplitter.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/core/chunk/model/ChunkDraft.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/core/chunk/model/ChunkAssembler.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/core/chunk/model/ChunkMetadata.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/core/ingest/VectorTarget.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/core/ingest/embed/ChunkEmbeddingService.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/support/VectorTargetResolver.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/core/ingest/sink/ChunkIndexWriter.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/sink/RelationalChunkSink.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/sink/VectorChunkSink.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/PgVectorStoreService.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/decorator/KeywordSyncingVectorStoreService.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/decorator/GraphSyncingVectorStoreService.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/service/impl/KnowledgeDocumentServiceImpl.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/service/impl/KnowledgeChunkServiceImpl.java`
- `bootstrap/src/main/resources/application.yaml`
- `resources/database/schema_pg.sql`

---

## 7.15 读完本章，你应该能自己回答

1. 为什么项目把 `Block → ChunkDraft → Chunk → EmbeddedChunk` 分成四种对象？
2. 默认 1024 字符为什么不是所有 Block 的硬切上限？
3. 表格和图片的 `content` 与 `embeddingText` 分别是什么？
4. `ChunkPacker` 为什么使用章节公共前缀，为什么会把小尾巴向前合并？
5. `VectorTarget` 里的 partition、model、dimension 分别属于哪一层约束？
6. 默认 PostgreSQL 路径和 Milvus 路径的一致性承诺有何不同？
7. 为什么文档摄取 `SUCCESS` 后，某次查询仍可能召回不到它？

如果这七个问题能沿真实类和状态边界完整回答，你已经不是在背“RAG 要分块、要向量化”，而是在解释 AsterRAG 这一版源码如何把结构文档变成可管理、可检索的数据。
