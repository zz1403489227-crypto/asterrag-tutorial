# 第 14 章：为什么还需要 Agent——确定性 Pipeline 与 ReAct Runtime

> 第 8～13 章已经证明，固定 RAG Pipeline 能完整完成一次知识问答。那么为什么项目还要增加 Agent？
>
> 答案不是“Agent 比 RAG 更高级”，也不是“ReAct 把原来的 Pipeline 全部删掉”。当前实现让 Agent 成为动态决策层，把确定性 RAG 收进一个知识检索工具；当问题只需查资料时，Agent 调用这条窄口，当问题还需要业务数据或多个工具时，Agent 决定组合和迭代。

## 14.1 先用一句话区分两条主链

```text
Workflow：代码提前决定下一步做什么
Agent：模型根据本轮上下文和工具 Schema 决定下一步做什么
```

这不是“有没有 LLM”的区别。Workflow 的改写、歧义判断、生成同样调用 LLM；区别在于**控制流的所有者**：

- Workflow 中，`StreamChatPipeline.execute` 的 Java 分支决定加载记忆、改写、分类、短路、检索和生成的固定顺序；
- Agent 中，`ReActAgent` 每轮先让模型产生正文或 ToolUseBlock，再由 Runtime 执行工具，并把结果送回下一轮模型推理。

可以把它们看成：

```text
确定性 RAG = 一个有严格输入输出契约的知识问答子程序
ReAct Agent = 可以选择是否、何时、以什么组合调用多个子程序的运行时
```

---

## 14.2 当前默认是 Agent，但 Workflow 接口没有消失

`application.yaml` 当前显式配置：

```yaml
ragent:
  engine:
    type: agent
```

`@ConditionalOnAgentEngine` 等价于只在 `ragent.engine.type=agent` 时装配 Agent Controller、Service、RunGate、Provider、ToolCatalog 和记忆中间件。因此当前默认配置会注册 `/agent/v1/*` 主链。

但 `RAGChatController` 的 `/rag/v3/chat` 没有挂这个条件注解，源码注释也明确写着“RAG v3 接口不受影响”。所以 engine type 更准确的含义是：

- 决定 Agent 架构是否装配及哪些 Prompt 槽位生效；
- 不会物理删除确定性 RAG 的 Bean 和接口；
- Agent 还需要调用 RAG 组件完成 `search_knowledge`。

`OrchestrationMode.of` 对空白或未知配置回落 `WORKFLOW`；而 Agent Bean 只有属性值为 agent 才注册。切换属于部署级决策，需要重启，不是管理员页面上的热切换按钮。

### 14.2.1 为什么不把两条链硬塞进一个 Controller

两条链的协议和状态都不同：

```text
/rag/v3/chat    → RAG SSE、RAG conversation/message、固定 Pipeline
/agent/v1/chat  → Agent SSE、Agent conversation/message/block、ReAct State
```

如果只在一个方法里按 if/else 切换，事件类型、会话表、取消语义和前端回放很容易互相污染。当前实现用独立入口保留两条协议，再在更窄的知识能力层复用组件。

---

## 14.3 两条链分别擅长什么

| 维度 | 确定性 Workflow | ReAct Agent |
|---|---|---|
| 控制流 | Java Pipeline 固定 | 模型在每轮决定直接答或调工具 |
| 知识问答 | 原生主链 | 调用 `search_knowledge` 工具 |
| 多工具组合 | 先按意图树固定执行 KB/MCP | 可在一轮发出多个工具调用，也可根据结果补调 |
| 模型调用次数 | 由固定阶段上界约束 | 随推理轮数、工具结果和总结变化 |
| 延迟/成本 | 相对可预测 | 更动态，最坏受 maxIters 约束 |
| 可解释性 | 阶段和短路点固定 | 需要保存 reasoning/tool/answer block 轨迹 |
| 恢复状态 | RAG 消息+摘要 | AgentScope State + Agent 展示消息分离 |
| 适合问题 | 单一知识回答、确定流程 | 需要判断工具、组合数据、根据结果继续行动 |

这里的“适合”是基于当前控制流的工程解释，不是质量评测结论。没有真实评测数据时，不能声称 Agent 对所有问题的准确率更高。

---

## 14.4 Agent 请求从哪里开始

