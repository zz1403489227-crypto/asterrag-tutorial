# 第 15 章：Agent 拿什么行动——工具目录、知识检索、MCP 与参数校验

> 增补衔接：[第 25 章](25-agentic-rag-interview-focus.md) 将知识工具和 [21～24 章检索专题](21-hnsw-vector-index.md) 连起来。重点区分“Agent 选择 query 工具”与“工具内部按配置选通道”，以及“返回合成答案”与“返回原始证据”。

> 第 14 章解释了 ReAct 怎样在“推理”和“行动”之间循环。本章只回答行动侧的核心问题：模型究竟看见哪些工具，工具描述和参数 Schema 从哪里来，调用怎样落到知识检索或 MCP 服务，错误又怎样回到下一轮推理。
>
> 最重要的边界是：AsterRAG 有两套 MCP 参数链。Workflow 先用独立 LLM 提取参数并分成三种结局；Agent 则让主模型按工具 Schema 直接产生参数，再由 AgentScope 校验。它们共享 MCP 执行器，不共享参数控制流。

## 15.1 先建立完整心智模型

Agent 的工具系统可以分成控制面和执行面。

```text
控制面：决定“模型能看见什么”

Prompt 槽位          意图树中的 MCP 叶子          MCP 注册表中的执行器
    │                         │                          │
    └─────────────── AgentToolCatalog.resolve ─────────┘
                              │
                      ResolvedCatalog 快照
                    ┌─────────┼──────────┐
                    │         │          │
             search_knowledge │    MCP 工具交集
                              │
                       flush_memory
                       （满足条件才有）
                              │
                      fingerprint + Toolkit

执行面：决定“一次调用怎样完成”

主模型输出 ToolUseBlock
          ↓
AgentScope 按 JSON Schema 校验
          ↓
找到 AgentTool 并调用 callAsync
          ↓
知识检索 / 记忆管道 / MCP 远端工具
          ↓
ToolResultBlock(SUCCESS 或 ERROR)
          ↓
写回 ReAct 上下文，进入下一轮 reasoning
```

这张图先回答三个问题：

1. MCP Server 发现了一个工具，不等于主 Agent 一定能看到它；
2. 模型选择工具，不等于模型可以绕过 Schema 和服务端身份边界；
3. 工具返回错误，不必立刻终止整条 Agent 运行，错误块会成为下一轮模型的输入。

---

## 15.2 一个 AgentTool 到底向模型承诺什么

AsterRAG 的三个适配器都实现 AgentScope 的 `AgentTool`：

- `KnowledgeSearchTool`：固定知识库工具；
- `MemoryFlushTool`：可选记忆整理工具；
- `McpToolBridge`：把已有 MCP executor 适配成 Agent 工具。

它们共同暴露四类契约：

| 契约 | 方法 | 作用 |
|---|---|---|
| 稳定标识 | `getName()` | 模型输出的 tool name 必须与它匹配 |
| 路由语义 | `getDescription()` | 告诉模型什么问题应该调用这个工具 |
| 参数协议 | `getParameters()` | JSON Schema，约束字段、类型、必填项和枚举等 |
| 执行结果 | `callAsync()` | 返回 `ToolResultBlock`，状态是成功、错误或其他运行态 |

因此“接了一个工具”不只是写一个 Java 方法。工具描述影响选不选择，Schema 影响怎么调用，结果文本影响下一轮怎么回答。任何一层含糊，都会把错误推迟到后面的 ReAct 轮次。

### 15.2.1 展示名不是工具名

系统内部仍使用稳定的英文 tool ID，例如：

```text
search_knowledge
flush_memory
weather_query
```

`ResolvedCatalog.displayNameOf()` 另存一份面向 SSE 的展示名，例如“知识库检索”。展示名用于前端解释过程，不能替代协议中的 tool name；否则一改中文文案就会破坏模型调用和执行器查找。

### 15.2.2 readOnly 不是“绝对不会出问题”

`KnowledgeSearchTool.isReadOnly()` 返回 true；`McpToolBridge` 只在 MCP `annotations.readOnlyHint=true` 时返回 true，未声明就保守地返回 false。

