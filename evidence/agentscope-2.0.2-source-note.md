# AgentScope 2.0.2 依赖源码核对记录

## 身份

- 项目声明：根 `pom.xml` 的 `agentscope.version=2.0.2`。
- 依赖坐标：`io.agentscope:agentscope-core:2.0.2`。
- Sources artifact：`https://repo1.maven.org/maven2/io/agentscope/agentscope-core/2.0.2/agentscope-core-2.0.2-sources.jar`。
- Sources JAR SHA-256：`2122af96aca74bc4ce1e9faa5b0d9663b125093e7ce6f7b99996415b3952e6fc`。
- 文件大小：645688 bytes。
- 核对日期：2026-09-01。

该 artifact 只用于解释 AsterRAG 已锁定依赖的运行语义，不把 AgentScope 的所有通用能力都写成 AsterRAG 已接入能力。项目自己的适配、配置和调用点仍以冻结 AsterRAG 源码为主证据。

## 第 14 章使用的方法

- `io/agentscope/core/ReActAgent.java`
  - `buildAgentStream` / `streamEvents`：一次调用的 Agent 事件生命周期。
  - `doCall` / `CallExecution#doCallInner`：按 `(userId, sessionId)` 激活状态并进入本轮。
  - `coreAgent` / `executeIteration` / `reasoning`：从第 0 轮开始的推理阶段。
  - `runPostReasoningPipeline` / `isFinished`：没有 ToolUseBlock 时结束，有工具调用时进入 acting。
  - `acting` / `actingStream` / `executeToolCalls`：执行工具、把结果反馈给下一轮。
  - `summarizing`：达到 `maxIters` 后补错误工具结果并再调用模型生成当前执行总结。
  - `buildGenerateOptions`：把 `maxRetries` 传为 `ExecutionConfig.maxAttempts`。
- `io/agentscope/core/tool/Toolkit.java`
  - `callTools`：依据 ToolkitConfig 的 parallel 选项批量执行工具。
- `io/agentscope/core/tool/ToolkitConfig.java`
  - 默认 `parallel=true`。
- `io/agentscope/core/agent/RuntimeContext.java`
  - `userId/sessionId` 是本轮身份；attributes 不持久化；call-scoped AgentState 由运行期挂入。

## 已确认边界

1. 当前 AsterRAG Builder 传入 `maxIters=10`，AgentScope 在 `iter >= maxIters` 时进入 summarizing，而不是直接把运行标失败。
2. 当前 AsterRAG Builder 传入 `maxRetries=2`；AgentScope 2.0.2 把该值落到 `maxAttempts=2`，语义是最多两次尝试（初次 + 一次重试），不是“初次 + 两次重试”。
3. 单次 reasoning 没有工具调用即结束；有工具调用则进入 acting，结果进入上下文后再开始下一轮 reasoning。
4. AsterRAG 使用默认 `new Toolkit()`，同一轮多个获准工具调用沿 AgentScope 默认 `parallel=true` 执行。
5. `streamEvents` 支持每次订阅自己的事件 sink 和 CallExecution；AsterRAG 仍额外用 `AgentRunGate` 限制同一用户同时只有一条 Agent 流。

## 不据此扩大的能力

- AgentScope 源码包含 HITL、permission、subagent、skills、structured output 等通用设施；AsterRAG 没有因依赖中存在这些类就自动完成相应产品接线。
- 教程只描述 AsterRAG Builder、Toolkit、RuntimeContext 和事件桥真实触达的分支；未被项目配置或调用的库能力不作为当前项目功能。