`GET /agent/v1/chat` 接收 question 和可选 conversationId，并用 `agent.sse-timeout-ms` 创建 emitter。当前默认15分钟，因为一次 Agent 运行可能包含多轮模型和工具调用。

`AgentChatServiceImpl.streamChat` 的顺序是：

```text
解析 userId / conversationId / taskId
        ↓
AgentRunGate.acquire
        ↓
发送 META
        ↓
touch Agent conversation
        ↓
建立长期记忆抽取下界（若启用）
        ↓
持久化本轮 user message
        ↓
创建 AgentRunHandle + 注册释放钩子
        ↓
ReActAgentProvider.getAgent
        ↓
创建 AgentStreamEventBridge
        ↓
注册 task / 建 RuntimeContext
        ↓
agent.streamEvents(question, runtimeContext)
        ↓
订阅 event / error / complete
        ↓
绑定 disposable + agent.interrupt
```

它和 RAG Pipeline 最明显的差异，是没有在 Service 中写死“改写→意图→检索→生成”。Service 只负责搭好一次运行的身份、资源、事件桥和取消接线，真正的下一步交给 ReAct 循环。

---

## 14.5 RunGate 为什么必须在所有副作用之前

`AgentRunGate` 使用 Redis key：

```text
ragent:agent:running:{userId}
value = taskId|conversationId
```

`setIfAbsent` 失败就拒绝请求，因此**同一用户跨所有 conversation 同时只能运行一条 Agent 流**。这个限制不是“同会话只能一条”，而是用户维度的一条。

闸门在发送 META、创建会话、保存 user message 和登记 task 之前获取。这样一个被拒绝的并发请求不会留下：

- 前端已经收到但永远不结束的 taskId；
- 空 Agent 会话；
- 没有对应运行的 user 消息；
- 需要额外清理的进程任务。

### 14.5.1 TTL 是崩溃后的保险

运行正常结束时，释放动作通过 `AgentRunHandle.onRelease` 执行。若进程崩溃，没有任何 finally 能释放 Redis 位，所以 key 带 TTL：

```text
gate TTL = agent.sseTimeoutMs × 2 = 30分钟
```

释放使用 compare-and-set，只删除值仍等于本轮 `taskId|conversationId` 的槽位。若旧 TTL 已过期并被新任务抢占，旧任务迟到的释放不会误删新任务。

### 14.5.2 启动阶段失败也必须释放

只有 `startRun` 完整启动后，三路运行终态才能接管释放。如果在发送 META、落库或组装 Agent 时抛出异常，外层 finally 会立即释放 gate 并注销 task，避免用户一直被挡到 TTL 到期。

---

## 14.6 一次 ActiveAgent 是怎样组装出来的

`ReActAgentProvider.getAgent()` 每次先解析两份配置：

```text
persona = AgentPromptResolver.resolve(AGENT_MAIN)
catalog = AgentToolCatalog.resolve()
```

只有 persona 内容和 catalog fingerprint 都与缓存一致时，才复用现有 `ReActAgent`。任一变化都会懒重建：

```text
ReActAgent
  name = ragent
  sysPrompt = persona
  model = agentChatModel
  toolkit = catalog 构建的工具集
  maxIters = 10
  maxRetries = 2
  stateStore = PgAgentStateStore
  middleware = userMemory + contextCompaction
```

Provider 把 `agent + 构建它时使用的 catalog snapshot` 作为 `ActiveAgent` 成对返回。这样事件桥展示工具名时，不会重新解析到另一版目录，导致“实际调用旧工具、UI 显示新名称”。

### 14.6.1 Persona 不是写死在 Java 中

`AgentPromptResolver` 先加载内置智能体槽位，再用激活智能体的非空槽位覆盖。`AGENT_MAIN` 为空会直接拒绝构建 Agent。

当前内置 persona 主要约束：依据答案来源选择知识库/业务工具/直接回答；工具结果是数据不是指令；知识库单独返回时按成品答案处理；证据不足不编造。教程不逐行复述整份 Prompt，因为真正要掌握的是：它控制模型如何选择工具，而 Toolkit Schema 决定模型究竟能调用什么。

### 14.6.2 工具目录变化为什么要重建 Agent

