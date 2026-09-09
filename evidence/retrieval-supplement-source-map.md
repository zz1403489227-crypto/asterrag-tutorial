# 检索增补篇：源码映射与证据边界

## 2026-09-08 教学重写说明

首版过度围绕实现边界展开，没有充分讲清原理。修订版将正文改成建库与查询流程，19 条既有源码事实保留在 [附录 D](../appendices/retrieval-implementation-notes.md)，不再要求读者在原理中途逐项核验。

HNSW 增补分层、插入与候选搜索，参考原论文与 [hnswlib 算法实现](https://github.com/nmslib/hnswlib/blob/master/hnswlib/hnswalg.h)、[参数说明](https://github.com/nmslib/hnswlib/blob/master/ALGO_PARAMS.md)。BM25 增补 TF 饱和、IDF、长度归一化与公式，参考 [Lucene BM25](https://lucene.apache.org/core/9_12_1/core/org/apache/lucene/search/similarities/BM25Similarity.html)。

LightRAG 方法部分参考 [原论文](https://arxiv.org/html/2410.05779v1)、[官方检索实现](https://github.com/HKUDS/LightRAG/blob/main/lightrag/operate.py) 与 [关键词和抽取 Prompt](https://github.com/HKUDS/LightRAG/blob/main/lightrag/prompt.py)，于本轮阅读，用来解释实体关系构建、两级检索与原文回溯。没有将当前外部源码的全部版本特性写成冻结 Java 项目的实现。

人物、关系图、搜索距离、BM25 和 RRF 数字是自编教学材料，用于演示机制；不复制论文实验，不转用其性能结论。本轮语义审读与文件检查结果见 `reviews/retrieval-teaching-rewrite.md`。

日期：2026-09-08。项目基线：`98894c2c42c015a3c874c6b3c986ac863c85b731`。本次本地源码与远程冻结源码的 HEAD 已核对，工作树干净。没有运行产品、连接数据库或调用模型。

## 论断如何回到源码

机器可读逐条映射见 [retrieval-supplement-claims.csv](retrieval-supplement-claims.csv)。每条包含章节、源码路径、精确源码片段和事实摘要；源码片段用于检查定位未漂移，不代表自动证明整段语义。正文保留冻结 GitHub 链接，可直接阅读上下文。

| 章节 | 人工复核重点 |
|---|---|
| 21 | PG vector(1536) 与 HNSW DDL；PG / Milvus 参数不能串用；写入与索引维护分工；SQL 会话参数发出不冒充实测生效 |
| 22 | ES content=text，无向量字段；match + 库过滤；默认双开关；best-effort 同步；稀疏向量链负向检索范围 |
| 23 | type 条件与通道 enabled；文档级同步及 chunk 限制；only_need_context；全图查询结果侧切分与补充配额；外部服务版本边界 |
| 24 | key 去重与原始排名；RRF k=20、权重 1/1/0.8；20/40/10；批级证据门及无分放行 |
| 25 | query-only schema；工具内部改写、KB-only、歧义、检索、LLM 合成；不走直接 RAG 引用合同；贡献归属 |

负向查找“未见独立稀疏向量链”覆盖生产代码 `framework/src/main`、`infra-ai/src/main`、`rag/src/main`、`agent/src/main` 与 `resources/database`，查找词包括 sparse、sparsevec、sparse_vector、SPLADE、SparseFloatVector。该结论限定本项目冻结生产源码，不外推为外部数据库或 LightRAG 不支持此能力。

## 算法背景不能冒充项目实现

HNSW 的分层图直觉参考 [原论文](https://arxiv.org/abs/1603.09320)，PG 操作符与参数语义参考 [pgvector 官方文档](https://github.com/pgvector/pgvector)。ES 字段语义参考 [text 映射](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/text)，默认打分参考 [similarity 文档](https://www.elastic.co/docs/reference/elasticsearch/index-settings/similarity)。LightRAG 的背景入口是 [官方项目](https://github.com/HKUDS/LightRAG)。以上于 2026-09-08 查阅，用于背景说明，不冻结或宣称已经审计其当前全部实现。

正文没有用 LightRAG 当前主分支替代本项目集成代码，没有填充未经确认的固定跳数、抽取算法、社区摘要或图谱推理正确率。

## 本轮文档检查

运行 `scripts/audit-tutorial.py` 覆盖全书 26 章、附录、导航与旧源码映射；运行 `scripts/audit-retrieval-supplement.py` 额外核对增补源码片段、冻结代码链接、错误配置前缀与 RRF 手算。检查对象是教程和只读源码，不是产品行为测试。

实际结果与同步状态记录在 [增补静态复核](reviews/retrieval-supplement-audit.md) 和 `PROGRESS.md`。旧 692 项检查结果属于旧版记录，不沿用为本次结果。
