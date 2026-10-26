# 第 45 章：学习问答源码核对记录

> 核对日期：2026-09-11。只读静态核验；不运行产品、数据库或模型，不把 ChatGPT 回答本身当作实现证据。

## 整理范围

学习对话涵盖用户身份、Redis 用户运行槽、AgentRunHandle 唯一收尾、SSE 传输、Spring Boot/Maven 分工五组回答；另补入 token 传递和用户级并发的澄清。正文按问题重写，删除重复类比和页面噪声。附带的 AgentRunHandle 卡片在读取时只提供标题，相关正文依据对话收尾回答与源码整理。

不将聊天侧栏、账号信息、其他对话标题、私人会话 URL 或完整页面快照加入仓库。问题标题为主题归纳，不冒充逐字引文。

## 版本与证据边界

- 主实现：`zz1403489227-crypto/AsterRAG@98894c2c42c015a3c874c6b3c986ac863c85b731`，保持原来源锁。
- 上游对照：`nageoffer/ragent@ca93991abe4ffd838e48d600d7ada24e010a884f`，仅比较下列五个文件。
- 不移动冻结版本，不将新增上游能力宣称为当前 fork 的实现。
- 设计理由、并发改造和外部工具副作用案例是教学推演。
- 下面的行号用于定位方法入口；结论依据方法体及相邻调用关系，不仅依据关键字出现。

<a id="identity-sources"></a>

## 身份与前端请求