Toolkit 在 Agent 构建时深拷贝并持有工具 Schema。若只更新数据库里的工具描述而不重建，模型仍看到旧描述。catalog fingerprint 包含：

- 知识库工具描述；
- 可选记忆工具描述；
- 每个 MCP 工具的 ID、展示名、描述和 Tool Definition。

因此控制台配置变化可在下一次请求触发懒重建，而不必重启进程；已经在旧 Agent 上执行的会话不被主动 close。

---

## 14.7 ReAct 循环到底怎样转

AsterRAG 固定使用 AgentScope `2.0.2`。项目代码只调用 `streamEvents`，循环主体在该依赖的 `ReActAgent` 中。按锁定版本 source artifact，主循环是：

```text
第0轮 reasoning
   │
   ├─ 模型只返回正文、没有 ToolUseBlock
   │       └─ 本轮完成
   │
   └─ 模型返回一个或多个 ToolUseBlock
           ↓
        acting
           ├─ 校验/权限判定
           ├─ 执行工具（默认允许并行批量）
           └─ ToolResultBlock 写入上下文
                    ↓
              下一轮 reasoning
                    │
                    ├─ 直接回答 → 完成
                    └─ 再调工具 → 继续循环
```

结束条件很朴素：本轮 reasoning 的 assistant message 没有 `ToolUseBlock`，就认为完成；即使模型请求了不存在的工具，也先进入 acting，让 Toolkit 返回“工具不存在”的错误结果，再由下一轮模型决定如何响应。

### 14.7.1 Reasoning 不等于把思维链全部存成一段字符串

模型流会产生 `ThinkingBlockDeltaEvent`、`TextBlockDeltaEvent`、`ToolCallStart/Delta/End` 等细粒度事件。AgentScope 同时把完成的 assistant/tool result message 写进它自己的会话 context；AsterRAG 的 `AgentStreamEventBridge` 再把可见增量投影为 reasoning/answer/tool blocks。

因此有三个层次：

```text
AgentScope Msg/ContentBlock  = Runtime 的推理与工具上下文
AgentEvent                  = 本轮运行的增量事实流
AsterRAG AgentBlock         = 面向前端回放的业务投影
```

它们不是同一张表里的同一种记录，第 16 章会展开状态所有权。

### 14.7.2 RuntimeContext 提供本轮身份

AsterRAG 只显式传入：

```java
RuntimeContext.builder()
    .userId(userId)
    .sessionId(conversationId)
    .build()
```

AgentScope 用 `(userId, sessionId)` 选择本轮 AgentState slot，工具和中间件也从同一个 RuntimeContext 读取身份。RuntimeContext 的属性袋只在单次 call 中有效，不自动持久化；持久状态由 AgentStateStore 负责。

---

## 14.8 RAG 在 Agent 中变成了什么

`AgentToolCatalog` 永远注册一个 `search_knowledge`。模型决定调用后：

```text
KnowledgeSearchTool
   ↓ 取 Agent 展示消息最近2轮，只用于指代改写
KnowledgeSearchFacade.search
   ↓
改写/拆分
   ↓
意图解析后只保留 KB intent
   ↓
歧义引导
   ↓
RetrievalEngine（复用第 10～12 章）
   ↓
清理 internal docId，不生成 citation/sources
   ↓
KB_ANSWER Prompt，history 为空
   ↓
LLMService.chat，temperature=0，thinking=false
   ↓
返回一份可直接引用的答案文本
```

这里不是把整个 `/rag/v3/chat` 当 HTTP 工具调用，也不是复用 `StreamChatPipeline.execute`。它抽出一个更窄的同步门面，复用知识检索核心，但去掉不适合工具返回的外围职责：

- 不创建 RAG conversation/message；
- 不发送 RAG SSE；
- 不装配 `sources` 或数字角标；
- 不把 Agent 全历史交给知识回答合成；
- 只把最近两轮给改写阶段做指代消解；
- 返回最终答案字符串作为 ToolResultBlock。

因此“RAG 变成 Tool”指的是**能力被包成工具契约**，不是原有 RAG Controller 被 Agent 直接套壳。

---

## 14.9 为什么动态问题需要 Agent

设想用户问：

```text
“先查退款制度，再查我的订单当前是否满足退款条件。”
```

这只是用于解释控制流的设计推演，不声称项目内置了真实订单工具。若工具目录里确有对应 MCP 工具，Agent 可以：

