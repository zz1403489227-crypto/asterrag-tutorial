# RocketMQ 使用点与默认启动边界

> 核验对象：AsterRAG `98894c2c42c015a3c874c6b3c986ac863c85b731`  
> 核验层级：冻结源码 + `rocketmq-spring-boot` 2.3.6 依赖字节码 + Hermetic 单元测试  
> 尚未替代：P3 真实 Broker 上的事务消息、消费重试和数据库/索引结果证据

## 1. 结论先行

当前默认配置不能把 RocketMQ 理解成“装了但不用”的可选组件：

1. AsterRAG 自己的 `RocketMQAutoConfiguration` 没有业务开关，直接要求 `RocketMQTemplate` 并暴露唯一的 `MessageQueueProducer`。
2. 随仓库 `application.yaml` 默认给出 NameServer 和 Producer Group，因而满足 starter 创建 Producer 与 `RocketMQTemplate` 的条件。
3. 三个 `@RocketMQMessageListener` Bean 会注册为自动启动的消费者容器；依赖字节码显示容器 `isAutoStartup()` 返回 `true`，`start()` 直接调用 `DefaultMQPushConsumer.start()`，失败会包装成 `IllegalStateException`。
4. `RocketMQTemplate.afterPropertiesSet()` 会启动默认 Producer。因此，在随仓库默认档下，应用启动会主动进入 RocketMQ 生命周期；不能承诺“没有 Broker 也可按默认配置正常启动”。
5. 真正使用事务消息的是“文档开始分块”和“删除知识库后的物理清理”两条路径；问答反馈使用普通同步发送，再由消费者异步落库。

这里的“默认必需”限定为：**按随仓库 YAML 和当前组件扫描启动完整应用时，RocketMQ 是被主动初始化的运行依赖**。这不等于所有 Java 类或所有 Hermetic 测试都必须连接 Broker。

## 2. 自动装配为何会生效

### 2.1 应用自己的桥接配置

`sources/AsterRAG/framework/src/main/java/com/nageoffer/ai/ragent/framework/config/RocketMQAutoConfiguration.java:30-42` 是普通 `@Configuration`：

- 始终创建 `DelegatingTransactionListener`；
- `MessageQueueProducer` 的构造参数直接要求 `RocketMQTemplate`；
- 没有 `@ConditionalOnProperty`、`@Profile` 或 fallback producer。

默认配置位于 `sources/AsterRAG/bootstrap/src/main/resources/application.yaml:327-331`：

```yaml
rocketmq:
  name-server: 127.0.0.1:9876
  producer:
    group: ragent-producer${unique-name:}_pg
    send-message-timeout: 2000
```

### 2.2 starter 2.3.6 的条件与生命周期

`scripts/inspect-mq-starter.sh` 对已解析的依赖 JAR 执行 `javap`，原始输出保存在 `evidence/runtime/p3-mq-starter-bytecode-2026-09-01.txt`。关键字节码事实为：

- starter 的 `RocketMQAutoConfiguration` 在 `rocketmq.name-server` 上 `matchIfMissing=true`；默认 Producer 还要求 `rocketmq.name-server` 与 `rocketmq.producer.group`；
- `rocketMQTemplate` 在 Producer 或 Pull Consumer 存在时创建；
- `RocketMQTemplate.afterPropertiesSet()` 调用 `DefaultMQProducer.start()`；
- `DefaultRocketMQListenerContainer.isAutoStartup()` 返回真；
- Consumer 容器的 `start()` 调用 `DefaultMQPushConsumer.start()`，捕获 `MQClientException` 后抛出 `IllegalStateException("Failed to start RocketMQ push consumer")`。

这份依赖级证据只回答 starter 的确定行为；P3 集成实验仍需记录实际进程在完整中间件栈中的启动顺序和故障表现。

## 3. 全仓业务使用矩阵

| 路径 | 生产者入口 | 消息类型 | 本地事务或发送语义 | Consumer | 最终副作用 |
|---|---|---|---|---|---|
| 文档分块 | `KnowledgeDocumentServiceImpl.startChunk` | 事务消息 | 在 Spring 事务中把文档从非 `RUNNING` 改为 `RUNNING`，写 operator/updateTime，并 upsert schedule | `KnowledgeDocumentChunkConsumer` | 恢复 `UserContext` 后调用 `executeChunk`，进入解析、分块、嵌入、索引与状态结算 |
| 知识库删除 | `KnowledgeBaseServiceImpl.delete` | 事务消息 | 先要求知识库下无未删除文档，再在本地事务中逻辑删除知识库 | `KnowledgeBaseCleanupConsumer` | best-effort 清向量空间、对象目录；配置存在时再清关键词与图谱。任一项失败则抛异常触发重试 |
| 点赞/点踩 | `MessageFeedbackServiceImpl.submitFeedbackAsync` | 普通消息 | `RocketMQTemplate.syncSend`；不与业务数据库事务绑定 | `MessageFeedbackConsumer` | 校验 assistant 消息归属并 upsert 反馈；用提交时间避免乱序覆盖 |
| 取消反馈 | `MessageFeedbackServiceImpl.cancelFeedbackAsync` | 普通消息 | 与反馈提交相同 | `MessageFeedbackConsumer` | upsert cancelled feedback |

