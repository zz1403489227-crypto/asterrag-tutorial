# 第 19 章：配置如何改变系统——组装条件、默认选择与故障推演

> 前 18 章回答了对象如何流动、状态由谁保存、终态怎样呈现。本章换一个方向：不跟某次请求，而是站在 Spring 启动阶段，判断哪些实现会真正进入当前系统。
>
> 阅读配置最大的陷阱是“看到代码里有一个实现，就说项目默认会用它”。AsterRAG 同时包含 pgvector 与 Milvus、S3 与 OSS、向量/关键词/图谱/联网检索、确定性 Workflow 与 ReAct Agent。它们有的是二选一实现，有的是存在但默认关闭的通道，有的是连接失败后降级，有的是缺失就让应用启动失败。只有把 POM、YAML、条件装配、运行期开关和失败策略串起来，才知道冻结版本的真实拓扑。

## 19.1 配置不是参数清单，而是“拓扑编译器”

可以把 Spring 启动理解为一次从静态仓库到运行拓扑的编译：

```text
Maven 依赖与模块
    │  决定哪些类型有资格被编译/扫描
    ▼
application.yaml + 环境覆盖
    │  绑定到 Properties / @Value
    ▼
@ConditionalOnProperty / 自定义条件
    │  决定哪些 Bean 进入容器
    ▼
启动校验、@PostConstruct、initMethod
    │  检查不变式并触碰部分外部依赖
    ▼
运行期 isEnabled / 工厂 / 注册表 / 路由器
    │  决定某一轮实际调用谁
    ▼
本次请求的真实路径与失败位置
```

这里有四级证据，强度逐级增加：

| 证据 | 能证明 | 不能证明 |
|---|---|---|
| POM 有 SDK 依赖 | 代码可以引用该 SDK | 对应实现已装配 |
| YAML 有配置段 | 值可被绑定或读取 | Bean 一定存在、通道一定参与 |
| 条件 Bean 已满足 | 实现进入 Spring 容器 | 本轮 `isEnabled` 一定为 true |
| 运行分支选中并调用 | 本轮确实走到该实现 | 外部依赖一定成功返回 |

后续每个“默认”结论都按这四级证据给出，而不是只抄 README。

---

## 19.2 先确认启动边界：七个模块不等于七个进程

根 POM 声明七个 Maven 模块：

```text
framework ← infra-ai
    ↑         ↑
 system ──→ rag ← agent
               ↑
            bootstrap

mcp-server（独立 Spring Boot 应用，无内部业务模块依赖）
```

真正的应用入口只有两类：

| 进程 | 入口 | 默认端口 | 责任 |
|---|---|---:|---|
| 主应用 | `RagentApplication` | 9090，context `/api/ragent` | RAG、Agent、知识库、系统与管理 API |
| MCP Server | `McpServerApplication` | 9099 | 独立暴露演示 MCP 工具 |

`bootstrap` POM 依赖 `rag` 与 `agent`，Spring 组件扫描再把它们及其传递内部模块装进同一个主进程。`mcp-server` 没有依赖 framework/rag/agent，是另一个进程边界。

因此准确表述是“模块化单体 + 一个独立 MCP Server”，而不是“七个微服务”。模块依赖描述编译与代码责任，进程入口才描述部署边界。

### 19.2.1 版本要求只作为阅读背景

冻结 POM 设置：

- Java release 17；
- Spring Boot 4.1.0；
- Maven Wrapper 下载 Maven 3.9.11；
- 编译器插件使用 `release=${java.version}`。

前端 package 使用 React 18.3、TypeScript 5.5、Vite 5.4。README 写 Node.js 18+，仓库 CI 则明确使用 Node 22。`package.json` 本身没有 `engines` 字段，因此“仓库强制 Node 22”并不准确；更准确的是“文档下限 18，CI 已知基线 22”。

这些信息帮助读源码和解释构建边界。本教程不要求读者实际搭环境。

---

## 19.3 冻结 YAML 生成的默认拓扑

把随仓库 `bootstrap/src/main/resources/application.yaml` 与所有条件类交叉后，默认拓扑可以压缩为：

```text
React/Vite
    │ /api/ragent
    ▼
主 Spring Boot 应用（Agent 档）
    ├─ Agent HTTP/SSE + ReAct + PostgreSQL Agent State/Memory
    ├─ 确定性 RAG HTTP/SSE（仍然存在）
    ├─ KnowledgeSearchFacade（Agent 的 search_knowledge 工具复用）
    ├─ PostgreSQL：31 表 + pgvector 共享表
    ├─ Redis/Redisson：ID、会话协调、gate、queue、cancel、semaphore、init lock
    ├─ S3 兼容对象存储：知识原件桶 + 公共资产桶
    ├─ RocketMQ：文档分块、知识库清理、反馈三类消费者
    ├─ 检索：vector=on(pgvector)
    │          keyword=off(type=none)
    │          graph=off(type=none)
    │          web=off(no enabled/key)
    ├─ RAG chat 模型：tier 路由与候选 fallback
    ├─ Agent chat 模型：固定 provider/model，无跨模型 fallback
    ├─ embedding：default + priority fallback
    ├─ rerank：真实候选失败后可落 noop
    └─ MCP Client：尝试连接 localhost:9099；失败跳过远程工具，不阻止启动

独立 MCP Server（默认 :9099）
    └─ 示例工具；You.com 工具还受 YDC_API_KEY 条件控制
```

