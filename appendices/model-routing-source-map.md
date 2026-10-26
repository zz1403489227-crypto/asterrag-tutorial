# 模型分流的源码定位与估算口径

对应[第 46 章](../docs/46-local-qwen-model-routing.md)。产品基准 `98894c2c42c015a3c874c6b3c986ac863c85b731`；只读核对日期 2026-09-11。下表统计直接业务调用表达式，不计接口声明、供应商转发和测试。行号只对本基准有效。

## 文本模型的 16 处入口

| 编号 | 类与行号 | 调用与用途 |
|---|---|---|
| 1 | [MultiQuestionRewriteService:111](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/rewrite/MultiQuestionRewriteService.java) | FAST，改写和拆分合为一次调用 |
| 2 | [DefaultIntentClassifier:169](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/intent/DefaultIntentClassifier.java) | 默认档位，意图识别；拆分后可能多次执行 |
| 3 | [AmbiguityLLMChecker:78](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/guidance/AmbiguityLLMChecker.java) | FAST，条件触发的歧义判断 |
| 4 | [LLMMcpParameterExtractor:97](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/mcp/LLMMcpParameterExtractor.java) | Workflow MCP 参数提取，不是 Agent 原生工具参数生成入口 |
| 5～6 | [StreamChatPipeline:217、245](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/service/pipeline/StreamChatPipeline.java) | 正常回答与兜底生成的两个分支 |
| 7 | [KnowledgeSearchFacade:99](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/service/KnowledgeSearchFacade.java) | 知识工具内部合成答案 |
| 8 | [RecommendedQuestionGenerator:86](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/service/impl/RecommendedQuestionGenerator.java) | FAST，独立的推荐问题生成入口 |
| 9 | [ConversationTitleGenerator:73](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/service/impl/ConversationTitleGenerator.java) | FAST，新会话标题 |
| 10 | [JdbcConversationMemorySummaryService:213](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/memory/JdbcConversationMemorySummaryService.java) | FAST，固定 RAG 的历史摘要 |
| 11 | [AgentChatServiceImpl:129](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/service/impl/AgentChatServiceImpl.java) | streamEvents 进入 Agent 循环，一次入口可能产生多次推理 |
| 12 | [AgentConversationSummarizer:114](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/memory/AgentConversationSummarizer.java) | STANDARD，Agent 对话摘要 |
| 13 | [AgentMemoryJudge:99](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/memory/AgentMemoryJudge.java) | STANDARD，长期记忆抽取决策 |
| 14 | [AgentMemoryConsolidator:108](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/memory/AgentMemoryConsolidator.java) | STANDARD，长期记忆合并计划 |
| 15 | [EnhancerNode:130](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/ingestion/node/EnhancerNode.java) | FAST 与指定模型，可选入库增强 |
| 16 | [EnricherNode:146](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/ingestion/node/EnricherNode.java) | FAST 与指定模型，可选元数据提取 |

## 其他 6 处产品模型调用

| 编号 | 类与行号 | 用途 |
|---|---|---|
| 17 | [ImageDocumentParser:102](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/core/parser/image/ImageDocumentParser.java) | VLM 图片描述 |
| 18 | [MinerUResultUnpacker:224](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/core/parser/mineru/MinerUResultUnpacker.java) | VLM 文档内嵌图片描述 |
| 19 | [ChunkEmbeddingService:54](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/core/ingest/embed/ChunkEmbeddingService.java) | 文档块批量向量化 |
| 20 | [PgVectorRetrieverService:58](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/PgVectorRetrieverService.java) | PG 查询向量化 |
| 21 | [MilvusVectorRetrieverService:66](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/MilvusVectorRetrieverService.java) | Milvus 查询向量化，与 PG 为替代后端 |
| 22 | [RerankPostProcessor:72](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/postprocessor/RerankPostProcessor.java) | 候选重排 |

LightRAG 的内部生成/嵌入、MinerU 服务自身的模型计算、RAGAS 的内部模型步骤不计入这 22 处 Java 业务入口。它们是外部服务成本，不能因不在列表里就从系统总账删除。HNSW、BM25、RRF 本身不需要生成式 LLM。

## 与分流设计直接相关的实现

- [ModelSelector](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/model/ModelSelector.java)：档位、候选与指定模型选择。
- [RoutingLLMService](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/chat/RoutingLLMService.java)：路由和回退。
- [OllamaChatClient](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/chat/OllamaChatClient.java)：复用兼容接口调用。
- [BaiLianRerankClient](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/rerank/BaiLianRerankClient.java)：专用重排协议。
- [AgentEngineConfiguration](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/config/AgentEngineConfiguration.java)：独立的 Agent 模型组装。
- [ConversationServiceImpl](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/service/impl/ConversationServiceImpl.java)：新会话创建时的标题生成。
- [EvalController](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/eval/EvalController.java)：旁路独立改写、意图和检索。

## 估算记录

| 口径 | 规划区间 | 限制 |
|---|---|---|
| 固定 RAG 云端 LLM 费用 | 25%～40% 降幅 | 单子问题、图谱开启、迁移辅助处理、回答留云端；无重试或缓存的例算附近 |
| Agent 云端 LLM 费用 | 10%～25% 降幅 | 两次知识搜索，外层费用假设 0.05～0.23 元；非当前供应商实测 |
| 固定 RAG 云端付费 Token | 30%～45% 降幅 | 对应正文的输入/输出长度假设 |
| Agent 云端付费 Token | 15%～30% 降幅 | 两次工具调用、外层合计约 15,000～50,000 Token 的例算附近 |

这些不是统计置信区间。费用区间与 Token 区间分别演算，不能要求每个边界一一对应。评测裁判、入库建图、Embedding、Rerank 和本地 GPU 成本不在简历的费用分母内。源码已有本地候选不等于已完成任务级迁移。

[返回第 46 章](../docs/46-local-qwen-model-routing.md) · [返回首页](../README.md)