源码锚点：

- 文档事务发送：`sources/AsterRAG/rag/src/main/java/com/nageoffer/ai/ragent/knowledge/service/impl/KnowledgeDocumentServiceImpl.java:197-232`
- 删除事务发送：`sources/AsterRAG/rag/src/main/java/com/nageoffer/ai/ragent/knowledge/service/impl/KnowledgeBaseServiceImpl.java:228-265`
- 反馈普通发送：`sources/AsterRAG/rag/src/main/java/com/nageoffer/ai/ragent/rag/service/impl/MessageFeedbackServiceImpl.java:52-89`
- 通用 Producer：`sources/AsterRAG/framework/src/main/java/com/nageoffer/ai/ragent/framework/mq/producer/RocketMQProducerAdapter.java:45-95`
- 三个消费者：`KnowledgeDocumentChunkConsumer.java:38-57`、`KnowledgeBaseCleanupConsumer.java:43-105`、`MessageFeedbackConsumer.java:35-50`

## 4. 事务消息的两级恢复语义

`DelegatingTransactionListener` 有两个不同生命周期的表：

```text
发送所在实例
  txId -> Consumer<Object>         只在当前进程内、只允许消费一次
            |
            +-- executeLocalTransaction -> Spring TransactionTemplate

Broker 后续回查
  topic -> TransactionChecker     每个实例启动时重新注册，可查询持久数据库
            |
            +-- 文档：document 存在且 status == RUNNING => COMMIT
            +-- 知识库：逻辑删除后 selectById 不可见 => COMMIT
```

关键边界：

- per-message 本地回调不是持久状态。发送异常或非 `SEND_OK` 会移除；执行时也以 `remove` 取出，所以不能执行两次。
- Broker 回查不依赖这个进程内回调，而是按 topic 找 checker，再查数据库事实。
- 回查无 checker 时返回 `ROLLBACK`；checker 抛异常时返回 `UNKNOWN`。
- 文档 checker 只能证明“开始分块的本地事务已提交”，不能证明解析、向量化或索引成功。
- 知识库 checker 只能证明逻辑删除可见性，物理资源清理仍由幂等 Consumer 重试完成。

源码锚点：

- `sources/AsterRAG/framework/src/main/java/com/nageoffer/ai/ragent/framework/mq/producer/DelegatingTransactionListener.java:41-105`
- `sources/AsterRAG/rag/src/main/java/com/nageoffer/ai/ragent/knowledge/mq/KnowledgeDocumentChunkTransactionChecker.java:47-65`
- `sources/AsterRAG/rag/src/main/java/com/nageoffer/ai/ragent/knowledge/mq/KnowledgeBaseCleanupTransactionChecker.java:46-62`

## 5. 已执行的 Hermetic 证据

`RocketMQProducerAdapterTest` 在 JDK 17 容器中实际执行 4 个用例，全部通过：

- Broker 调用抛异常后，进程内回调被删除；
- 非 `SEND_OK` 后，进程内回调被删除；
- 回调已执行但结束事务调用再抛异常时，不会二次执行本地事务；
- 成功发送时，本地事务只消费一次。

原始日志：`evidence/runtime/p3-hermetic-framework-2026-09-01.txt`。日志中的 `broker unavailable` 是 Mockito 注入的预期异常；最终结果是 `Tests run: 4, Failures: 0, Errors: 0` 和 `BUILD SUCCESS`。

## 6. 真实 Broker 阶段必须再证明什么

- Topic/Consumer Group 在隔离的 `unique-name` 下创建并启动；
- 文档事务消息的 half message、本地事务提交、Consumer 消费与最终 `SUCCESS/FAILED` 状态可串成同一 docId；
- 注入一次 Consumer 失败后，重试不会重复写脏 Chunk 或向量；
- 删除知识库时，逻辑删除、Broker 回查和物理清理的时间差可观测；
- Broker 停机时，应用启动或业务调用的真实失败点与日志；
- 产品自带 Compose 使用固定 `container_name` 和宿主端口，不能直接拿来覆盖服务器已有服务；教程集成栈必须使用独立 project name、容器名和非冲突端口。

## 7. 问题状态

Q-005 更新为 `resolved-source-dependency`：全仓使用点、starter 条件和默认生命周期已由源码/依赖字节码确认。真实 Broker 的成功、重试与故障注入仍属于 P3 Integration 验证，不会因本问题关闭而省略。
