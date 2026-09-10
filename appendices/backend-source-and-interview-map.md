# 后端源码与面经对照

这份附录用于查证，不是正文的阅读前提。先按第 35～44 章理解流程，再来定位代码和题源。

## 一、资料范围

- 产品实现固定为 AsterRAG `98894c2c42c015a3c874c6b3c986ac863c85b731`；沿用全书来源归属。
- 简历范围：Java、Spring Boot、MyBatis-Plus、PostgreSQL、Redis、SSE；检索存储及 AgentScope/MCP、Python 只讲必要的连接边界。
- 本次只读检索面经数据库中 accepted 且 quality_score ≥ 7 的记录，并回读代表题。记录编号是库内定位标识，不是市场出现次数或真实面试概率。
- 面经是应聘者的公开经验叙述，不能作为某公司固定考纲或技术正确性的权威依据。技术解释由产品源码和官方文档支撑。
- 这里只公开归纳主题与公开帖子链接，不分发数据库、原题全集、作者私人信息或内部路径。组合模拟问答不是原帖逐字摘录。

## 二、为什么选择这些章节

| 从项目切入的问题 | 面经记录编号 | 基础追问 | 项目章 → 基础章 | 公开题源 |
|---|---|---|---|---|
| Agent 里 Redis 和数据库做什么 | 1474、1476、1477 | 类型、用途差异 | 35/38 → 43 | [百度后端二面](https://www.nowcoder.com/feed/main/detail/bba6d0ac6de74df8a215d5e7dbb2c80e) |
| 会话如何存储 | 726、727、729 | 字段、Redis 类型、语义缓存 | 37 → 42/43 | [百度大模型开发实习一面](https://www.nowcoder.com/feed/main/detail/7653bea1b037490b97c8bf473371a3c8) |
| Spring 怎样注入依赖 | 307、309 | 注解、MyBatis 参数安全 | 36/37 → 41 | [腾讯后台 Agent 一面](https://www.nowcoder.com/feed/main/detail/5a6705afdb45487e852c29bad27575d5) |
| 共享 Service 会不会串数据 | 1441、1443、1444、1445 | 集合、ConcurrentHashMap、DI、单例 | 36/39 → 40/41 | [百度后端一面](https://www.nowcoder.com/feed/main/detail/958e45d5456a4f9b8246e07c53f4b412) |
| 删除过程异常是否回滚 | 327 | 有事务方法调用普通方法 | 37 → 41 | [腾讯后端 Agent 一面](https://www.nowcoder.com/feed/main/detail/e97f7836e506423fb750561ce054926f) |
| 事务注解如何生效 | 6 | AOP 动态代理 | 36/37 → 41 | [美团后端 AI 实习一面](https://www.nowcoder.com/feed/main/detail/f358b3a4f6854f159a52f4237d023069) |
| Redis 闸门怎么取得与释放 | 461、462 | SETNX、租期、owner | 38 → 43 | [京东后端 Agent 一面](https://www.nowcoder.com/feed/main/detail/f4faa7d5858e4c16947ad46e4f9f7a35) |
| Agent 缓存怎么设计 | 1094 | key、上下文、版本、失效 | 35/38 → 43 | [字节 AI Agent 一面](https://www.nowcoder.com/feed/main/detail/8b2fdbdf61184235bc4210760250663e) |
| Lua/锁遇到故障怎么办 | 1140、1142 | 原子、恢复、Redis 为什么快 | 38 → 43 | [腾讯二面](https://www.nowcoder.com/feed/main/detail/2c61378d66314d0494c0491b36c7bd77) |
| 数据库与搜索副本怎么同步 | 1103、1115、1116 | 双写、重试、锁边界 | 37/38 → 42/43 | [快手秋招面经](https://www.nowcoder.com/feed/main/detail/38659bd44a0141a48715a52b0300332c) |
| 并行检索任务异常怎么知道 | 783、784、786、787、789 | 锁、异常类型、线程终止 | 39 → 40 | [快手 Agent 实习一面](https://www.nowcoder.com/feed/main/detail/be29f78d1c174fe2ab2af85f89f6b792) |
| SSE 高并发哪里卡 | 403 | 连接、调度、资源容量 | 39 → 44 | [腾讯金融科技 AI 实习](https://www.nowcoder.com/feed/main/detail/0fab92ecf694420dae6b27c2df28d40b) |
| 线程池里任务怎样等待 | 657 | 线程状态、sleep/wait、死锁 | 39 → 40 | [美团后端 Agent 一面](https://www.nowcoder.com/feed/main/detail/4e2aff1a23bd47b2a401a3526a89a20d) |
| 索引如何提高查询效率 | 463、1446、1447、1448、1449 | 计划、事务、联合索引缺中间列 | 37 → 42 | [京东一面](https://www.nowcoder.com/feed/main/detail/f4faa7d5858e4c16947ad46e4f9f7a35)、[百度一面](https://www.nowcoder.com/feed/main/detail/958e45d5456a4f9b8246e07c53f4b412) |
| Redis 底层怎么组织数据 | 1262、1263 | 编码、类加载 | 36/38 → 40/43 | [小红书 Agent 一面](https://www.nowcoder.com/feed/main/detail/223fa82f976b4418b214894bd7d941fd) |
| 缓存失效与持久化 | 1347、1430、1478、1482、1484 | 穿透/击穿/雪崩、RDB/AOF、淘汰 | 38 → 43 | [蚂蚁 Agent 一面](https://www.nowcoder.com/feed/main/detail/6490526c86124f92b79a993e171f7222)、[去哪儿 AI 面](https://www.nowcoder.com/feed/main/detail/6f6ca6dd2c644f15a60a1b68f27489c8)、[百度二面](https://www.nowcoder.com/feed/main/detail/bba6d0ac6de74df8a215d5e7dbb2c80e) |

取舍：题库也包含秒杀库存、Kafka、数据库分片等问题，不因此扩写整套课程。Redis 搜索框模糊查询（记录 1292）也不在本次重点范围；本文只引用相关帖的速度和类型问题。数据库题中 MySQL 专属的日志、聚簇索引和锁，仅作与 PostgreSQL 的必要区别，不宣称项目使用 MySQL。

## 三、可点击源码索引

以下链接均锁定同一产品提交，而不是随 main 变化。更细的完整路径和用于静态复核的符号片段见 [source map](../evidence/backend-source-map.json)。该映射证明位置可查，不代替对调用关系的人工阅读。

| 编号 | 源码 | 使用章节 |
|---|---|---|
| S01 | [pom.xml](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/pom.xml) | 35、36、40、41 |
| S02 | [RagentApplication.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/bootstrap/src/main/java/com/nageoffer/ai/ragent/RagentApplication.java) | 36 |
| S03 | [application.yaml](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/bootstrap/src/main/resources/application.yaml) | 35、36、38、44 |
| S04 | [AgentEngineConfiguration.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/config/AgentEngineConfiguration.java) | 36 |
| S05 | [ConditionalOnAgentEngine.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/config/ConditionalOnAgentEngine.java) | 36 |
| S06 | [ReActAgentProvider.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/config/ReActAgentProvider.java) | 36、40 |
| S07 | [AgentChatController.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/controller/AgentChatController.java) | 35、39、44 |
| S08 | [AgentChatServiceImpl.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/service/impl/AgentChatServiceImpl.java) | 35、38、39 |
| S09 | [AgentConversationServiceImpl.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/service/impl/AgentConversationServiceImpl.java) | 36、37、41 |
| S10 | [AgentMessageDO.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/dao/entity/AgentMessageDO.java) | 37、41 |
| S11 | [AgentStateMapper.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/dao/mapper/AgentStateMapper.java) | 37、41、42 |
| S12 | [PgAgentStateStore.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/state/PgAgentStateStore.java) | 35、37 |
| S13 | [AgentRunGate.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentRunGate.java) | 38、43 |
| S14 | [StreamTaskManager.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/framework/src/main/java/com/nageoffer/ai/ragent/framework/web/StreamTaskManager.java) | 35、38、40、41 |
| S15 | [AgentRunHandle.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentRunHandle.java) | 35、39、40 |
| S16 | [AgentStreamEventBridge.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentStreamEventBridge.java) | 37、39 |
| S17 | [SseEmitterSender.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/framework/src/main/java/com/nageoffer/ai/ragent/framework/web/SseEmitterSender.java) | 39 |
| S18 | [UserContextInterceptor.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/system/src/main/java/com/nageoffer/ai/ragent/user/config/UserContextInterceptor.java) | 36 |
| S19 | [UserContext.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/framework/src/main/java/com/nageoffer/ai/ragent/framework/context/UserContext.java) | 36、40 |
| S20 | [DataBaseConfiguration.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/framework/src/main/java/com/nageoffer/ai/ragent/framework/config/DataBaseConfiguration.java) | 36、41 |
| S21 | [ThreadPoolExecutorConfig.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/config/ThreadPoolExecutorConfig.java) | 39、40 |
| S22 | [MultiChannelRetrievalEngine.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/MultiChannelRetrievalEngine.java) | 39 |
| S23 | [PgVectorStoreService.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/PgVectorStoreService.java) | 37、42 |
| S24 | [KeywordSyncingVectorStoreService.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/decorator/KeywordSyncingVectorStoreService.java) | 37、43 |
| S25 | [GraphSyncingVectorStoreService.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/core/vector/decorator/GraphSyncingVectorStoreService.java) | 37 |
| S26 | [schema_pg.sql](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/resources/database/schema_pg.sql) | 37、42 |

## 四、关键结论怎么查

| 结论 | 核查顺序 |
|---|---|
| Agent 默认启用 | S03 配置 → S05 条件 → S07/S08 入口 |
| 每轮状态和共享 Agent 不混为一谈 | S08 new 本轮对象 → S15/S16 → S06 缓存 Agent 与目录 |
| 会话和框架状态都在 PG，但用途不同 | S09/S10 消息 → S11/S12 payload → S26 表结构 |
| 删会话不是一个跨系统事务 | S09 delete/deleteBatch/afterCommit → S14 取消 → S06 本机驱逐 |
| Redis 是用户粒度闸门，不是 watchdog 锁 | S13 key/acquire/release/ttl → S03 超时值 |
| 取消标记补注册时序，不保证历史补发 | S14 register/bindHandle/publishCancel/cancelLocal/isCancelled |
| 业务收尾与网络结束不同 | S15 settle → S16 完成/取消/落库异常 → S17 closed |
| 超时不保证下游已停止 | S22 withTimeout → S21 线程池 → 相应客户端边界 |
| 多索引写入不是强一致事务 | S23 主向量写 → S24/S25 best-effort 同步 |
| 索引存在不等于 SQL 全部命中 | S26 DDL 与 S09 实际过滤/排序、S23 JSON 表达式对照 |

## 五、基础资料如何使用

Java 以 JDK 17 API/JLS 为主要解释口径；PostgreSQL 基础引用 17 版文档，不据此推定部署版本；Spring、Redis、MyBatis 的官方资料用于核对通用契约。正文对应段落已给出直接链接。官方库当前支持某能力，不等于冻结项目使用了它。

第一部分的“当前行为”来自产品源码；第二部分的教学 SQL、缓存设计、fencing、可靠清理、容量估算和模拟问答均是原理解释或设计推演。没有产品启动、真实数据库查询、模型调用、评测分数或性能提升数字。

[从第 35 章开始](../docs/35-backend-request-map.md) · [返回首页](../README.md)
