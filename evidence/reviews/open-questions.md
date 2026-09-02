# P1 待核验问题

> 原则：问题未关闭前，教程正文不得把对应内容写成确定事实。

| ID | 问题 | 当前源码结论 | 后续证据 | 状态 |
|---|---|---|---|---|
| Q-001 | AsterRAG 当前默认启用了哪些检索通道，哪些只是可选实现？ | 随仓库 YAML 只启用向量通道，后端选择 pgvector；关键词、图谱、联网通道均默认关闭。四类通道实现仍存在，启用后由 `MultiChannelRetrievalEngine` 并行调度。 | P4 启动后查询 `/rag/settings` 并保存真实检索 Trace。 | resolved-source |
| Q-002 | 文档上传后，正常情况下由哪个入口触发入库任务，节点的实际默认顺序是什么？ | 上传只保存对象与 `PENDING` 文档。显式 `/knowledge-base/docs/{doc-id}/chunk` 经事务消息和 Consumer 调用固定 `DefaultIngestionKernel` 五步。`/ingestion/tasks` 是要求显式 Pipeline ID 的独立同步子系统；未发现默认种子顺序。知识文档 `PIPELINE` 模式当前明确暂停。 | P3 跑一条真实上传→分块→可召回链并保存 MQ、表和索引证据。 | resolved-source |
| Q-003 | 确定性 RAG SSE 的事件顺序、消息落库和 Trace 收尾分别由谁负责？ | 正常由 `StreamChatEventHandler` 保存 `NORMAL` 后发 `FINISH/DONE`；取消只在有正文时保存 `INTERRUPTED` 后发 `CANCEL/DONE`；失败不保存 assistant 失败消息。排队拒绝另存 `REJECTED` 并发 `META/REJECT/FINISH/DONE`。`StreamChatTraceRunner` 包装 callback 收尾 Run。 | 执行 Handler/Trace 聚焦测试并实跑正常、取消、错误；重点确认取消在 Trace 中的最终状态。 | partial-source |
| Q-004 | Agent 正常、取消、失败三条收尾路径是否都会保存 State、释放闸门并安排长期记忆抽取？ | `AgentRunHandle` 证明三路都会 unregister 并执行释放钩子；`AgentChatServiceImpl` 登记了释放闸门、驱逐本节点 State 缓存和安排长期记忆抽取。正常/取消会保存业务 assistant 消息，失败不会。应用适配层本身不能证明 AgentScope 在所有异常时点都成功保存内部 State。 | 执行现有 RunHandle/Bridge/ChatService 测试；检查 AgentScope 2.0.2 依赖源码并实跑取消/失败后的 `t_agent_state`。 | partial-source |
| Q-005 | RocketMQ 在当前默认配置是否必需，哪些业务路径真正使用事务消息？ | 随仓库 YAML 会启用 Producer/Template，三个 listener 容器自动启动；应用自己的 producer 配置无业务开关。文档分块和知识库删除使用事务消息，反馈提交/取消使用普通消息。详见 `evidence/mq-census.md`。 | P3 在隔离 Broker 上实跑事务消息、消费重试和停机故障；这属于 Integration 证据，不再影响源码/依赖级结论。 | resolved-source-dependency |
| Q-006 | 前端聊天页分别怎样处理 RAG SSE 与 Agent SSE，它们是否共享事件协议？ | 已确认 RAG 使用 `useStreamResponse + chatStore`，Agent 使用 `useAgentStream + agentChatStore`，后端也有不同 enum/handler；因此不能先验视为同一协议。 | 逐事件建立后端→前端映射，实测 finish/cancel/reject/error 和刷新恢复。 | partial-source |
| Q-007 | 作者公开教程中的 4 模块和 Spring Boot 3.5.7 描述，与 AsterRAG 当前 7 模块/Boot 4.1.0 之外还有哪些漂移？ | 已登记 Schema 22/21→31 的口径差、默认 Agent 档、pgvector 默认、多通道“支持/默认启用”差别，以及可配置入库 Pipeline 与当前固定知识文档主链的边界；详见 `reference-drift.md`。 | 后续逐章引用作者文章时继续增量登记，不把本次清单视为永久封闭。 | resolved-reference-source |