```text
reasoning 0
  ├─ search_knowledge(退款制度)
  └─ order_query(当前订单状态)
        ↓ 默认并行执行
tool results
        ↓
reasoning 1
  ├─ 证据够 → 综合回答
  └─ 参数/结果缺失 → 追问或换参数补调
```

固定 Pipeline 也能被专门编写成这条流程，但每增加一种业务组合就要增加代码分支。ReAct 的价值在于把“选择哪个已注册工具、是否需要第二轮”交给模型；它的代价则是调用次数和路径不再完全由代码提前决定。

---

## 14.10 maxIters 与 maxRetries 控制的不是同一件事

当前配置：

```text
maxIters = 10
maxRetries = 2
```

### 14.10.1 `maxIters=10`

它限制 reasoning→acting 循环的 reasoning 轮数。达到上限时，AgentScope 不是立即抛错，而是：

1. 为仍 pending 的 ToolUseBlock 补 ERROR ToolResult；
2. 发布 `ExceedMaxItersEvent`；
3. 再调用模型，要求直接总结当前已完成情况；
4. 最终消息标记 `GenerateReason.MAX_ITERATIONS`。

AsterRAG 的事件桥收到 `EXCEED_MAX_ITERS` 时发送 hint：“已达到最大迭代次数，正在生成当前执行结果的总结”，但最终有 `AgentResult` 时仍按正常完成保存，而不是自动标为 error。

所以迭代上限是“停止继续行动并生成当前总结”的护栏，不是简单 HTTP 500。

### 14.10.2 `maxRetries=2` 的源码语义

AsterRAG 注释把它写成“单次模型调用失败重试次数”，但 AgentScope 2.0.2 实际将该值传给 `ExecutionConfig.maxAttempts(2)`。锁定版本的准确语义是：**一次模型调用最多尝试2次，即初次 + 1次重试**。

这也是为什么教程要继续查看固定依赖源码，不能只凭本项目字段名推断。

### 14.10.3 Agent 外层模型没有候选 fallback

`AgentEngineConfiguration` 直接从 `agent.chat.provider/model` 构造一个 `OpenAIChatModel`。当前是 SiliconFlow 的 `deepseek-ai/DeepSeek-V4-Pro`，没有经过第 13 章的 `RoutingLLMService` 候选、首包 fallback 和健康熔断。

但 `search_knowledge` 内部合成调用的是共享 `LLMService.chat`，所以内层知识子程序仍可使用 AI model routing。必须区分：

```text
主 Agent reasoning model：单模型 + maxAttempts
知识 Tool 内部 LLM：RoutingLLMService 的候选 fallback
```

---

## 14.11 事件桥让动态路径仍能回放

`AgentStreamEventBridge` 只选择产品需要的 AgentEvent：

```text
TextBlockDelta      → message(type=response)
ThinkingBlockDelta  → message(type=think)
ToolCallStart       → tool(status=start)
ToolResultTextDelta → 累积工具结果
ToolResultEnd       → tool(status=end, ok/result)
HintBlock           → hint
ExceedMaxIters      → MAX_ITERATIONS hint
AgentResult         → 终答兜底
```

它还把事件按出现顺序整理成 `AgentBlock`：reasoning、answer、tool。工具事件到来会封口当前文本块，工具结束后再来的正文会开启新 block。因此数据库不仅有最终 content，还能回放“先想→调工具→看结果→再回答”的轨迹。

工具结果持久化最多保留64000字符，避免异常大结果无限放大展示消息；这个上限只针对业务回放 block，不等于 AgentScope 内部模型上下文的统一 token budget。

---

## 14.12 Agent 的取消链比 RAG 接得更完整

`AgentChatServiceImpl.bindEmitterLifecycle` 把 emitter 的三种信号都接到 `taskManager.cancel(taskId)`：

```text
onTimeout
onError
onCompletion
```

主动 `/agent/v1/stop` 则走 `cancelByUser`。TaskManager 触发时：

1. `runHandle.interruptUpstream` 先 dispose Reactor subscription；
2. 再调用 `agent.interrupt(userId, conversationId)` 设置该 slot 的中断状态；
3. EventBridge 的 cancel finalizer 保存已有 reasoning/answer/tool 轨迹；
4. 发送 cancel/done；
5. `AgentRunHandle` 注销 task 并执行所有 release hooks。

