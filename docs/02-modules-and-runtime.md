# 第 2 章：项目怎样启动——模块边界、依赖方向与运行拓扑

> 第 1 章告诉你系统有哪些架构节点。本章回答：这些节点在仓库中住在哪里，它们怎样被组装成进程？

## 2.1 最重要的结论：七个 Maven 模块不是七个微服务

冻结仓库根 `pom.xml` 声明七个模块：

```text
framework
infra-ai
system
rag
agent
bootstrap
mcp-server
```

但判断微服务不能数目录，要看三种边界：

| 边界 | 它回答什么 | AsterRAG 中的结论 |
|---|---|---|
| 编译依赖 | 哪个模块可以直接使用哪个模块的类 | 由各 `pom.xml` 决定 |
| 业务责任 | 谁拥有知识、模型、Agent 或审计的规则 | 按模块/包边界分开 |
| 运行进程 | 是否需要网络调用才能穿越 | 主应用 1 个进程，MCP Server 另 1 个独立进程 |

`bootstrap` 把 `rag` 和 `agent` 装进同一个 Spring Boot 应用，而 `rag` 再依赖 `framework`、`infra-ai` 和 `system`。这是模块化单体：有源码责任边界，但核心业务调用不经过多个网络服务。

## 2.2 依赖方向

用箭头表示“上层可以编译依赖下层”：

```text
framework
   ↑       ↑        ↑
infra-ai   system      rag
   └─────↗   ↗─────┘
             rag
              ↑
            agent
              ↑
          bootstrap

mcp-server  （独立 Spring Boot 边界）
```

更准确地说：

- `infra-ai` 依赖 `framework`；
- `system` 依赖 `framework`；
- `rag` 依赖 `framework + system + infra-ai`；
- `agent` 依赖 `rag`，因而能通过窄门面复用 RAG 能力；
- `bootstrap` 依赖 `rag + agent`，只做最终应用组装；
- `mcp-server` 不依赖主应用业务模块，它是外部工具服务示例。

这个方向也解释了为什么 Agent 能使用 `KnowledgeSearchFacade`，而 RAG 不应反过来依赖 Agent 的业务会话或工具 block。

## 2.3 七个模块的责任表

### 2.3.1 `framework`：横切契约，不做业务编排

`framework` 包含：

- 统一响应与异常处理；
- 用户上下文和 Sa-Token 认证基础；
- 幂等契约/AOP；
- Redisson、MQ 和事务消息基础能力；
- Trace 上下文传递；
- `SseEmitterSender`、`StreamTaskManager` 等 Web/SSE 通用工具；
- MyBatis Plus 、校验和通用工具集成。

它不应该知道“文档怎样分块”或“Agent 应该选哪个工具”。如果横切层开始使用 KnowledgeDocument 或 AgentSession 的领域规则，依赖方向就会反转。

### 2.3.2 `infra-ai`：模型能力与路由，不决定业务范围

`infra-ai` 将不同 AI 供应商暴露为应用可使用的共同能力：

- Chat 模型；
- Embedding 模型；
- Rerank；
- VLM；
- 候选模型、路由、健康/熔断和首包探测。

它回答“如何调用模型能力”，不回答“查哪个知识库”或“没有证据是否应该回答”。后两个是 RAG 业务编排的责任。

### 2.3.3 `system`：用户和审计等系统域

`system` 主要拥有：

- 用户和系统基础管理；
- 示例/推荐问题等控制面数据；
- BizChangeLog 的业务审计能力。

业务审计记录“谁修改了哪个管理对象、before/after 是什么”。它与 RAG Trace 回答的“这次问答经过了哪些节点、耗时多少”不是一回事。

### 2.3.4 `rag`：最大的业务域

`rag` 模块同时拥有：

- 知识库、文档、Chunk 和远程刷新；
- 固定摄取内核与通用 Ingestion 子系统；
- 查询改写、意图、多通道检索与后处理；
- Prompt、Grounding、确定性 RAG Pipeline 和 SSE 收尾；
- MCP client/registry/executor；
- RAG Trace、管理 API 和设置投影。

它内部也不应按字母阅读。用主链导航：

```text
knowledge
  → 文档入口、对象/元数据、MQ、刷新生命周期

core.parser / core.chunk / core.ingest
  → 固定摄取的纯能力和五步内核

ingestion
  → 独立通用 Pipeline/Task/Node 子系统

rag.core
  → 改写、意图、检索、后处理、Prompt、MCP

rag.service.pipeline
  → 确定性 StreamChatPipeline

rag.trace / rag.aop
  → 运行观测与节点记录
```

### 2.3.5 `agent`：动态编排和 Agent 专属状态

`agent` 依赖 `rag`，但不是另一份确定性 RAG 拷贝。它拥有：