默认值表：

| 选择点 | 随仓库 YAML | 当前结果 |
|---|---|---|
| 执行架构 | `ragent.engine.type=agent` | Agent Bean 参与装配，前端默认进入 Agent 页 |
| 对象存储 | `rag.storage.type=s3` | S3 client/presigner + S3 ObjectStorageClient |
| 向量后端 | `rag.vector.type=pg` | PgVector Store/Retriever/Admin |
| 关键词后端 | `rag.keyword.type=none` | ES client/index/channel 均不装配 |
| 图谱后端 | `rag.graph.type=none` | LightRAG client/channel/写同步均不装配 |
| 向量通道 | enabled=true | 本地知识检索主通道 |
| 关键词/图谱/联网 | enabled=false | 不参与本轮检索 |
| Query Rewrite/Rerank/Citation/Trace | true | 对应流程分支开启 |
| RAG 全局并发 | true，最大 10 | 进入 Redis 公平队列/许可机制 |
| Eval | true | Eval Controller 装配，提交防重切面按第 17 章逻辑绕过 |

“默认 Agent”不等于“Workflow 代码没有装配”。`RAGChatController` 与 RAG Pipeline 没有用 `@ConditionalOnAgentEngine` 排除；Agent 还需要通过 KnowledgeSearchFacade 复用 RAG 核心。默认改变的是产品入口与 Agent 专属 Bean 是否加入，不是删掉整个确定性 RAG 子系统。

---

## 19.4 引擎开关：Java 兜底值与仓库 YAML 默认值不是一回事

`OrchestrationProperties.type` 的字段初始值是 `workflow`，但随仓库 YAML 显式写 `agent`。Spring 绑定后，YAML 覆盖字段初始值：

```text
键存在：ragent.engine.type=agent
           ↓
OrchestrationProperties.type = agent
           ↓
@ConditionalOnAgentEngine 成立
           ↓
Agent Controller / Service / RunGate / State / Memory / ToolCatalog 装配
```

只有删除或覆盖这个键时，Java 字段兜底才可能回到 workflow。不能看到 Java 注释“workflow（默认）”就忽略仓库实际 YAML。

自定义 `@ConditionalOnAgentEngine` 本质上封装了：

```java
@ConditionalOnProperty(
    prefix = "ragent.engine",
    name = "type",
    havingValue = "agent"
)
```

它没有 `matchIfMissing=true`。键缺失时 Agent Bean 不装配。前端 `EngineGate` 又读取 `/rag/settings` 中同一 `OrchestrationProperties`，所以后端 Bean 拓扑与前端入口使用同一配置源。

### 19.4.1 Agent 模式下哪些配置问题会在启动期暴露

`AgentEngineConfiguration.agentChatModel()` 检查：

- `agent.chat.provider` 和 `agent.chat.model` 非空；
- provider 必须存在于 `ai.providers`；
- provider 的 base URL 和 `endpoints.chat` 非空。

这些结构问题会在创建 Bean 时直接抛 `IllegalStateException`。但它没有检查 apiKey 非空，也没有在构建时向模型发探活请求，所以“Agent Bean 创建成功”不等于供应商鉴权和网络可用。密钥或端点真实可用性会在模型调用阶段暴露。

---

## 19.5 PostgreSQL 同时承担关系事实、Agent 状态和默认向量后端

默认 datasource 指向 PostgreSQL。`RagentApplication` 扫描七组 Mapper，31 张表分别承载用户、RAG 会话、知识、Trace、Agent、通用入库与向量。

默认 `rag.vector.type=pg` 还会装配：

- `PgVectorStoreService`：写/删 `t_knowledge_vector`；
- `PgVectorRetrieverService`：embedding 后用 `<=>` 做余弦距离查询；
- `PgVectorStoreAdmin`：检查共享表与 HNSW 索引。

所以“PostgreSQL 挂了”并不只是聊天历史不可查；默认配置下还会同时影响：

- 登录用户与会话；
- 文档/Chunk/入库状态；
- Agent State、压缩与长期记忆；
- Trace/审计；
- 向量写入与查询。

### 19.5.1 Schema 不是 Spring 自动迁移

仓库提供 `resources/database/schema_pg.sql`，README 明确要求用 `psql` 执行。冻结源码中没有找到 Flyway、Liquibase、`spring.sql.init.schema-locations` 或主动执行该 SQL 的代码。

因此 Schema 文件是第一手结构定义，但不是“主应用启动时自动建 31 表”。如果数据库可达但表未建立，Mapper 查询或启动初始化器触碰表时会失败。

SQL 首先执行 `CREATE EXTENSION IF NOT EXISTS vector`，随后定义 `t_knowledge_vector.embedding vector(1536)` 与 HNSW 索引。这里有一个重要配置耦合：