这只是工具的副作用元数据，不代表成功、幂等或低成本。查询仍可能超时、失败或消耗外部配额。并且当前 AsterRAG 这些适配器是直接实现 `AgentTool` 的 legacy 形态，没有配置一套面向用户的 AgentScope 工具审批流程，所以不能把这个标记讲成“当前系统会弹窗审批写工具”。

---

## 15.3 AgentToolCatalog：不是工具列表，而是一次可复现的目录快照

`AgentToolCatalog.resolve()` 每次请求前读取当前配置，生成 `ResolvedCatalog`。随后 `buildToolkit(catalog)` 只使用这份快照，不再回读注册表。

这个顺序解决了一个一致性问题：

```text
错误做法：先算指纹 → 注册表变化 → 再从新注册表建 Toolkit
结果：指纹代表 A，实际 Toolkit 却是 B

当前做法：先冻结 ResolvedCatalog
          ├─ 用它算 fingerprint
          ├─ 用它建 Toolkit
          └─ 用它保存 displayNames
结果：三者来自同一版本
```

第 14 章中的 `ActiveAgent` 又把 Agent 实例和这份 catalog snapshot 成对保存。于是一次运行期间，模型看到的 Schema、实际调用的工具和 SSE 展示名不会跨版本漂移。

### 15.3.1 三类工具的注册规则不同

| 工具 | 出现条件 | 缺失时的行为 |
|---|---|---|
| `search_knowledge` | 永远固定注册，且描述槽位非空 | `KNOWLEDGE_TOOL_DESCRIPTION` 为空直接拒绝构建 |
| `flush_memory` | 长期记忆开启，且记忆工具描述非空 | 不注册；开启但描述为空时重建阶段告警 |
| MCP 工具 | 意图树已启用配置，且注册表中存在同 ID executor | 不注册，并把 ID 记入 unavailable 列表，重建阶段告警 |

知识检索是 Agent 的基础能力，所以描述缺失是硬错误；记忆整理是可选能力，所以用“不开工具”降级；远端 MCP 可能暂时离线，所以不可用项不拖垮整个 Agent。

### 15.3.2 MCP 使用“双重门控”

MCP 工具集不是远端 `tools/list` 的原样复制，而是求交集：

```text
Agent 可见 MCP 工具
  = 意图树中已启用的 MCP 叶子节点
  ∩ 当前 McpToolRegistry 中真实存在的 executor
```

这两侧各自承担不同责任：

- 意图树是产品配置门：决定这个部署想向 Agent 暴露什么能力，并可提供更适合路由的描述和展示名；
- MCP 注册表是运行可用门：证明当前进程确实有一个可调用的执行器。

所以有两种不进入 Toolkit 的情况：

- 服务端发现了工具，但意图树未配置：隐藏；
- 意图树配置了工具，但服务没连上：记为 unavailable 并告警。

这种交集比“远端发现什么就全给模型”更容易控制工具面，也避免给模型一个实际上无法执行的名字。

### 15.3.3 同一个 MCP 工具可以被多个意图节点引用

`resolveMcpToolBindings` 先按 `mcpToolId` 分组。若多个叶子指向同一工具：

- 展示名取第一个非空节点名；
- 路由描述把不同的非空节点描述按换行拼接；
- Toolkit 最终只注册一个同名执行器。

也就是说，意图树可以从多个业务表达解释同一个底层工具，但不能在 Toolkit 中注册多个相同 ID 的副本。

### 15.3.4 为什么 fingerprint 要包括完整 Tool Definition

目录指纹包含：

- 知识工具描述；
- 可选记忆工具描述；
- MCP 的 tool ID、展示名、路由描述；
- MCP executor 提供的完整 `Tool definition`。

若远端给 `weather_query` 新增必填参数，即使名字没变，Tool Definition 已变；下一请求应重建 Agent，才能让主模型看到新 Schema。这就是把 Schema 放入指纹的原因。

---

## 15.4 search_knowledge：把完整 RAG 收成一条窄接口

`KnowledgeSearchTool` 对主 Agent 暴露的协议非常小：

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "用于检索知识库的完整独立问题"
    }
  },
  "required": ["query"],
  "additionalProperties": false
}
```

模型只有一个决定：把需要知识库回答的问题整理成完整的 `query`。知识库 ID、topK、通道、Prompt、模型候选都没有开放给模型，仍由 RAG 服务端配置控制。

### 15.4.1 实际调用链

```text
ReAct 模型产生 search_knowledge(query)
        ↓