| 文件 | 本次核对点 |
|---|---|
| [AuthServiceImpl.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/system/src/main/java/com/nageoffer/ai/ragent/user/service/impl/AuthServiceImpl.java#L41) | 登录返回 token |
| [SaTokenConfig.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/system/src/main/java/com/nageoffer/ai/ragent/user/config/SaTokenConfig.java#L57) | 登录先于上下文，排除与派发分支 |
| [UserContextInterceptor.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/system/src/main/java/com/nageoffer/ai/ragent/user/config/UserContextInterceptor.java#L62) | 从登录身份查询用户，并在 afterCompletion 清理 |
| [UserContext.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/framework/src/main/java/com/nageoffer/ai/ragent/framework/context/UserContext.java#L28) | 线程上下文保存 LoginUser |
| [authStore.ts](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/frontend/src/stores/authStore.ts#L39) | 前端保存登录凭据 |
| [storage.ts](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/frontend/src/utils/storage.ts#L3) | localStorage 存储 |
| [agentChatStore.ts](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/frontend/src/stores/agentChatStore.ts#L648) | Authorization；调用方 retryCount=1 |
| [AgentConversationServiceImpl.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/service/impl/AgentConversationServiceImpl.java#L113) | 会话条件包含用户属主 |
| [StreamTaskManager.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/framework/src/main/java/com/nageoffer/ai/ragent/framework/web/StreamTaskManager.java#L142) | 停止鉴权、owner 缺失的竞态与任务清理 |

<a id="gate-sources"></a>

## 运行槽与共享记忆

| 文件 | 本次核对点 |
|---|---|
| [AgentRunGate.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentRunGate.java#L53) | 用户键、原子占位、TTL 和比较释放 |
| [AgentChatServiceImpl.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/service/impl/AgentChatServiceImpl.java#L107) | 释放钩子先归还闸门，再安排记忆任务 |
| [AgentMemoryPipeline.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/memory/AgentMemoryPipeline.java#L83) | 按会话 claim，读取用户记忆，带 revision/watermark 提交 |

<a id="finalization-sources"></a>

## 句柄与事件桥

| 文件 | 本次核对点 |
|---|---|
| [AgentRunHandle.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentRunHandle.java#L137) | CAS、异常捕获与 finally 的实际顺序 |
| [AgentStreamEventBridge.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentStreamEventBridge.java#L321) | 落库异常内部返回 null，三条出口的差异 |
| [SseEmitterSender.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/framework/src/main/java/com/nageoffer/ai/ragent/framework/web/SseEmitterSender.java#L88) | 连接层 closed 与关闭逻辑 |

<a id="sse-sources"></a>

## SSE 后端与前端

| 文件 | 本次核对点 |
|---|---|
| [AgentChatController.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/controller/AgentChatController.java#L44) | 冻结版 chat 与 stop，无 confirm |
| [AgentSSEEventType.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/enums/AgentSSEEventType.java#L26) | 冻结版七种正式事件 |
| [useAgentStream.ts](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/frontend/src/hooks/useAgentStream.ts#L137) | GET、解析器、重试默认值、无 terminated 检查 |
| [AgentChatServiceImpl.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/service/impl/AgentChatServiceImpl.java#L169) | 尚未 settled 时连接结束触发取消 |

<a id="build-sources"></a>

## 构建与启动

| 文件 | 本次核对点 |
|---|---|
| [pom.xml](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/pom.xml#L53) | 根 POM 的依赖、模块与插件管理 |
| [bootstrap/pom.xml](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/bootstrap/pom.xml#L47) | 启动模块实际启用 Boot 打包插件 |
| [RagentApplication.java](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/bootstrap/src/main/java/com/nageoffer/ai/ragent/RagentApplication.java#L29) | 启动与扫描入口 |
| [bootstrap/src/main/resources/application.yaml](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/bootstrap/src/main/resources/application.yaml#L1) | 端口 9090、context-path、token-name、SSE 配置 |

<a id="upstream-diff"></a>

## 较新上游的差异核对

| 文件 | 在上游对照提交中确认的内容 |
|---|---|
| [useAgentStream.ts](https://github.com/nageoffer/ragent/blob/ca93991abe4ffd838e48d600d7ada24e010a884f/frontend/src/hooks/useAgentStream.ts#L153) | 只请求一次、GET/POST、缺少 done 检查；不能回写为冻结版行为 |
| [AgentChatController.java](https://github.com/nageoffer/ragent/blob/ca93991abe4ffd838e48d600d7ada24e010a884f/agent/src/main/java/com/nageoffer/ai/ragent/agent/controller/AgentChatController.java#L55) | 工具确认 POST 返回新的 SseEmitter |
| [AgentSSEEventType.java](https://github.com/nageoffer/ragent/blob/ca93991abe4ffd838e48d600d7ada24e010a884f/agent/src/main/java/com/nageoffer/ai/ragent/agent/enums/AgentSSEEventType.java#L41) | 新增 block 和 confirm 事件 |
| [AgentStreamEventBridge.java](https://github.com/nageoffer/ragent/blob/ca93991abe4ffd838e48d600d7ada24e010a884f/agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentStreamEventBridge.java#L206) | 异常提示与中断消息持久化、finish/done；待确认发 confirm/done |
| [pom.xml](https://github.com/nageoffer/ragent/blob/ca93991abe4ffd838e48d600d7ada24e010a884f/pom.xml#L17) | 聊天所列主要版本仍需按冻结 POM 解释，而非认为所有差异均来自版本号 |

## 对原回答的关键修订

1. UserContext 存 LoginUser；浏览器仍通过 Authorization 发送 token。
2. 冻结版 RuntimeContext 构造只显式填 userId/sessionId，不把 taskId/replyToMessageId 画进去。
3. 用户级闸门是主流并发策略；先释放闸门再安排异步记忆抽取。
4. CAS 是一个 RunHandle 内的至多一次入口；不是跨进程 exactly-once 或写库成功证明。
5. persistAssistantMessage 内捕获普通落库异常并返回 null，仍可能继续发 finish/done。
6. 区分冻结版错误关闭与较新上游保存中断消息的行为。
7. 区分冻结版重试和较新上游 streamOnce；冻结调用方实际设置 retryCount=1。
8. confirm、block、POST 流与缺少 done 检查只标为对照版事实。
9. finally、deleteAsync、TTL 不等于故障下外部清理已成功。
10. Boot 与 Maven 是职责划分；解释依赖管理/实际依赖、插件管理/实际启用及 9090 默认端口。

## 验证范围

- 文件 SHA 与行锚点记录在 [request-study-source-map.json](request-study-source-map.json)。
- 使用已有后端教程审计，另检查本次新增正文的相对链接、锚点、代码围栏、版本对应与敏感路径。
- 不新增模拟产品测试，不启动应用；文档检查不证明产品运行成功。
- 实际检查结果见 [PROGRESS.md](../PROGRESS.md) 中的本次记录。

[阅读第 45 章](../docs/45-agent-request-study-qa.md) · [全书来源锁](SOURCES.lock.md)