```text
rag.default.dimension = 1536
          ↕ 必须与
t_knowledge_vector.embedding = vector(1536)
          ↕ 还必须与
embedding 模型实际返回维度一致
```

只改 YAML dimension，不会自动改 PostgreSQL 列类型。维度是跨配置、Schema、模型三方不变式。

### 19.5.2 `VectorSpaceInitializer` 在 PG 与 Milvus 下做的事不同

初始化器只依赖 `VectorStoreAdmin` 抽象：

- Milvus 实现会确保共享 collection；
- PG 实现先查询 `t_knowledge_vector`，表存在就视为 vector space 已存在；不存在时尝试创建 HNSW index，而它不能代替建表脚本。

Schema 已创建名为 `idx_kv_embedding` 的 HNSW 索引，`PgVectorStoreAdmin` 检查/创建的是 `idx_kv_embedding_hnsw`。按冻结源码，两者名称不同，因此在特定 Schema 状态下可能额外创建第二个 HNSW 索引。教程只记录这个源码事实，不把它扩写为运行结果。

---

## 19.6 Redis 在默认拓扑中不是“可有可无的缓存”

默认路径对 Redis/Redisson 的使用包括：

- `SnowflakeIdInitializer` 执行 Lua 分配 workerId/datacenterId；
- `StorageInitializer` 和 `VectorSpaceInitializer` 用分布式锁；
- 全局聊天公平队列、信号量和 AgentRunGate；
- StreamTaskManager 的 owner/cancel key 与 pub/sub；
- 上传、MinerU 等分布式许可；
- Sa-Token 会话相关 Redis 适配。

其中 `SnowflakeIdInitializer.init()` 是 `@PostConstruct`，Redis Lua 执行失败会被包装成“分布式Snowflake初始化失败”并继续抛出。Storage/Vector 初始化器也会在需要锁时触碰 Redisson，并采用快速失败策略。

因此默认拓扑里 Redis 不只是提高性能的 cache，而是启动身份分配和跨节点协调基础设施。没有 Redis 时不能笼统地说“只是缓存未命中，回数据库即可”。

### 19.6.1 配置开关关闭限流，也不会移除所有 Redis 依赖

`rag.rate-limit.global.enabled=false` 只让 ChatQueueLimiter 绕过全局排队逻辑。`ChatRateLimiterConfig` 仍创建 FairDistributedRateLimiter Bean，其他 ID、任务取消、上传许可与初始化锁也没有因此消失。

单个功能开关只保护自己的分支，不能当作全局“无 Redis 模式”。

---

## 19.7 对象存储是二选一 Bean，且默认启动会主动验证

`rag.storage.type` 控制两组互斥对象：

```text
type=s3 或键缺失
  ├─ S3Client
  ├─ S3Presigner
  └─ S3ObjectStorageClient

type=oss
  ├─ OSS client
  └─ OssObjectStorageClient
```

S3 条件使用 `matchIfMissing=true`，RagStorageProperties 字段兜底也为 s3，随仓库 YAML 同样显式选择 s3。三层结论一致。

`StorageInitializer.@PostConstruct` 会确保知识原件桶与资产桶存在，并把资产桶设为公共读。它先查桶，缺失时使用 Redisson lock 做双重检查和创建。对象存储不可达、权限不足或锁获取失败会让异常上抛，属于启动时可见故障。

如果把 type 写成既非 s3 也非 oss 的值，两套 `ObjectStorageClient` 都不注册，`StorageInitializer` 的构造依赖无法满足，应用会在 Bean 装配阶段失败。这和“合法后端暂时不可达”是两个不同错误层：

| 错误 | 可见层 |
|---|---|
| type 无匹配实现 | Bean 依赖装配失败 |
| endpoint/凭据/桶权限不对 | client 调用或 StorageInitializer 失败 |

---

## 19.8 RocketMQ：配置存在不等于消息已经消费

主应用配置 name server、producer group 和发送超时。framework 无条件提供 `MessageQueueProducer`，实际调用 `RocketMQTemplate.syncSend` 或事务发送。仓库中三个真实 Consumer 分别处理：

- 知识文档分块；
- 知识库清理；
- 消息反馈。

项目代码的失败语义很明确：

- 普通/事务发送抛异常时，adapter 记录错误并继续抛；
- 事务发送前在 `DelegatingTransactionListener` 注册本地事务；发送异常会注销；
- 业务 Consumer 的重试与重复边界按第 6、17 章理解。

RocketMQ listener 容器何时连接 broker 属 starter 生命周期；仅凭项目源码不武断承诺“broker 不可达一定在某一启动行失败”。可以确认的是：项目没有为文档分块主链提供无 MQ 的同步替代实现，第一次需要发送时失败会直接暴露；Consumer 不工作时，即使上游某个动作已经提交，也不能说异步处理已完成。

### 19.8.1 `unique-name` 改的是消息命名空间，不是业务租户

配置中的 `${unique-name:}` 会拼进 application name、producer group、三个 topic/consumer group。它能让同一套基础设施上的多套实例使用不同 MQ 名称。