AgentScope ToolValidator 校验 Schema
        ↓
KnowledgeSearchTool.callAsync
        ↓ boundedElastic
读取 RuntimeContext 的 sessionId / userId
        ↓
AgentConversationService.loadRecentTurns(..., 2)
        ↓
KnowledgeSearchFacade.search(query, recentTurns)
        ↓
问题改写 → KB-only 意图 → 歧义 → scope → 多通道检索 → 后处理
        ↓
KB_ANSWER 同步生成一段成品答案
        ↓
ToolResultBlock(SUCCESS)
        ↓
下一轮主模型决定直接采用、组合其他工具或继续行动
```

“窄接口”不等于内部能力简单。它只是把第 8～13 章的复杂性藏在一个稳定契约之后，让主 Agent 不必自己编排向量、关键词和图检索。

### 15.4.2 为什么还读最近两轮 Agent 对话

主模型理论上可以把“它呢？”改成完整问题，但工具层仍取最近两轮 user/assistant 业务消息，为 RAG 的 query rewrite 兜底。若 RuntimeContext 没有身份，则退化为空历史改写，而不是猜一个会话。

这里要区分三份上下文：

| 上下文 | 用途 |
|---|---|
| AgentScope 当前 ReAct context | 主模型推理、工具选择和多步行动 |
| 最近两轮 Agent 展示消息 | 仅帮助知识查询改写、消解指代 |
| KnowledgeSearchFacade 的生成上下文 | 检索结果和当前 query；不带完整 Agent 对话做 RAG 合成 |

因此不能说“Agent 全历史被再发送了一遍给知识库生成模型”。源码只把近期轮次用在改写，知识合成保持窄边界。

### 15.4.3 为什么不返回 sources 和 citation

Agent 工具返回的是一段知识答案，而不是 `/rag/v3` 的 sources 面板和 citation 协议。这样主 Agent 可以把知识结果与 MCP 数据继续组合，但代价是外层无法复用 Workflow 的逐来源展示。

这是能力边界，不是“底层没有召回 chunk”。底层照常检索，窄接口只选择不把来源结构向 Agent 暴露。

### 15.4.4 工具错误怎样处理

空 query 会形成 ERROR `ToolResultBlock`；检索异常也会转成文本 `知识库检索异常: ...` 的 ERROR block，而不是向 Reactor 上游继续抛异常。

错误结果会进入下一轮模型上下文。Persona 要求不要向用户暴露工具内部细节，但这属于模型侧约束；从工程边界看，工具错误字符串已经交给下一轮模型，因此错误文案仍应避免秘密或过多内部信息。

---

## 15.5 flush_memory：模型只有触发权，没有事实写入权

`MemoryFlushTool` 只有在长期记忆开启且描述存在时才进入 Toolkit。它的 Schema 是一个不允许额外字段的空对象：

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

这意味着模型只能表达“现在整理记忆”，不能提交：

```text
userId
conversationId
要保存的事实
要删除的事实
```

真正身份来自服务端 `RuntimeContext`，候选内容来自当前对话，写入、合并、删除和容量仲裁交给 `AgentMemoryPipeline`。这是一条重要的信任边界：模型负责建议触发，服务端负责决定长期状态。

### 15.5.1 结果不是简单的 boolean

工具把记忆管道的结局映射为给下一轮模型看的状态：

| Pipeline 结局 | ToolResult | 含义 |
|---|---|---|
| `WRITTEN` | SUCCESS | 记忆集已更新 |
| `SETTLED_EMPTY` | SUCCESS | 已处理，但没有新增长期事实；也可能合并了旧记忆 |
| `NOTHING_PENDING` | SUCCESS | 没有未整理的新轮次 |
| `BUSY` / `CAPACITY_REJECTED` / `DISABLED` / `CONFLICT` / `FAILED` | ERROR | 本次没有按预期写入 |
| `BELOW_THRESHOLD` | 抛异常后转 ERROR | 它只属于后台批处理，出现在主动 flush 说明分支错误 |

若记忆集发生变化，工具会刷新 RuntimeContext 中的用户记忆快照，使本轮后续推理能看到新视图。刷新失败不反转数据库成功，因为“持久化事实”和“本轮缓存投影”是两件事。

本章只讲工具契约；长期记忆怎样抽取、并发仲裁、推进水位和压缩，将在第 16 章完整展开。

---

## 15.6 MCP 在这里承担什么角色

MCP 把外部能力描述为标准 Tool，并通过标准调用请求执行。AsterRAG 当前链路是：

```text
独立 mcp-server（默认 :9099/mcp）
        │
        ├─ initialize
        ├─ tools/list
        └─ tools/call
             ↑