- Agent Controller/Service 和每用户 RunGate；
- AgentScope `ReActAgent` 构建与 cache 刷新；
- Knowledge/Memory/MCP 工具目录；
- Agent Scope State 持久适配；
- Context Compaction 和 Long-term Memory；
- Agent 业务会话、消息和 block；
- Agent event bridge 与三路 finalizer。

它复用 `rag` 的知识窄门面，不得不经约束地穿透到 RAG Controller/SSE 内部。

### 2.3.6 `bootstrap`：最终组装，不是业务杂物间

`bootstrap` 中的 `RagentApplication` 是主 Spring Boot 入口。其 POM 依赖 `rag + agent`，使用 Spring 扫描将所有核心模块装入同一进程。

它的责任是：

- 启动主应用；
- 持有总配置 `application.yaml`；
- 通过依赖传递组装业务 Bean。

不应把新的知识库或 Agent 业务逻辑直接写进 bootstrap，否则模块 owner 会消失。

### 2.3.7 `mcp-server`：独立工具服务示例

`McpServerApplication` 是另一个 Spring Boot 入口，默认端口 9099。它提供 MCP 工具服务，主应用通过 MCP client 和配置 URL 连接它。

仓库中的天气、票务或销售等工具是示例数据/能力，不能在面试中说成已经集成某个真实企业业务系统。

## 2.4 两个启动边界

| 进程 | 入口 | 默认地址 | 主要能力 |
|---|---|---|---|
| AsterRAG 主应用 | `bootstrap/src/main/java/com/nageoffer/ai/ragent/RagentApplication.java` | `9090` + context `/api/ragent` | UI/API、知识、RAG、Agent、管理 |
| 示例 MCP Server | `mcp-server/src/main/java/com/nageoffer/ai/ragent/mcp/McpServerApplication.java` | `9099` | 独立 MCP tools |

从代码上看，这两者的网络边界是真实的。主应用中 `rag` 调 `infra-ai` 或 `agent` 调 `KnowledgeSearchFacade` 则是同进程方法/Bean 调用。

这个区分会直接影响你对失败的判断：

- 同 JVM 业务调用失败，可以在当前调用栈抛异常/使用 Spring 事务；
- MCP 调用失败，涉及外部服务连接、注册表和工具执行边界；
- 同一仓库不能消除运行时网络失败。

## 2.5 根构建身份

冻结根 POM 明确的主版本是：

```text
Java: 17
Spring Boot: 4.1.0
```

仓库文档对 Maven 的参考是 3.9.11。前端在自己的 `package.json` 中构建；文档中可见 Node 18 级别描述，CI 工作流使用 Node 22。对学习源码来说，重点是知道前后端有独立构建边界，不要把文档推荐和 CI 当作同一条运行证据。

作者旧公开页中的 Spring Boot 3.5.7/四模块是旧版本参考，不应被复制进当前冻结仓库的主叙述。

## 2.6 从 YAML 到 Bean：怎样判断实际选择

阅读配置时需要四层证据：

```text
POM 有依赖
   ↓ 只证明能编译/可以支持
YAML / Properties 有值
   ↓ 证明配置选择或兜底
Conditional Bean 进容器
   ↓ 证明实现被装配
本轮 runtime branch 经过该能力
   ↓ 才是这次请求实际使用
```

### 反例一：workflow 还是 agent

`OrchestrationProperties.type` 的 Java 字段兜底是 `workflow`，但 `bootstrap/src/main/resources/application.yaml` 明确配置：

```yaml
ragent:
  engine:
    type: agent
```

因此带这份 YAML 正常启动时选 Agent 档。Java 兜底只在该键没有被外部配置覆盖时生效。

### 反例二：Milvus 还是 pgvector

某些 Milvus 条件 Bean 可以有 `matchIfMissing=true`，但 YAML 显式配置 `rag.vector.type=pg`。这意味着当前默认后端是 PostgreSQL/pgvector，不是 Milvus。

这两个例子共同说明：

> 不能从一个 Properties 初始值或一个 `@ConditionalOnProperty` 的单独属性，跳过实际 YAML 就宣布项目默认拓扑。

## 2.7 默认主链和可选扩展层

由冻结 POM、YAML 和条件装配可以建立三层拓扑理解。这里是源码/配置导航，不是启动复现指南。

### 层 1：静态阅读和 Hermetic 测试

需要 JDK/Maven，前端需 Node/npm。一部分纯单元测试可以不连外部中间件，但这不代表主应用可在无依赖下运行。

### 层 2：随仓库默认主链

从配置和 fail-fast 初始化可知，主链涉及：

- PostgreSQL + pgvector；
- Redis/Redisson；
- S3 兼容对象存储；
- RocketMQ 的知识文档分块使用点；
- 至少一个 Chat/Embedding 等模型供应商配置；
- Agent 执行档和默认 vector 检索。