它不是 userId、tenantId 或知识库隔离键，也不会自动改 PostgreSQL 表名、Redis 全部 key 或对象存储桶。不要把它称为完整多租户隔离。

---

## 19.9 检索通道有“两道门”：Bean 是否存在 + 本轮是否启用

四类通道的装配模型不同：

| 通道 | Bean 进入容器条件 | 本轮 `isEnabled` 条件 | 默认 |
|---|---|---|---|
| 向量 | 必须有 pg 或 milvus `VectorRetrieverService` | `channels.vector.enabled` | pg + true |
| 关键词 | `rag.keyword.type=es` | `channels.keyword.enabled` | none + false |
| 图谱 | `rag.graph.type=lightrag` | `channels.graph.enabled` | none + false |
| 联网 | `WebSearchChannel` 总是组件 | enabled 且 API key 非空 | false |

于是“有效参与”可以写成：

```text
关键词/图谱：backend Bean exists AND runtime enabled
联网：runtime enabled AND key resolvable
向量：selected retriever exists AND runtime enabled
```

`MultiChannelRetrievalEngine` 注入容器中所有 `SearchChannel`，每次请求再过滤 `channel.isEnabled(context)`。这就是为什么条件 Bean 和运行开关必须分开读。

### 19.9.1 启动前置校验只拦截单向矛盾

`RetrievalConfigEnvironmentPostProcessor` 通过 `spring.factories` 注册，在 application.yaml 加载后、Bean 创建前读取完整 Environment。

它检查：

```text
keyword.enabled=true 但 keyword.type!=es       → 启动失败
graph.enabled=true   但 graph.type!=lightrag   → 启动失败
```

FailureAnalyzer 会给出“启用后端”或“关闭通道”的二选一动作。反过来 `type=es/lightrag` 但 query channel=false 是合法的：后端可以只做索引写入、图谱管理或可视化，不参与问答召回。

Web Search 没有同样的启动失败：enabled=true 但 key 为空时，`isEnabled()` 返回 false，表现为静默不参与。这个差异来自各通道的装配模型，而不是统一规则。

---

## 19.10 向量后端：为什么 `matchIfMissing=true` 仍不能推出默认 Milvus

Milvus 的 Config、Store、Retriever、Admin 都写：

```java
@ConditionalOnProperty(
    name = "rag.vector.type",
    havingValue = "milvus",
    matchIfMissing = true
)
```

PG 实现要求 `havingValue="pg"`。如果键完全缺失，Milvus 确实兜底；但随仓库 YAML 显式写 `pg`，所以实际默认是 pgvector。

这是最经典的优先级问题：

```text
条件注解的“缺键兜底”
           <
application.yaml 的显式值
```

切到 Milvus 会同时改变 Store、Retriever、Admin 与 client，`VectorSearchChannel` 仍依赖同一个抽象。`VectorSpaceInitializer` 会在启动时确保 collection 存在，连接或权限问题因此可能在初始化阶段暴露。

如果写一个未知 vector type，PG/Milvus 两套 Bean 都不存在，依赖 `VectorRetrieverService`、`VectorStoreService` 或 `VectorStoreAdmin` 的组件会装配失败；项目没有 `none` 向量后端。

---

## 19.11 ES：`type=es` 不只是打开查询，还会织入写同步

当 `rag.keyword.type=es` 时：

1. `EsClientConfig` 创建 ElasticsearchClient；
2. `EsKeywordIndexService.@PostConstruct` 确保共享索引；
3. `KeywordSearchChannel` 进入容器；
4. `KeywordSyncVectorStorePostProcessor` 发现 KeywordIndexService，把真实 VectorStoreService 包成 `KeywordSyncingVectorStoreService`。

于是读写条件不同：

```text
type=es
  ├─ 写：向量写成功后 best-effort 同步 ES
  └─ 读：还需 channels.keyword.enabled=true
```

关键词写失败只记录 warning，不回滚已经成功的向量写；这是 best-effort 双写，不是跨 PG/ES 的原子事务。

即使 query channel=false，只要 type=es，ES client、索引初始化与写装饰器仍会出现。因此外部 ES 不可达可能在共享索引 `@PostConstruct` 阶段暴露，而不是等第一次搜索。

---

## 19.12 LightRAG：后端开关同时影响管理、读取与 best-effort 写同步

当 `rag.graph.type=lightrag` 时：

- LightRagClient 进入容器；
- GraphSearchChannel 进入容器；
- GraphSyncVectorStorePostProcessor 把 VectorStoreService 包成图谱同步装饰器；
- 后台图谱查询/可视化可以调用同一 client。

问答召回仍需要 `channels.graph.enabled=true`。LightRAG 查询失败会返回空图谱证据，写入/删除失败只 warning，不中断向量主链。

冻结 YAML 注释提到“写入由下方 ingestion.enabled 独立控制”，但冻结源码没有找到该配置键的绑定或读取；实际 `GraphSyncVectorStorePostProcessor` 的条件是能否取得 LightRagClient，也就是 `type=lightrag`。因此本教程按实现写：**type 打开后就会织入 best-effort 文档级图谱同步；query enabled 只控制是否参与问答召回。**