bootstrap 进程中的 McpSyncClient
        ↓
McpClientToolExecutor
        ↓
McpToolRegistry
        ├─ Workflow：RetrievalEngine 直接使用
        └─ Agent：McpToolBridge 适配成 AgentTool
```

这里的复用点不是“Agent 和 Workflow 共用一段提示词”，而是二者共用同一份 Tool Definition 和 executor。

### 15.6.1 为什么没有直接用 AgentScope 自带 MCP 客户端

`McpToolBridge` 的源码注释明确说明：项目根依赖压制了 AgentScope 自带的 MCP SDK 版本，因此 Agent 不再建立第二套 MCP 连接，而是复用 rag 模块已经连接好的 `McpToolExecutor`。

这种做法带来两个直接结果：

- 工具发现、连接和异常标准化只维护一套；
- 需要写一层 Schema/结果适配，把 MCP `Tool` 和 `CallToolResult` 转成 AgentScope 的接口。

### 15.6.2 启动时怎样发现远端工具

`McpClientAutoConfiguration` 读取 `rag.mcp.servers`。当前默认 server URL 是 `http://localhost:9099`，代码会补成 `/mcp`，然后：

1. 构建同步 Streamable HTTP client；
2. `initialize()`；
3. `listTools()`；
4. 为每个 Tool 建 `McpClientToolExecutor` 并注册；
5. 进程销毁时逐个关闭 client。

一个 server 连接失败只会跳过该 server，不阻止其他 server 继续注册，也不会让整个 Spring 应用必然启动失败。

### 15.6.3 Registry 是执行器的进程内索引

`DefaultMcpToolRegistry` 启动时先注册 Spring 容器中的本地 executor Bean，随后远端发现的 executor 也可动态放入。key 是 tool ID；重复 ID 会由后注册者覆盖并告警。

因此 Registry 回答的是“当前 JVM 里，某 tool ID 应该交给哪个 executor”，不是一份永久配置，也不是 MCP Server 的数据存储。

---

## 15.7 McpToolBridge 怎样完成协议适配

桥接层看起来薄，但至少做了四次翻译。

### 15.7.1 名字和描述

- 名字始终取远端 Tool Definition 的 name，也就是 executor 的 tool ID；
- 描述优先使用意图树节点描述；为空才回落 MCP Server 原始 description。

原因是服务端描述通常解释“这个 API 做什么”，意图树描述还可以解释“在当前 Agent 的业务语境里什么时候选它”。

### 15.7.2 输入 Schema

桥接层把 MCP `JsonSchema` 转成 Map：

```text
type       → 空时回落 object
properties → 空时回落 {}
required   → 非空时才写入
```

当前桥没有复制 `additionalProperties` 等其他顶层字段。因此应准确表述为“保留当前代码显式映射的 Schema 核心字段”，不能泛化为“无损透传完整 JSON Schema”。

### 15.7.3 只读提示

只有远端 Tool Definition 的 `annotations.readOnlyHint` 明确为 true，bridge 才报告只读。未声明时不按工具名字猜测。

这很保守：把一个查询工具错判成写工具，最多失去部分自动放行机会；把写工具误判成只读，则可能放过重复副作用。不过当前随仓库提供的示例 MCP 工具没有设置 annotations，所以即使名字都是 query，bridge 也会返回 false。

### 15.7.4 输出和错误

bridge 调 executor 后：

- 只提取 MCP `TextContent`；
- 多段文本用换行连接；
- null 或 content 为空，返回“（工具无返回内容）”；
- `CallToolResult.isError=true` 映射为 ERROR；
- bridge 自身捕获到异常时，返回“工具调用异常: ...”的 ERROR。

非文本 content 当前不会被转换成图片、结构化资源或二进制 block。如果结果中只有非文本内容，过滤后的字符串会是空串；这就是当前适配层的能力上限。

---

## 15.8 Agent 路径的参数校验：主模型产参，框架验参