教程只讲清它们的责任与故障边界，不搭建专属集成环境来重新证明项目正确。

### 层 3：可选扩展

- Milvus 向量后端；
- Elasticsearch 关键词/写同步；
- LightRAG 图谱/写同步；
- Web Search；
- 外部 MCP Servers；
- MinerU、VLM 等特定解析/模态能力；
- Eval 与外部模型服务。

“可选”的精确含义是：存在实现和配置入口，但当前默认拓扑不保证它们全部被装配/执行。

## 2.8 前端的运行边界

前端是 React 应用，通过 API 和 SSE 与主应用交互。这一层不只是“画页面”，它还拥有当前流的客户端投影：

- `EngineGate` 根据后端元信息选择 Agent/RAG 页；
- `useStreamResponse` + `chatStore` 消费确定性 RAG 协议；
- `useAgentStream` + `agentChatStore` 消费 Agent block 协议；
- 刷新后通过服务端持久消息重建可恢复部分。

两套 hook/store 说明 Agent 与 RAG 不只后端不同，连前端事件合同和本地状态都不同。

## 2.9 如何从仓库开始读：15 分钟跳转路线

第一遍不要查所有包。只跳这些点：

```text
1. pom.xml
   → 数 7 个模块，看 Java/Boot 版本

2. bootstrap/pom.xml
   → 确认 rag + agent 被组装

3. RagentApplication
   → 确认主进程入口

4. application.yaml
   → 确认 9090/context、engine=agent、vector=pg、通道开关

5. KnowledgeDocumentController
   → 找写路径入口

6. RAGChatController
   → 找固定读路径入口

7. AgentChatController
   → 找动态 Agent 入口和条件装配

8. McpServerApplication + mcp-server/application.yml
   → 确认第二进程边界
```

这条路线完成后，你应该能把任何一个后续类放回“模块 owner + 所属进程 + 主链位置”中。

## 2.10 常见误解

### “七个模块是不是七个微服务？”

不是。核心业务模块通过 `bootstrap` 在同一 JVM 组装。MCP Server 才是独立网络边界。

### “bootstrap 依赖所有业务，是不是业务都应放它里？”

不是。它是 composition root，依赖上层能力是为了装配，不是为了拥有领域规则。

### “同一仓库的 MCP Server 是不是不会有网络失败？”

不是。它有独立启动入口和端口，主应用作为 client 连接，依然存在注册、连接、超时和执行失败。

### “类默认是 workflow，为什么说项目默认 Agent？”

因为 Java 字段初始值只是配置键缺失时的兜底；随仓库 YAML 显式设置 `type=agent`，覆盖了兜底。

### “支持 ES/LightRAG/Milvus，默认就会都连吗？”

不是。要逐层检查实现、YAML、条件 Bean 和运行分支。当前向量选 pg，query channel 默认只开 vector。

## 2.11 本章源码卡片

| 问题 | 锚点 |
|---|---|
| 有多少 Maven 模块 | 根 `pom.xml` 的 `<modules>` |
| 主应用装了什么 | `bootstrap/pom.xml` |
| 主应用入口 | `bootstrap/src/main/java/com/nageoffer/ai/ragent/RagentApplication.java` |
| MCP Server 入口 | `mcp-server/src/main/java/com/nageoffer/ai/ragent/mcp/McpServerApplication.java` |
| 主应用端口/context/引擎/向量 | `bootstrap/src/main/resources/application.yaml` |
| MCP 端口 | `mcp-server/src/main/resources/application.yml` |
| Java/Boot 版本 | 根 `pom.xml` |
| Agent 条件装配 | `AgentChatController` 及 Agent configuration |
| engine Java 兜底 | `OrchestrationProperties` |

## 2.12 本章自测

1. 画出模块依赖方向，并说出为什么它不是七个微服务。
2. `framework`、`infra-ai`、`rag`、`agent` 分别拥有什么，不拥有什么？
3. 主应用和 MCP Server 的运行边界是什么？
4. 为什么读配置要经过 POM、YAML、Conditional Bean 和 runtime branch 四层？
5. 随仓库默认选 Agent 还是 workflow？默认向量后端是什么？
6. 为什么不能把作者旧网页的 4 模块/Boot 3.5.7 直接写成当前项目事实？

## 2.13 小结：代码住在哪里已经清楚，下一步问“状态归谁”

现在你已经能将第 1 章的架构节点放回七个模块和两个进程。但知道类在哪里还不足以解释失败：一次分块中断后，原文件、文档状态、Chunk 和向量分别发生什么？Agent 页面刷新后，业务消息、Agent State、raw frames 哪个还在？

第 3 章将放下包名，改用“持久事实、原对象、派生索引、协调态和进程态”来重新理解整个系统。