这是一个很重要的源码阅读原则：注释与代码不一致时，教程必须记录漂移，不能为了让配置说明“看起来合理”而杜撰一个未接线开关。

### 19.12.1 为什么 type=lightrag、query=false 是合法状态

这种组合可以用于：

- 后台可视化；
- 随文档写入维护图谱；
- 暂不让图谱证据进入 RRF/Rerank。

所以前置校验只拦 `query=true + backend off`，不拦 `backend on + query=false`。

---

## 19.13 Web Search 与 MCP Server 中的 You.com 是两套独立实现

主应用 `WebSearchChannel` 总是一个 Spring Component，但运行期开关需要：

```text
rag.search.channels.web-search.enabled=true
AND 配置 api-key 或环境变量 YDC_API_KEY 非空
```

请求异常、401/429/5xx、格式错误或超时都降级为空结果，不阻断本地检索。

独立 mcp-server 中另有 `YouComSearchMcpExecutor`，它使用 `@ConditionalOnProperty(name="YDC_API_KEY")`，只有环境变量/属性存在才注册工具。两套实现属于不同进程、不同消费者，源码注释明确接受“服务级重复”。

因此可能出现：

| 状态 | 主应用联网检索 | MCP Server You.com 工具 |
|---|---|---|
| channel=false，YDC key 有 | 不参与 RAG | 工具可注册 |
| channel=true，key 无 | `isEnabled=false` | 工具不注册 |
| channel=true，key 有 | 参与 RAG | 工具可注册 |

不能只看到一处 key 就推出两边都已启用。

---

## 19.14 MCP Client 采取“连接失败降级”，而不是启动强依赖

主应用 YAML 默认列出一个 MCP server URL。`McpClientAutoConfiguration.@PostConstruct` 依次：

```text
构建 /mcp URL
  → initialize client
  → listTools
  → 每个远程 Tool 包成 McpClientToolExecutor
  → 注册到 DefaultMcpToolRegistry
```

整段位于 try/catch 中。连接失败时记录 error 并跳过该 server，不继续抛出，所以主应用可以没有远程 MCP 工具而启动。

AgentToolCatalog 后续只会把“意图配置”和“MCP 注册表真实存在工具”的交集桥接给 Agent。MCP 配置里写了 server，不等于远程工具已经进入 Agent；还必须完成连接、发现、注册和目录解析。

这里与对象存储/Redis 的 fail-fast 形成鲜明对比：

| 外部依赖 | 启动失败策略 |
|---|---|
| Redis/Snowflake | 失败上抛，阻止正常启动 |
| 默认对象存储初始化 | 失败上抛 |
| PG Schema/向量初始化 | 触碰失败可上抛 |
| MCP Server | catch 后跳过远程工具 |
| LightRAG 调用 | 查询空结果、写入 warning |
| Web Search 调用 | 空结果降级 |

“外部依赖不可用时怎么办”必须按调用点回答，不能统一说“都有降级”。

---

## 19.15 RAG 模型路由：Chat 与 embedding/rerank/vlm 使用两种选择规则

`AIModelProperties` 把 provider 连接信息与模型候选分开。provider 给 base URL/apiKey/endpoints，candidate 给 id/provider/model/dimension/priority/enable 等。

### 19.15.1 Workflow Chat 走 tier

Chat 不再使用 defaultModel，而是：

```text
请求类型
  ├─ 普通 → default-tier=standard
  ├─ deep thinking → deep-thinking-tier=deep
  └─ 调用点显式 Tier → 对应 tier
           │
           ▼
tier.candidates 的有序 ID
           │
           ├─ 过滤 disabled
           ├─ thinking 时过滤 supportsThinking!=true
           ├─ 过滤 healthStore 暂不可用
           └─ 逐个调用，失败 fallback 下一个
```

`ChatTierConfigValidator` 在启动时检查：

- candidate id 不重复；
- default/deep tier 引用存在；
- 每个 tier 有正 timeout；
- tier candidate 都在注册表；
- Tier 枚举覆盖完整；
- deep tier 至少有一个启用且 supportsThinking 的候选。

这些是结构不变式。provider key 是否有效、远端是否可达仍是运行期问题。

流式模型 fallback 还有第 13 章的边界：首个正文包提交给用户后不再跨模型切换，避免把两个模型输出拼在同一回答里。

### 19.15.2 embedding/rerank/vlm 走 defaultModel + priority

这三组先把 defaultModel 置于队首，其余按 priority、id 排序，过滤 disabled 与 healthStore 不可用候选。`ModelRoutingExecutor` 逐候选调用，异常后标记失败并切下一个，全部失败才抛 RemoteException。

随仓库配置的关键结果：

- embedding 默认远程候选，后续还有本地/另一供应商候选；最终是否可用取决于 endpoint/key/模型；
- rerank 默认真实模型，后面有 `provider=noop` 的候选，所以真实 Rerank 失败可以退到不重排客户端；
- VLM 当前只有一个默认候选，失败没有第二个图生文模型可切。