在 Agent 路径中，主模型已经获得工具描述和 Schema。它直接生成 `ToolUseBlock`，其中包含 tool name 与 JSON 参数。

AgentScope 2.0.2 的 `ToolExecutor.executeCore` 在真正调用工具前依次做：

```text
按 name 查工具
    ↓ 找不到
ToolResultBlock.error("Tool not found")

找到工具
    ↓
ToolValidator.validateInput(toolCall.content, tool.getParameters)
    ↓ 失败
ToolResultBlock.error("Parameter validation failed ... Please correct ...")

校验通过
    ↓
合并 RuntimeContext / preset parameters
    ↓
tool.callAsync
```

校验器使用 JSON Schema Draft 2020-12，源码明确支持 required、类型、enum、数值范围、字符串长度与 pattern、嵌套 object/array 等约束。

### 15.8.1 可选 null 的特殊规则

在校验前，框架会递归删除“Schema 已声明、不是 required、值为 null”的字段，把它当成未传；required 字段为 null 时则删除后自然触发 required 校验。

因此：

```text
可选字段缺失       ≈ 可选字段显式 null
必填字段缺失       ≈ 必填字段显式 null → 校验失败
```

### 15.8.2 校验失败不等于整条 Agent 立即报错

`ToolExecutor` 把校验错误包装成 ERROR `ToolResultBlock`。ReAct 下一轮模型能看到“哪个工具、哪个参数不合法”，然后可以：

- 修正参数再调用；
- 向用户追问；
- 放弃该工具并解释无法完成。

但源码没有为 Agent 路径定义一个单独的 `NEED_CLARIFICATION` 状态。模型是否先追问，来自 Persona、Schema 和下一轮推理，不是一个 Java 三态分支的强制结果。

### 15.8.3 校验发生在 preset 参数合并之前

AgentScope 先校验模型产生的 tool content，再合并注册时 preset 参数，而且 preset 值优先。AsterRAG 当前这三个工具没有使用 preset 注入，但理解顺序有助于区分“模型可见参数”和“框架控制参数”。

---

## 15.9 Workflow 路径的参数提取：独立 LLM + 三态分流

Workflow 没有 ReAct 主模型直接产生原生 ToolUseBlock。意图阶段选到 MCP 节点后，`RetrievalEngine` 调 `LLMMcpParameterExtractor`，用当前问题、Tool Definition 和可选自定义参数 Prompt 再请求一次 LLM。

```text
用户问题 + MCP Tool Schema
        ↓
LLMMcpParameterExtractor
 temperature=0.1 / topP=0.3 / thinking=false
        ↓
解析 JSON、按字段类型和 enum 校验
        ↓
┌────────────────────┬────────────────────────┬────────────────────┐
│ SUCCESS            │ NEED_CLARIFICATION     │ FAILED             │
│ 参数有效           │ 必填无默认值且用户未给 │ 协议畸形或值非法   │
│ 填默认值后调远端   │ 不调远端               │ 不调远端           │
└────────────────────┴────────────────────────┴────────────────────┘
```

消费端的处理也不同：

- `SUCCESS`：真正调用 executor；
- `NEED_CLARIFICATION`：构造 `isError=false` 的提示上下文，要求最终 LLM 向用户问缺失参数；
- `FAILED`：构造 `isError=true` 的“已跳过调用”上下文。

### 15.9.1 两套参数机制对比

| 维度 | Workflow MCP | Agent MCP |
|---|---|---|
| 谁先产参数 | 独立参数提取 LLM | ReAct 主模型 |
| 选择工具与产参 | 意图树先选，提参后做 | 主模型一次产生 ToolUse |
| 校验位置 | AsterRAG `LLMMcpParameterExtractor` | AgentScope `ToolValidator` |
| 缺必填参数 | Java 明确产出 NEED_CLARIFICATION | ERROR ToolResult，下一轮模型自行处理 |
| 值非法 | FAILED，不调用 | ERROR ToolResult，不调用 |
| 默认值 | SUCCESS 后由 extractor 填充 | Schema 主要约束模型；bridge 不额外 fill defaults，远端实现可自行默认 |
| 调用结果去向 | 格式化进 RetrievalContext，再由固定生成阶段回答 | ToolResult 直接进下一轮 ReAct |