release hooks 当前包括：

- 释放 Redis RunGate；
- 驱逐该会话的进程内 Agent state cache；
- 异步触发长期记忆抽取（若启用）。

这与第 8 章发现的当前 RAG emitter 接线边界不同：Agent 明确把断页、超时和 emitter error 连接到上游 ReAct 中断，而不是只结束浏览器输出。

---

## 14.13 为什么 Agent 不能完全替代 Workflow

Agent 带来的动态性也产生新的成本：

### 14.13.1 模型调用次数更不稳定

一次知识问答可能包含：主 Agent 判断工具、知识 Tool 内部改写/合成、主 Agent 读取结果后再回答。复合任务还可能多轮补调。Workflow 的阶段数更固定。

### 14.13.2 终答受两层 Prompt 约束

知识 Tool 先按 KB Prompt 合成成品，主 Agent persona 再决定原样输出或与其他工具组合。任何一层改动都可能改变用户最终看到的文本，因此 persona、工具描述和 KB Prompt 要分别治理。

### 14.13.3 可预测性更低

同一个意图分类结果在 Workflow 中确定进入固定 scope；Agent 在更外层先决定是否调用知识工具。错误既可能来自工具选择，也可能来自工具内部检索。排障时必须先判断“没调用”还是“调用了但没检索到”。

### 14.13.4 状态更多

Agent 除展示消息外，还有 AgentScope State、RuntimeContext、上下文压缩、长期记忆、运行闸门、工具轨迹。它需要更严格的 owner 和生命周期分层。

因此保留 Workflow 的价值不是“落后版本兼容”，而是它仍然提供一条控制流固定、延迟更可预期、容易按阶段解释的知识问答路径。

---

## 14.14 哪些能力共享，哪些必须隔离

| 能力 | 两条链的关系 |
|---|---|
| 文档入库、Chunk、向量/关键词/图索引 | 完全共享，同一份知识底座 |
| 改写、意图、scope、多通道检索、后处理 | Agent 的 KnowledgeSearchFacade 复用 |
| `KB_ANSWER` Prompt | 两种模式共用槽位 |
| MCP executor/registry | Workflow 直接按意图执行；Agent 适配成原生工具 |
| RAG `ConversationMemoryService` | Workflow 使用；Agent 不把它当主会话状态 |
| AgentScope `AgentStateStore` | Agent 专用 |
| RAG sources/citation | Workflow 使用；Agent Knowledge Tool 显式关闭 |
| SSE 协议和消息表 | 分开维护 |
| 主生成模型 | Workflow 走 RoutingLLMService；Agent 外层走单 OpenAIChatModel |

这一张表是理解整个项目“共享底座、分离编排”的关键。共享过少会复制检索逻辑，共享过多则会把 RAG 的来源面板、Agent 的工具轨迹和两套会话状态强行混在一起。

---

## 14.15 常见误解校正

### 误解一：Agent 模式关闭了 `/rag/v3/chat`

没有。Agent Bean 条件装配，但 RAG v3 Controller 不受该条件影响。默认配置选择 Agent 主架构，不等于删除 Workflow 接口。

### 误解二：Agent 不再使用意图分类和检索 Pipeline

不对。主 Agent 先决定是否调用 `search_knowledge`；工具内部仍执行改写、KB-only 意图、歧义、检索、后处理和 KB 合成。

### 误解三：maxIters=10 表示最多调用10次工具

不准确。它限制 ReAct reasoning iteration；一轮可以产生多个工具调用，Toolkit 默认可并行执行。达到上限后还会多一次总结模型调用。

### 误解四：maxRetries=2 表示失败后再重试两次

按 AgentScope 2.0.2 实现不是。它落到 `maxAttempts=2`，即包含初次在内最多两次尝试。

### 误解五：主 Agent 也使用第 13 章的模型熔断

不使用。主 Agent 是单个 `OpenAIChatModel`；只有知识工具内部的共享 `LLMService` 仍走模型路由。

### 误解六：Agent 的最终文字就是完整运行轨迹

不是。最终 content、thinking、AgentBlock 展示轨迹和 AgentScope State 是不同投影；仅保存最终文字无法恢复工具调用顺序。