“rerank.enabled=true”因此不等于“每轮都得到真实模型分数”。当真实候选失败并落到 noop，流程仍能返回排序前/截断后的候选，但证据门对真实 rerank 分的适用边界要按第 12 章理解。

---

## 19.16 Agent 模型不是 Workflow tier 路由的另一个调用点

Agent 使用 `AgentEngineConfiguration` 直接构建一个 AgentScope `OpenAIChatModel`：

```text
agent.chat.provider = siliconflow
agent.chat.model    = deepseek-ai/DeepSeek-V4-Pro
       │
       └─ 到 ai.providers.siliconflow 解析 url/apiKey/endpoints.chat
```

`AgentProperties` 注释明确“单模型无 fallback”。`max-retries=2` 是同一模型单次调用失败的重试次数，不是切换到 Workflow tier 的其他模型。

所以必须分开：

| 能力 | Workflow/RAG LLM | ReAct Agent LLM |
|---|---|---|
| 配置入口 | `ai.chat.tiers` | `agent.chat` + `ai.providers` |
| 候选 | tier 内多个 | 一个 provider/model |
| 跨模型 fallback | 首包前支持 | 无 |
| 重试 | 路由/客户端语义 | AgentScope maxRetries，同模型 |
| thinking 选择 | deep tier 过滤 | ReAct 自身 reasoning，不走该 tier 开关 |

Agent 的 `search_knowledge` 工具内部又会用 embedding、rerank，必要时用 RAG 答案合成配置。一次 Agent 运行因此可能同时依赖“Agent 固定模型”和“RAG 基础模型路由”，但两者责任仍然不同。

---

## 19.17 文档解析也有外部依赖：Parser 已注册不等于 SaaS 可用

冻结源码中 PDF/Word/PPT 的版面解析主实现是 MinerU，配置包含 API URL、key、轮询间隔、超时、OCR 与分布式并发许可。

`MinerUDocumentParser.@PostConstruct` 会通过 Redisson 初始化许可；这一步不向 MinerU SaaS 发业务请求。真正解析时才会：

```text
申请上传链接 → PUT 文件 → 轮询 batch → 下载/解包结果
```

缺 key、远端鉴权失败、网络失败或持续轮询失败会在文档处理链暴露，最终由第 6 章的入库状态/Consumer 失败语义承接。ParserRegistry 中存在 MinerU 只证明 MIME/Profile 可以路由到它，不证明 SaaS 凭据可用。

图片描述使用 VLM；VLM 候选失败的边界与 MinerU 不同。一个文档可能同时依赖对象存储、Redis 许可、MinerU、VLM、embedding 和向量落点，故“上传成功”离“可检索”仍有多层配置条件。

---

## 19.18 三类启动校验：结构矛盾尽量早失败

### 19.18.1 Environment 阶段：通道与后端一致性

`RetrievalConfigEnvironmentPostProcessor` 早于 Bean，拦 keyword/graph 的哑开关，并由 FailureAnalyzer 输出可操作诊断。

### 19.18.2 Properties/Bean 阶段：检索预算与记忆不变式

`SearchChannelProperties.afterPropertiesSet()` 检查：

- final topK > 0；
- recall budget ≥ final topK；
- rerank candidate limit 为正时 ≥ final topK；
- scope min intent 不低于上游过滤下限；
- confidence 在 `(minIntent, 1]`；
- supplement ratio < 1；
- evidence min rerank score ≤ 1。

`MemoryConfigValidator` 在摘要开启时要求 `summaryStartTurns > historyKeepTurns`，否则摘要永远不会触发。

### 19.18.3 Bean 创建/初始化阶段：结构引用与外部基础设施

- ChatTierConfigValidator 检查模型注册表/tier 结构；
- AgentEngineConfiguration 检查 provider/model/url/endpoint 引用；
- Snowflake/Storage/Vector/ES 初始化器触碰相应基础设施；
- MCP 初始化器也触碰远端，但异常被降级吞掉。

早失败的价值不是“项目永远不会出错”，而是把可静态发现的矛盾从一次用户问答提前到启动诊断。网络抖动、密钥失效和模型服务错误仍只能在调用期出现。

---

## 19.19 故障推演树：先问“在哪一层第一次可见”

```text
请求失败/功能缺失
  │
  ├─ 应用根本没启动？
  │    ├─ Environment 配置矛盾
  │    ├─ 缺少候选 Bean（非法 type）
  │    ├─ Properties/tier/memory 不变式失败
  │    └─ @PostConstruct 外部依赖失败（Redis/Storage/PG/ES...）
  │
  ├─ 应用启动，但能力没出现？
  │    ├─ 条件 Bean 未装配（agent/type/You.com）
  │    ├─ runtime enabled=false
  │    ├─ key 为空导致 isEnabled=false
  │    └─ MCP 连接失败，工具注册被跳过
  │
  ├─ 请求进入，但某通道为空？
  │    ├─ 单通道异常/超时降级
  │    ├─ LightRAG/Web 返回空
  │    ├─ scope 没有有效 collection
  │    └─ Evidence Gate 丢掉整批
  │
  ├─ 模型失败？
  │    ├─ Workflow 首包前尝试下一个候选
  │    ├─ 首包后不再跨模型 fallback
  │    ├─ Agent 同模型 retry，无跨模型 fallback
  │    └─ embedding/rerank/vlm 按各自候选列表处理
  │
  └─ 页面断流？
       ├─ 后端业务 finalizer 是否已保存消息
       ├─ SSE 是否发出 finish/cancel/done
       └─ 前端只会新 GET 重试，不是 event resume
```