面试时最容易答错的是：“MCP 参数都是由参数提取器产生。”这只对 Workflow 路径成立；Agent 路径绕过了 `LLMMcpParameterExtractor`。

---

## 15.10 错误是怎样逐层标准化的

以 Agent 调远端 MCP 为例：

```text
1. tool ID 不在 Toolkit
   → AgentScope: Tool not found ERROR

2. 参数不符合 Schema
   → AgentScope: Parameter validation failed ERROR
   → 不进入 McpToolBridge

3. 远端 SDK 调用抛异常
   → McpClientToolExecutor 捕获
   → CallToolResult(isError=true, "远程调用失败: ...")

4. 远端正常返回业务错误
   → CallToolResult.isError=true

5. McpToolBridge 适配
   → ToolResultBlock.ERROR

6. ReAct 下一轮
   → 模型根据错误决定重试、换工具、追问或说明失败
```

注意第三层：`McpClientToolExecutor` 已把多数远端异常转成普通错误结果，所以 bridge 的 catch 更像第二道保险，而不是远端失败的唯一处理点。

### 15.10.1 “ERROR”是给运行时和模型的信号，不是最终用户文案

ToolResult 中可能带 SDK 原因或异常消息。最终回复应由主模型按 Persona 转成用户可理解、不过度暴露内部实现的说法。工具错误字符串本身不能被当成已经完成脱敏的用户提示。

### 15.10.2 日志边界

`McpClientToolExecutor` 当前在成功和失败日志中记录 params。它有利于排查“模型究竟传了什么”，但如果未来工具参数包含手机号、客户 ID 或其他敏感字段，就要增加结构化脱敏，而不能因为日志不展示 API Key 就认为所有参数都安全。

---

## 15.11 仓库里的 mcp-server 是协议示例，不是生产业务系统

独立 `mcp-server` 模块当前最多暴露六个工具：

| Tool ID | 示例能力 | 数据边界 |
|---|---|---|
| `weather_query` | 城市天气与预报 | 在进程内按规则生成示例天气 |
| `ticket_query` | 技术支持工单查询 | 生成/缓存演示工单数据 |
| `leave_query` | 假期余额与明细 | 生成/缓存演示员工数据 |
| `asset_query` | IT 资产汇总与明细 | 生成/缓存演示资产数据 |
| `sales_query` | 销售汇总、排名、明细、趋势 | 生成/缓存演示销售数据 |
| `youcom_search` | You.com 联网搜索 | 只有配置 `YDC_API_KEY` 才注册，并真实调用外部 Search API |

前五个类中可以直接看到 `Random`、`getOrGenerate...`、示例人名和公司名。因此教程只能把它们讲成 MCP Schema、调用和结果适配的可读示例，不能宣称项目已经接入真实 HR、CRM、工单或资产系统。

`youcom_search` 的边界不同：它是可选真实外部 HTTP 调用，没 Key 时 Bean 不注册。这样远端 `tools/list` 不会暴露一个注定不可用的搜索工具。

### 15.11.1 示例工具没有 readOnly annotations

这些工具名字和实现大多是查询，但构造 `Tool` 时没有设置 `ToolAnnotations.readOnlyHint`。所以 Agent 适配后会保守报告非只读。面试时可以说“协议支持透传只读提示”，不能说“示例查询工具都已经标成 read-only”。

---

## 15.12 用两个请求串起整章

### 请求 A：问项目文档中的内部规则

```text
用户：这个系统怎样避免同一用户并发运行两个 Agent？
  ↓
主模型根据 description 选择 search_knowledge
  ↓
参数：{"query":"AsterRAG 如何避免同一用户并发运行两个 Agent？"}
  ↓
Schema 校验通过
  ↓
KnowledgeSearchFacade 完成 KB-only 检索和合成
  ↓
知识答案作为 ToolResult
  ↓
主模型直接组织最终回答
```

这里没有 MCP 参数提取器，也没有远端 mcp-server。

### 请求 B：问某城市天气

假设 `weather_query` 同时满足“意图树已配置”和“executor 已注册”：

```text
用户：杭州明天天气怎么样？
  ↓
主模型选择 weather_query
  ↓
参数：{"city":"杭州","queryType":"forecast","days":2}
  ↓
AgentScope 按 MCP Schema 校验
  ↓
McpToolBridge → McpClientToolExecutor → /mcp tools/call
  ↓
TextContent → ToolResultBlock
  ↓
主模型组织最终回答
```