---

## 14.16 面试追问与回答骨架

### 问：既然 RAG Pipeline 已经完整，为什么还要 Agent？

Pipeline 解决确定性知识问答；Agent 解决运行时工具选择、复合工具组合和按结果继续行动。项目没有重写检索，而是用 KnowledgeSearchFacade 把 RAG 核心封成 `search_knowledge` 工具。

### 问：两种架构的根本区别是什么？

不是是否使用 LLM，而是控制流 owner。Workflow 由 Java 分支决定固定阶段；ReAct 由模型输出 ToolUseBlock 驱动 reasoning/acting 循环，Runtime 负责执行和护栏。

### 问：Agent 模式下 RAG 的哪些部分被复用？

改写、KB-only 意图、歧义、scope、多通道检索、后处理和 KB_ANSWER 合成。RAG 会话/SSE、sources、citation 和历史合成不进入该工具窄口。

### 问：一次 ReAct 迭代是什么？

先 reasoning：模型结合上下文和工具 Schema 输出正文或 ToolUseBlock；无工具即完成，有工具则 acting 执行，把 ToolResult 写回上下文，再进入下一轮 reasoning。

### 问：如何防止 Agent 跑飞？

当前有同用户单流 RunGate、15分钟 SSE timeout、maxIters=10、模型 maxAttempts=2、取消时 dispose+interrupt，以及达到迭代上限后的总结收尾。它们分别限制并发、总生命周期、循环轮数和单次模型尝试。

### 问：为什么 RunGate 要在发送 META 和落库之前？

拒绝的请求不应制造任何业务副作用。否则会留下空会话、孤立 user 消息或前端已经看到但永远不执行的 taskId。

### 问：Agent Persona 或工具配置变化怎样生效？

每次 getAgent 都解析 persona 和 catalog snapshot；二者内容指纹不匹配就懒重建 Agent。ActiveAgent 把实例与其目录快照成对返回，保证运行工具和展示名一致。

---

## 14.17 源码定位卡

### AsterRAG 冻结源码

- `bootstrap/src/main/resources/application.yaml`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/OrchestrationMode.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/OrchestrationProperties.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/config/ConditionalOnAgentEngine.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/config/AgentProperties.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/config/AgentEngineConfiguration.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/config/ReActAgentProvider.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/controller/AgentChatController.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/service/impl/AgentChatServiceImpl.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentRunGate.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentRunHandle.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentStreamEventBridge.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/tool/AgentToolCatalog.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/tool/KnowledgeSearchTool.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/KnowledgeSearchFacade.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/prompt/AgentPromptSlot.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/prompt/AgentPromptResolver.java`
- `resources/database/init_data_pg.sql`
- `pom.xml`

### 锁定依赖源码

- Maven：`io.agentscope:agentscope-core:2.0.2:sources`
- `io/agentscope/core/ReActAgent.java`
- `io/agentscope/core/agent/RuntimeContext.java`
- `io/agentscope/core/tool/Toolkit.java`
- `io/agentscope/core/tool/ToolkitConfig.java`
- 校验和与使用方法见 `evidence/agentscope-2.0.2-source-note.md`。

---

## 14.18 读完本章，你应该能自己回答

1. Workflow 与 Agent 的控制流 owner 分别是谁？
2. `ragent.engine.type=agent` 注册了什么，又没有关闭什么？
3. RunGate 为什么是用户级而不是 conversation 级？
4. persona 与 catalog fingerprint 为什么共同决定 Agent 是否重建？
5. ReAct 的 reasoning、acting、ToolResult 和下一轮怎样衔接？
6. `search_knowledge` 复用了 RAG 哪些阶段，删掉了哪些外围职责？
7. maxIters、maxAttempts 和 SSE timeout 各限制什么？
8. 为什么主 Agent 没有第 13 章的候选模型 fallback？
9. AgentEvent、AgentBlock 和 AgentState 为什么不能合并成一个概念？
10. Agent 的断线取消链为什么比当前 RAG emitter 接线更完整？

下一章将打开 Agent 的“行动能力”：`search_knowledge`、记忆整理和 MCP 工具怎样从目录快照、描述和 JSON Schema 变成可执行的 ToolResult，又怎样把参数缺失、工具不可用和错误结果反馈给下一轮模型。