下面按依赖给出更具体的源码推演：

| 故障 | 首个确定可见点 | 上层表现 | 当前恢复/降级 |
|---|---|---|---|
| Redis 不可达 | Snowflake `@PostConstruct` Lua，或其他初始化 | 主应用启动失败 | 无全局无 Redis 模式 |
| PG 不可达/Schema 缺表 | vector initializer/Mapper | 启动或首次 DB 操作失败 | 无内存数据库替代 |
| S3/OSS 不可达 | StorageInitializer bucket 检查 | 主应用启动失败 | 无本地文件 fallback |
| RocketMQ 发送失败 | ProducerAdapter send | 文档分块/清理/反馈动作失败 | 没有知识主链同步替代 |
| ES type=none | Bean 不存在 | 关键词能力完全不参与 | 合法默认 |
| ES type=es 但不可达 | shared index init 或调用 | 可能启动失败；后续同步 best-effort | 查询依赖 ES，写同步失败不回滚向量 |
| LightRAG 不可达 | 查询/写/后台调用 | 查询空、写 warning、后台空/null | 不阻断向量主链 |
| Web key 缺失 | `isEnabled=false` | 通道不出现 | 本地检索继续 |
| MCP Server 不可达 | McpClient init catch | 远程工具缺席 | 主应用继续 |
| Workflow chat 候选失败 | 模型路由 | 首包前切下一个；全失败 error | 首包后不拼接第二模型 |
| Agent 模型失败 | AgentScope/Agent bridge | Agent error 收尾 | 同模型 maxRetries，无跨模型切换 |
| Embedding 全失败 | 入库或检索 embed | 当前业务失败 | 按候选逐个 fallback 后抛 |
| Rerank 真实模型失败 | RoutingRerankService | 可落 noop | 结果不具真实 rerank 分语义 |
| MinerU 不可用 | 文档解析调用 | 入库任务失败/重试边界 | 轮询瞬时异常重试到 timeout，无另一版面 Parser |

这张表不是运行报告，而是由条件、异常分支和 finalizer 推导的“源码故障地图”。

---

## 19.20 常见配置误读

### 误读一：项目依赖 Milvus SDK，所以默认用 Milvus

不成立。SDK 只在 POM 层；显式 YAML `rag.vector.type=pg` 选择 PG Bean。Milvus 的 matchIfMissing 只在键缺失时兜底。

### 误读二：keyword enabled=false，所以 ES type=es 也完全没有影响

不成立。query channel 不参与，但 ES client/index service 和写同步装饰器仍会装配。

### 误读三：LightRAG query 关闭，所以不会写图谱

按冻结实现不成立。`type=lightrag` 即产生 LightRagClient 和写装饰器；没有找到注释所说的独立 ingestion.enabled 接线。

### 误读四：MCP URL 配了，所以 Agent 一定有远程工具

不成立。还要连接、initialize、listTools、registry 注册、意图与目录交集；连接失败会被跳过。

### 误读五：RAG 有多模型 fallback，所以 Agent 也会自动切模型

不成立。Workflow chat 走 tier；Agent 用固定 provider/model，maxRetries 是同模型重试。

### 误读六：schema_pg.sql 在 resources 下，所以 Spring 会自动执行

不成立。文件不在默认 `schema.sql` 约定位置，源码也没有 Flyway/Liquibase/spring.sql.init 接线；README 使用外部 psql 命令。

### 误读七：某依赖连接失败，系统都会降级

不成立。Redis、对象存储等默认初始化 fail-fast；MCP、LightRAG、Web Search 采用不同程度降级；必须逐调用点确认。

---

## 19.21 面试追问与参考回答

### 问：怎样证明当前默认使用 pgvector，不是 Milvus？

答：先看 YAML 明确 `rag.vector.type=pg`，再看 Pg Store/Retriever/Admin 的条件为 havingValue=pg；Milvus 虽 matchIfMissing=true，但显式 pg 已让其条件不成立。最后看 `t_knowledge_vector` Schema 与 PgVector SQL，形成配置、Bean、数据结构三方证据。

### 问：支持混合检索为什么默认只有向量？

答：能力实现与默认装配分层。ES/LightRAG/Web 类存在，但默认 keyword/graph type=none、所有可选 query channel=false；MultiChannelRetrievalEngine 只执行容器内且 isEnabled 的通道。当前默认是向量，打开可选通道还需要后端和连接条件。

### 问：项目如何防止配置打开了通道但忘记配置后端？

答：EnvironmentPostProcessor 在 Bean 创建前检查 keyword/graph 的 type 与 enabled，发现 backend off + channel on 直接抛 RetrievalConfigException，再由 FailureAnalyzer 给二选一修复建议。Web Search 机制不同，缺 key 时 isEnabled=false，并不启动失败。