但仓库中的天气结果是生成的演示数据，所以这个例子只用于解释调用链，不代表可作为真实天气服务使用。

---

## 15.13 当前设计的取舍

### 15.13.1 用目录快照换一致性

每次解析再按指纹懒重建，比全局可变 Toolkit 多了一层对象，但保证 Schema、执行器和展示名属于同一版。

### 15.13.2 用双重门控换可控工具面

远端发现不自动等于 Agent 授权。缺点是接入新工具需要同时准备 MCP 服务与意图配置；优点是不会把所有基础设施能力无条件暴露给模型。

### 15.13.3 用窄知识工具换复用

Agent 无需重写 RAG，但失去了 Workflow 的 sources/citation 投影。它选择复用知识答案能力，而不是复用完整前端协议。

### 15.13.4 用服务端身份换安全边界

记忆工具不接受 userId、conversationId 和记忆正文，避免模型伪造 owner。代价是工具必须依赖 RuntimeContext，脱离 Agent 运行时无法独立调用。

### 15.13.5 用文本适配换简单性

MCP 结果只取 TextContent，能覆盖当前示例，但没有完整支持多模态或结构化内容。若未来接图片、资源链接或结构化输出，bridge 必须扩展，而不能只改 MCP Server。

---

## 15.14 常见误解校正

### 误解一：MCP Server 发现的所有工具都会交给 Agent

不会。还必须存在启用的意图树 MCP 节点；Agent 使用两者交集。

### 误解二：Agent 调 MCP 前也会先走 LLMMcpParameterExtractor

不会。Agent 主模型直接产生 ToolUse 参数，AgentScope 校验；独立提参器属于 Workflow。

### 误解三：缺参数时 Agent 一定进入 NEED_CLARIFICATION

Agent 路径没有这个 Java 状态。Schema 校验失败形成 ERROR ToolResult，下一轮模型决定是否追问。NEED_CLARIFICATION 是 Workflow 的 `McpExtractionResult`。

### 误解四：flush_memory 让模型决定要记住什么

模型只能触发。身份、候选对话、抽取、合并和容量控制都在服务端。

### 误解五：MCP Schema 被无损复制给 AgentScope

当前 bridge 显式复制 type、properties 和非空 required；没有完整复制所有顶层约束。

### 误解六：readOnly=true 表示工具一定安全且免费

它只表示无可观察写副作用的声明。查询仍可能失败、泄露输入、消耗配额；当前 AsterRAG 也没有围绕这些 legacy AgentTool 配一套用户审批交互。

### 误解七：示例工单、请假和销售结果来自真实企业系统

不是。源码生成演示数据；只有可选 You.com 工具在配置 Key 后调用真实外部 API。

---

## 15.15 面试追问与回答骨架

### 问：主 Agent 的工具列表从哪里来？

固定知识工具、可选记忆工具，以及“意图树配置 ∩ 当前 MCP executor 注册表”的交集。解析结果冻结成 ResolvedCatalog，用同一快照构建 fingerprint、Toolkit 和展示名。

### 问：为什么 MCP 工具需要意图树和注册表双重存在？

意图树负责产品层暴露和路由语义，注册表负责运行时可调用性。只发现不配置就隐藏，只配置没连上就告警但不注册。

### 问：KnowledgeSearchTool 是不是直接调用 `/rag/v3/chat`？

不是。它调用 KnowledgeSearchFacade 的窄服务接口，复用改写、KB-only 意图、检索、后处理和 KB 合成，不复用 RAG Controller、SSE、sources 或 citation。

### 问：为什么记忆工具设计成无参？

防止模型获得身份和事实写入权。模型只决定何时触发，服务端从 RuntimeContext 与持久化对话决定处理谁、处理什么、怎样合并。

### 问：Agent 与 Workflow 的 MCP 参数链有什么区别？

Workflow 先按意图树选工具，再用独立 LLM 提参，并强制分 SUCCESS、NEED_CLARIFICATION、FAILED；Agent 由 ReAct 主模型按 Schema 直接产参，AgentScope 校验失败后把 ERROR ToolResult 交给下一轮模型。

### 问：远端 MCP 调用失败会不会直接让 Agent 流异常？

