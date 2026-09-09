# 附录 D：检索实现备查——读懂原理以后再回到源码

正文第 21～25 章按原理和流程组织。本附录集中保存配置、类名和需要精确区分的实现细节，不要求顺序阅读。项目源码基线仍为 `98894c2c42c015a3c874c6b3c986ac863c85b731`。

## D.1 默认组合与开关

默认向量后端为 `rag.vector.type=pg`，向量通道开启；ES/BM25 和 LightRAG 为可选后端，默认关闭。准确通道前缀是 `rag.search.channels`。

| 能力 | 后端装配配置 | 问答通道配置 |
|---|---|---|
| 向量 | `rag.vector.type=pg` | `rag.search.channels.vector.enabled=true` |
| 关键词 | `rag.keyword.type=none`，可选 `es` | `rag.search.channels.keyword.enabled=false` |
| 图谱 | `rag.graph.type=none`，可选 `lightrag` | `rag.search.channels.graph.enabled=false` |

后端装配与参与问答是两件事：只开启查询开关不会创建全部历史数据，关闭查询通道也不等于撤掉已装配后端的写同步。

源码：[application.yaml](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/bootstrap/src/main/resources/application.yaml)。

## D.2 HNSW 的具体落点

PG 表 `t_knowledge_vector` 使用 `vector(1536)` 字段，Schema 中 HNSW 索引名为 `idx_kv_embedding`；管理类使用 `idx_kv_embedding_hnsw`。命名不同，所以不能把“按名检查存在”理解成无条件检测到了 Schema 的那一个索引。

PG 查询代码发出 `hnsw.ef_search=200` 与 `hnsw.iterative_scan=relaxed_order`。前者控制搜索宽度，后者是允许放松顺序的迭代扫描设置。它们是数据库会话设置；源码中调用相邻，不单独证明连接池环境中的实际生效会话和执行计划。本教程没有连接数据库验证这些运行细节。

Milvus 分支显式配置 `M=48`、`efConstruction=200`；不能把它们当成 PG 分支显式采用的建图参数。Milvus 的 `collection_name` 字段另建标量 INVERTED 索引，不是稀疏向量索引。

- [PG 字段与索引](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/resources/database/schema_pg.sql#L614)
- [PG 索引管理](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/PgVectorStoreAdmin.java)
- [PG 写入](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/PgVectorStoreService.java)
- [PG 查询与参数](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/PgVectorRetrieverService.java)
- [Milvus 参数](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/MilvusVectorStoreAdmin.java)

## D.3 ES/BM25 的接线

ES 共享索引默认名为 `rag_keyword_store`。正文为 text，库名和 docId 为 keyword；写入 `ik_max_word`、查询 `ik_smart`。文档 ID 使用 chunk 标识，正文中没有写入向量字段。查询是正文 match 加 collection 范围过滤。

关键词同步装饰器在向量主操作后执行 ES 同步，采用 best-effort；ES 同步失败不回滚向量主操作。冻结源码未见独立的稀疏向量模型生成 / 存储 / 查询链，正文因此用“BM25 词法或稀疏检索”说明它。

- [映射与文本写入](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/keyword/EsKeywordIndexService.java)
- [match 与范围过滤](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/keyword/EsKeywordRetrieverService.java)
- [关键词同步](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/decorator/KeywordSyncingVectorStoreService.java)

## D.4 LightRAG：算法原理和 Java 接入分别看

正文中的实体关系构建与 local/global 检索，参考 LightRAG 原论文及官方实现，用于解释方法。Java 项目负责外部服务接入，不是在仓库里重新实现整套算法。外部服务具体版本的模式扩展和抽取策略可能演进。

本项目通过文档级同步把正文和 `file_source` 发到 `/documents/text`，单个 chunk 的更新 / 删除不单独同步图谱。写同步采用 best-effort。配置注释提及的独立 `ingestion.enabled` 没有在当前属性绑定与同步分支中接线。

检索请求设置 `only_need_context=true`，并请求 references 与 chunk content；结果转成 `RetrievedChunk`。临时图谱分数为按名次递减的 `1/(rank+1)`，不是推理置信度。

当前客户端没有将 collection 集合下发为查询前子图过滤条件，而是全图查询后按来源切分。定向请求量放大三倍，再分主路和补充路；默认有条件地使用 15/5 配额。unmatched 可能参与补充，来源解析失败也会落入这一份，所以这种 scope 策略不是完整的授权或租户隔离机制。

- [图谱写同步接线](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/config/GraphSyncVectorStorePostProcessor.java)
- [文档与片段操作区别](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/decorator/GraphSyncingVectorStoreService.java)
- [请求与结果解析](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/graph/LightRagClient.java)
- [图谱通道与配额](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/channel/GraphSearchChannel.java)
- [Neo4j 与 LightRAG 存储配置](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/resources/docker/graphrag/lightrag-neo4j-stack.compose.yaml)

## D.5 融合、精排与证据门

RRF 采用 `weight/(k+rank+1)`，代码 rank 从 0 起；默认 k=20，向量 / 关键词权重 1，图谱 0.8。证据 key 优先为 id，无 id 时使用文本哈希，不是语义去重。正文手算例子假定同一字母的证据身份已对齐；图谱 reference 和向量 chunk 不天然具有同一 id。

预算依次是 `recall-budget=20`、`rerank-candidate-limit=40`、`default-top-k=10`。只有一路结果时不执行跨路 RRF 重排，只做必要截断。

证据门默认阈值 0.2，比较整批最高有效精排分：全部低于门槛时丢弃整批，过线时放行该批。没有有效精排分时告警放行，不逐条保证证据正确。真正的 Rerank 与 Noop 分支详见原第 12 章。

- [共同上下文与并行](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/MultiChannelRetrievalEngine.java)
- [RRF 与候选池](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/postprocessor/FusionPostProcessor.java)
- [证据 key](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/framework/src/main/java/com/nageoffer/ai/ragent/framework/convention/RetrievedChunkKey.java)
- [精排接线](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/postprocessor/RerankPostProcessor.java)
- [证据门分支](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/postprocessor/EvidenceGatePostProcessor.java)

## D.6 Agent 知识工具的实际合同

`search_knowledge` 只有 query 参数，禁止额外字段。`KnowledgeSearchFacade` 执行改写、KB-only 意图、歧义判断、检索与知识答案合成。近期历史帮助改写，合成主要依据本轮知识上下文。

工具不直接复用 RAG HTTP 路径的引用 / sources 装配，合成前会剥离内部 docId 锚点；返回工具文本，不是全部原始候选对象。工具空结果文本与执行异常也是不同语义。

- [工具参数与结果](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/tool/KnowledgeSearchTool.java)
- [内部检索与合成](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/service/KnowledgeSearchFacade.java)

返回 [HNSW](../docs/21-hnsw-vector-index.md)、[BM25](../docs/22-es-bm25-retrieval.md)、[LightRAG](../docs/23-lightrag-graph-retrieval.md)、[检索流程](../docs/24-hybrid-retrieval-to-evidence.md)、[Agent](../docs/25-agentic-rag-interview-focus.md)。