### 问：为什么 Redis 故障可能阻止启动？

答：Redis 不只做 cache。SnowflakeIdInitializer 在 PostConstruct 执行 Redis Lua 分配节点 ID，失败上抛；Storage/Vector 初始化还可能用 Redisson lock。它属于默认协调基础设施。

### 问：Agent 与 RAG 模型配置有什么本质差别？

答：RAG chat 由 ai.chat tier 选择多个候选并在首包前 fallback；Agent 由 agent.chat 指定一个 provider/model，解析 provider 连接信息后构建 AgentScope model，只有同模型 maxRetries，没有跨模型 fallback。Agent 工具内部仍可能调用 RAG 的 embedding/rerank 等路由。

### 问：哪些外部系统失败会降级？

答：需要按 owner 分。MCP 连接失败跳过远程工具，LightRAG/Web Search 调用失败降为空，ES/LightRAG 写同步是 best-effort；Redis ID 初始化、对象存储桶初始化等则 fail-fast。不能用一个“统一熔断降级”概括。

### 问：配置变更是否都能热生效？

答：不能。application.yaml 与条件 Bean 通常在启动时决定拓扑，需要重启；Agent 人设和工具目录由数据库/注册表指纹驱动懒重建，可在下一次取 Agent 时生效。前端 settings 页也是只读运行配置投影，不负责保存 YAML。

---

## 19.22 源码定位卡

### 构建与入口

- `pom.xml`
- `.mvn/wrapper/maven-wrapper.properties`
- `bootstrap/pom.xml`
- `bootstrap/src/main/java/com/nageoffer/ai/ragent/RagentApplication.java`
- `mcp-server/pom.xml`
- `mcp-server/src/main/java/com/nageoffer/ai/ragent/mcp/McpServerApplication.java`
- `frontend/package.json`
- `frontend/vite.config.ts`
- `.github/workflows/ci.yml`

### 默认配置与 Schema

- `bootstrap/src/main/resources/application.yaml`
- `resources/database/schema_pg.sql`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/OrchestrationProperties.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/SearchChannelProperties.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/config/AIModelProperties.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/config/AgentProperties.java`

### 条件装配与初始化

- `agent/src/main/java/com/nageoffer/ai/ragent/agent/config/ConditionalOnAgentEngine.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/config/AgentEngineConfiguration.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/StorageClientConfig.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/StorageInitializer.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/VectorSpaceInitializer.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/MilvusConfig.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/EsClientConfig.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/KeywordSyncVectorStorePostProcessor.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/GraphSyncVectorStorePostProcessor.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/distributedid/SnowflakeIdInitializer.java`

### 通道、模型与降级

- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/MultiChannelRetrievalEngine.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/channel/WebSearchChannel.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/graph/LightRagClient.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/mcp/McpClientAutoConfiguration.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/model/ModelSelector.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/model/ModelRoutingExecutor.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/model/ChatTierConfigValidator.java`

### 配置诊断

- `rag/src/main/resources/META-INF/spring.factories`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/validation/RetrievalConfigEnvironmentPostProcessor.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/validation/RetrievalChannelConfigValidator.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/validation/RetrievalConfigFailureAnalyzer.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/validation/MemoryConfigValidator.java`

---

## 19.23 读完本章必须能回答的自检题

1. POM、YAML、条件 Bean、`isEnabled` 四级证据分别能证明什么？
2. 为什么七个 Maven 模块只形成主应用和独立 MCP Server 两类进程入口？
3. Java 字段默认 workflow 与仓库 YAML 默认 agent 为什么不冲突？
4. Agent 档下为什么确定性 RAG Controller 和核心仍然存在？
5. 如何用配置、Bean 与 Schema 三份证据证明默认 pgvector？
6. 为什么 Schema 文件不能等同于应用自动迁移？
7. `rag.default.dimension` 与 `vector(1536)`、embedding 返回维度必须怎样对齐？
8. 为什么关闭 RAG rate limit 不能得到“无 Redis 模式”？
9. storage type 非法与 S3 endpoint 不可达分别在哪一层失败？
10. keyword/graph 的 backend type 与 query enabled 为什么要分成两道门？
11. type=es、query=false 时 ES 仍会承担什么责任？
12. 冻结源码中 LightRAG 写入实际受哪个条件控制？为什么 YAML 注释不能覆盖实现？
13. Web Search 缺 key、MCP Server 不可达、Redis 不可达的失败策略分别是什么？
14. Workflow tier fallback 与 Agent maxRetries 有何本质差别？
15. 为什么 rerank enabled=true 不保证一定使用真实 rerank 模型？
16. 如何从“首次可见层”推演一个配置或依赖故障？

读到这里，你已经可以从一份 YAML 反推出系统默认拓扑，也能解释可选能力为什么存在却没有参与当前主链。下一章会把前 19 章压缩成可画、可讲、可追问的面试叙述：不虚构运行成绩或个人改造，而是用 owner、调用链、状态、失败和设计权衡证明真正读懂源码。