通常不会。McpClientToolExecutor 把远端异常标准化成 `CallToolResult(isError=true)`，bridge 再变成 ERROR ToolResult，下一轮模型决定如何收尾。框架外的严重异常仍可能进入更外层运行错误处理。

### 问：工具配置热更新为什么要重建 Agent？

Agent 构建时持有 Toolkit 深拷贝。描述或 Schema 变化后旧实例不会自动变化，所以目录指纹改变时，在下一请求懒重建。

### 问：MCP bridge 当前最大的能力边界是什么？

Schema 只映射核心字段，结果只提取 TextContent；完整 JSON Schema 顶层约束和非文本内容没有无损透传。

---

## 15.16 源码定位卡

### AsterRAG 工具目录与 Agent 适配

- `agent/src/main/java/com/nageoffer/ai/ragent/agent/tool/AgentToolCatalog.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/tool/KnowledgeSearchTool.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/tool/MemoryFlushTool.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/tool/McpToolBridge.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/config/ReActAgentProvider.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/service/AgentConversationService.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/KnowledgeSearchFacade.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/intent/IntentNodeRegistry.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/prompt/AgentPromptResolver.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/prompt/AgentPromptSlot.java`

### MCP 客户端、注册表与 Workflow 提参

- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/mcp/McpClientProperties.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/mcp/McpClientAutoConfiguration.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/mcp/McpToolExecutor.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/mcp/McpClientToolExecutor.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/mcp/McpToolRegistry.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/mcp/DefaultMcpToolRegistry.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/mcp/McpParameterExtractor.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/mcp/LLMMcpParameterExtractor.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/mcp/McpExtractionResult.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/RetrievalEngine.java`
- `bootstrap/src/main/resources/application.yaml`

### 示例 MCP Server

- `mcp-server/src/main/java/com/nageoffer/ai/ragent/mcp/config/McpServerConfig.java`
- `mcp-server/src/main/java/com/nageoffer/ai/ragent/mcp/executor/WeatherMcpExecutor.java`
- `mcp-server/src/main/java/com/nageoffer/ai/ragent/mcp/executor/TicketMcpExecutor.java`
- `mcp-server/src/main/java/com/nageoffer/ai/ragent/mcp/executor/LeaveMcpExecutor.java`
- `mcp-server/src/main/java/com/nageoffer/ai/ragent/mcp/executor/AssetMcpExecutor.java`
- `mcp-server/src/main/java/com/nageoffer/ai/ragent/mcp/executor/SalesMcpExecutor.java`
- `mcp-server/src/main/java/com/nageoffer/ai/ragent/mcp/executor/YouComSearchMcpExecutor.java`
- `mcp-server/src/main/resources/application.yml`

### 锁定的 AgentScope 2.0.2 源码

- `io/agentscope/core/tool/AgentTool.java`
- `io/agentscope/core/tool/Toolkit.java`
- `io/agentscope/core/tool/ToolExecutor.java`
- `io/agentscope/core/tool/ToolValidator.java`
- 来源与校验和见 `evidence/agentscope-2.0.2-source-note.md`。

---

## 15.17 读完本章，你应该能自己回答

1. ResolvedCatalog 为什么必须同时派生 fingerprint、Toolkit 和 displayNames？
2. Agent 能看见的 MCP 工具为什么是意图树和注册表的交集？
3. `search_knowledge` 的一个 query 背后复用了哪些 RAG 阶段？
4. 为什么知识工具只取近期对话做改写，而不把完整历史送进 KB 合成？
5. `flush_memory` 为什么没有 userId 和 memoryContent 参数？
6. McpToolBridge 怎样映射 name、description、Schema、readOnly 和 result？
7. AgentScope 在什么时点做参数校验，失败后谁决定下一步？
8. Workflow 的 NEED_CLARIFICATION 为什么不能套用到 Agent 路径？
9. 远端 MCP 异常经过哪几层才变成下一轮模型看到的 ERROR？
10. 为什么不能把仓库中的天气、工单、请假和销售工具讲成真实生产集成？

下一章将从“Agent 会调用什么”转向“Agent 记住什么”：AgentScope State、展示消息、RuntimeContext、上下文压缩和跨会话长期记忆分别归谁所有，何时加载、何时刷新、何时持久化，又如何避免并发写坏记忆水位。
