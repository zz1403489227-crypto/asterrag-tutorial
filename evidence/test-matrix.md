# AsterRAG 测试与运行证据矩阵

> 冻结提交：`98894c2c42c015a3c874c6b3c986ac863c85b731`  
> 当前阶段：P1 静态分类；尚未把“存在测试”写成“测试通过”。

## 1. 证据等级

| 等级 | 定义 | 当前状态 |
|---|---|---|
| Hermetic | 不依赖 Redis、PostgreSQL、Milvus、外部网络或真实模型供应商 | pending execution |
| Integration | 依赖一个或多个本地/容器化基础设施 | pending environment census |
| Live | 调用真实模型、联网搜索、MinerU 或 MCP 外部服务 | pending credentials/services |
| Browser | 真实前后端、真实 SSE、真实刷新/重连后的页面状态 | pending full stack |

## 2. 源码计数

- 测试 Java 文件：77。
- `@Test`：367 处。
- `@SpringBootTest` 文件：11。
- 明确命名的 `*LiveTest.java`：2。

计数不代表通过数，也不代表覆盖率。

## 3. CI 已定义的 Hermetic 基线

后端：

```bash
./mvnw -B test -Dsurefire.excludes='**/*Tests.java'
```

前端：

```bash
cd frontend
npm ci
npm run lint
npm run build
```

当前状态：尚未在教程工作区执行。执行后必须把完整日志、退出码、提交和环境版本保存到 `evidence/runtime/`。

## 4. `@SpringBootTest` 清单

以下测试默认归入 Integration/Live 待复核，不进入 Hermetic 通过声明：

- `rag/src/test/java/com/nageoffer/ai/ragent/RagentCoreApplicationTests.java`
- `rag/src/test/java/com/nageoffer/ai/ragent/core/parser/mineru/MinerUPdfUploadFlowTest.java`
- `rag/src/test/java/com/nageoffer/ai/ragent/index/InvoiceIndexDocumentTests.java`
- `rag/src/test/java/com/nageoffer/ai/ragent/rag/Intent/IntentTreeServiceTests.java`
- `rag/src/test/java/com/nageoffer/ai/ragent/rag/Intent/SimpleIntentClassifierTests.java`
- `rag/src/test/java/com/nageoffer/ai/ragent/rag/Intent/VectorTreeIntentClassifierTests.java`
- `rag/src/test/java/com/nageoffer/ai/ragent/rag/embedding/SiliconFlowEmbeddingServiceTests.java`
- `rag/src/test/java/com/nageoffer/ai/ragent/rag/rewrite/MultiQuestionRewriteServiceTests.java`
- `rag/src/test/java/com/nageoffer/ai/ragent/rag/rewrite/QueryRewriteTests.java`
- `rag/src/test/java/com/nageoffer/ai/ragent/service/ConversationMessageServiceTests.java`
- `rag/src/test/java/com/nageoffer/ai/ragent/vector/MilvusCollectionTests.java`

## 5. 明确 Live Test

- `mcp-server/src/test/java/com/nageoffer/ai/ragent/mcp/executor/YouComSearchMcpExecutorLiveTest.java`
- `rag/src/test/java/com/nageoffer/ai/ragent/rag/core/retrieval/channel/WebSearchChannelLiveTest.java`

默认不执行，除非已经确认真实凭据、调用成本、网络和数据边界。

## 6. 教程核心链路的聚焦测试候选

### 入库

- `IngestionEngineTest`
- `ConditionEvaluatorTest`
- `IngestionPipelineServiceImplTest`
- `IngestionTaskServiceImplTest`
- `RemoteFileFetcherTest`
- `ScheduleRefreshProcessorTest`
- `IngestionSpecCodecTest`
- `ChunkingFixtureTest`
- `MinerUPdfUploadFlowTest`（Integration/Live 边界待核）

### 确定性 RAG

- `StreamChatPipelineTest`
- `ChatQueueLimiterTest`
- `RetrievalEngineTest`
- `MultiChannelRetrievalEngineTest`
- `RetrievalScopeResolverTest`
- `VectorSearchChannelTest`
- `KeywordSearchChannelTest`
- `GraphSearchChannelTest`
- `WebSearchChannelTest`
- `DeduplicationPostProcessorTest`
- `EvidenceGatePostProcessorTest`
- `RAGPromptServiceTest`
- `CitationContextEnricherTest`
- `CitationMarkupTest`
- `RoutingLLMServiceHalfOpenRecoveryTest`

### Agent

- `AgentChatServiceImplTest`
- `AgentRunGateTest`
- `AgentRunHandleTest`
- `AgentStreamEventBridgeTest`
- `ReActAgentProviderTest`
- `AgentToolCatalogTest`
- `KnowledgeSearchToolTest`
- `MemoryFlushToolTest`
- `AgentMemoryPipelineTest`
- `AgentConversationServiceImplTest`

## 7. 结果记录格式

每次执行必须记录：

- `source_commit`
- `timestamp`
- `host`
- `java_version` / `maven_version` / `node_version`
- 完整命令
- 退出码
- 通过/失败/跳过数量
- 外部服务与配置摘要（不得记录密钥）
- 日志文件 SHA-256
- 结论范围与不能证明的内容

