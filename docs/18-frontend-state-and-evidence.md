# 第 18 章：控制台不是截图——前端状态、证据展示与管理闭环

> 后端已经定义了会话、消息、任务、SSE 事件、来源、Agent 轨迹和管理数据，但用户最终看到的不是这些 Java 对象，而是 React 页面。理解前端的关键不是记住按钮放在哪里，而是回答三个问题：页面此刻显示的内容来自哪里，哪些内容已经成为服务端事实，刷新或切换会话后哪些内容还能重建。
>
> 本章因此不做颜色、间距和响应式样式巡礼，也不把一张页面截图当成“功能证明”。我们沿着 `router → EngineGate → hook → Zustand store → component → API` 追踪两套聊天投影，再把管理页放回后端 API。最终要建立的心智模型是：**前端是服务端业务状态与当前连接事件的投影层，不是新的持久真相源。**

## 18.1 先把前端放回总体架构图

AsterRAG 前端是一个 React 18 + TypeScript + Vite 单页应用，状态主要由 Zustand store 管理，普通管理请求通过 Axios，聊天流则直接使用 `fetch` 读取 SSE。

```text
                                   ┌─ 普通 API ── Axios ── 管理数据/会话历史
浏览器路由 ── EngineGate ── 页面 ──┤
                                   └─ 流式 API ── fetch ── 手写 SSE 解析器
                                                              │
                                                  事件投影到 Zustand store
                                                              │
                                  ┌───────────────────────────┴──────────────┐
                                  │                                          │
                         当前连接的临时显示                          服务端返回的持久事实
                     temp id / streaming / hint                 message id / status / blocks
                     raw frame / live duration                  sources / history / title
                                  │                                          │
                                  └──────────── React 组件渲染 ──────────────┘
```

这张图里最容易混淆的是“浏览器看见了”和“服务端保存了”。例如：

- 一个回答 token 已出现在页面上，只能证明当前连接收到了该 `message` 事件；
- `finish.messageId` 到达并替换临时 ID，才说明前端拿到了持久助手消息的标识；
- 停止时页面追加“（已停止生成）”，这个后缀是客户端提示，不是数据库正文；
- Agent 原始帧抽屉保存的是本次浏览器连接最近 2000 帧，不是 RAG Trace，也不是 Agent State；
- 刷新后重新出现的内容，必须能够从会话/消息 API 重新取得，不能依赖内存中的 Zustand 对象。

因此本章会反复使用三层术语：

| 层次 | owner | 典型内容 | 刷新后 |
|---|---|---|---|
| 浏览器交互态 | Zustand / React component | 输入框、展开面板、临时 ID、live timer | 通常丢失 |
| 当前连接事件态 | SSE hook + store | 增量 token、hint、raw frame、正在运行的工具 | 连接结束或刷新后不天然存在 |
| 服务端业务事实 | PostgreSQL/API，Agent State 另有其 owner | 持久消息 ID、正文、状态、sources、blocks、会话标题 | 可由 API 重建 |

---

## 18.2 页面入口不是写死的：`EngineGate` 先问后端当前使用哪套引擎

聊天路由没有直接绑定某一个聊天页。`router.tsx` 中 `/chat` 和 `/chat/:sessionId` 先经过 `RequireAuth`，再交给 `EngineGate`：

```text
/chat 或 /chat/:sessionId
        │
        ├─ RequireAuth
        │
        └─ EngineGate.initialize()
                │
                └─ GET /rag/settings
                        │
                        ├─ engine.type == "agent" → AgentChatPage
                        └─ 其他值                  → ChatPage
```

`engineStore` 只在本次 SPA 状态中初始化一次。它读取 `/rag/settings` 的 `settings.engine.type`，只有精确等于 `agent` 才进入 Agent 页面；其他值统一解释为 workflow。若设置请求失败，它记录 warning 并回退到 workflow，而不是让整个聊天入口永久空白。

后端 `RAGSettingsController` 的 engine 字段来自 `OrchestrationProperties.getMode()`。冻结源码的当前 YAML 把 `ragent.engine.type` 配成 `agent`，因此默认入口是 Agent 页面；但前端仍保留确定性 Workflow 页，并不是两套代码同时驱动同一个回答。

这个设计解决的是“部署时选择哪套产品入口”，不是“每一轮让用户临时选择 Agent 或 Workflow”。面试时可以这样概括：

> 后端配置是引擎选择的权威，前端启动后查询只读设置，通过 EngineGate 装配对应聊天页。默认配置选择 Agent；确定性 RAG 页面仍是另一套完整实现，而不是 Agent 页里的一个开关。

### 18.2.1 Agent 页右上角的“在线”说明了什么

`AgentLayout` 会调用 `/agent/v1/meta`，显示框架、模型、最大迭代数、能力列表、工具提供方和 MCP 是否配置。请求成功可说明：

- Agent meta 接口可达；
- 当前进程能返回自己的装配身份；
- 页面拿到了本次显示所需元数据。

它不能单独证明一次 Agent 运行能够完成，也不能证明所有工具、模型和外部 MCP 此刻都可用。这个探针是“身份/配置投影”，不是完整业务健康检查。

---

## 18.3 路由守卫负责用户体验，不能冒充后端授权

`main.tsx` 在渲染应用前触发 `authStore.checkAuth()`。store 的初始登录判断来自 localStorage 中是否存在 token，随后 `/user/me` 再刷新当前用户资料。Axios 请求拦截器把 token 放进请求头；遇到 HTTP 401，或统一业务响应的 message 表明“未登录”，会清理本地认证信息并跳回登录页。

路由层有两种守卫：

| 守卫 | 判断 | 页面行为 |
|---|---|---|
| `RequireAuth` | store 是否认证 | 未认证跳转 `/login` |
| `RequireAdmin` | 已认证且 `user.role === "admin"` | 普通用户跳回 `/chat` |

`/admin` 整棵路由树都放在 `RequireAdmin` 下，聊天侧边栏也只给 admin 角色显示管理后台入口。这些行为可以阻止普通用户通过正常 UI 进入管理页面，却不是 API 的最终安全边界。

第 17 章已经从后端源码确认：当前显式 `StpUtil.checkRole("admin")` 只在用户管理四个操作中出现，permission list 为空。于是必须把结论分成两句：

1. 前端按用户角色隐藏入口并守卫 `/admin` 路由；
2. 后端是否允许某个管理 API，仍要逐个看拦截器、显式 role check 和资源归属条件。

不能从第一句推出第二句。URL 以 `/admin` 开头、菜单只对管理员可见，都不会自动生成后端授权。

### 18.3.1 登录切换还暴露了两套 store 的独立性

`authStore.login/logout` 会调用 Workflow 的 `useChatStore.cancelGeneration()` 和 `reset()`。冻结源码中没有对 `useAgentChatStore` 做同样的显式 reset。路由跳转、页面重新装载和重新拉取会话通常会重建所见内容，但从源码责任上说，两套聊天 store 是独立的，不能假定清理一个就等于清理另一个。

这是阅读大型前端时很实用的检查法：**不要只看页面长得相似，要找每套状态的真正 owner 和清理入口。**

---

## 18.4 两套聊天前端共享模式，但不是同一个状态机

Workflow 和 Agent 都遵循“先乐观创建一轮，再用 SSE 修正”的大模式：

```text
用户按发送
   │
   ├─ 立即插入临时 user 消息
   ├─ 立即插入 assistant-{timestamp} 空消息，status=streaming
   ├─ 发起 GET 流式请求
   └─ SSE 逐步修正 conversation/task/content/status/messageId
```

它们的责任分工如下：

| 路径 | hook | store | 主要投影 |
|---|---|---|---|
| 确定性 RAG | `useStreamResponse.ts` | `chatStore.ts` | think/response、sources、反馈、推荐追问 |
| ReAct Agent | `useAgentStream.ts` | `agentChatStore.ts` | reasoning/answer/tool/hint block、raw frame、轮次耗时 |

临时消息让用户点击发送后立刻看到自己的问题和等待态，不需要等服务端创建会话。代价是前端必须处理身份升级：

```text
assistant-172...（浏览器临时 ID）
              │ finish.messageId
              ▼
1928...（服务端持久消息 ID）
```

反馈、推荐追问等后续动作只对真实消息 ID 有意义，所以组件会排除 `assistant-` 前缀的临时消息。若 `finish` 到达但 `messageId` 为空，页面可以结束 streaming 显示，却不会把该临时对象误当作可反馈的持久消息。

---

## 18.5 为什么不用原生 `EventSource`：两套 hook 都手写读取 SSE

两套 hook 都用 `fetch`，原因从实现能力可以直接看到：它们需要把 Authorization header 带进 GET，并需要可控的 `AbortController`。原生浏览器 `EventSource` 对自定义 header 不友好。

解析器的基本算法相同：

```text
response.body.getReader()
  ↓ TextDecoder("utf-8")
持续拼入 buffer
  ↓ 按 CRLF/LF 切行
event: xxx       → 更新 eventName
data: yyy        → 追加到 dataLines
: heartbeat      → 忽略注释行
空行             → join 多行 data，JSON.parse，dispatch
```

几个细节值得面试时主动讲：

- TCP chunk 不等于 SSE event，所以必须保留未完整行的 `buffer`；
- 一个事件可以有多行 `data:`，解析器用换行连接；
- data 不是合法 JSON 时保留为字符串；
- 空行才触发 dispatch，流结束前还会补 dispatch 一次；
- `onEvent` 在具体事件分派前执行，Agent 用它记录原始帧。

### 18.5.1 “重试”不是“断点续传”

store 给两套 hook 都传 `retryCount: 1`。失败后，hook 按指数延迟再次执行同一个 GET。源码没有维护 SSE event id，也没有发送 `Last-Event-ID`，所以它的真实语义是：

```text
第一次 GET 中断
   │
   └─ 新建第二次 GET，请求参数与原请求相同
```

它不是从最后一个 token 继续。第二次 GET 可能再次触发生成。

Agent 路径有完整流窗口的 `AgentRunGate`，原任务仍占用 gate 时，新请求通常会被拒绝；但这仍然是“新请求被 gate 拦住”，不是恢复旧流。Workflow 路径没有同构的 per-user 全流程 gate，不能把重试描述成 exactly-once 或 resume。

### 18.5.2 两套 hook 对 `200 + JSON` 的处理并不相同

Agent hook 在 `response.ok` 后还检查 `content-type`。若不是 `text/event-stream`，它把 JSON 业务错误转成 `AgentStreamRejectionError`，并明确不重试。

Workflow hook 只检查 HTTP status，没有检查 content-type。如果提交防重开启并以 `200 + JSON` 返回重复提交错误，解析器可能把 JSON body 当成普通字节读完，却分派不出任何 SSE 事件。当前默认 `ragent.eval.enabled=true` 会绕过提交防重，所以这不是默认配置下的必经表现；它是一个由两段源码对照得到的条件边界。

这也说明“两个 hook 看起来几乎一样”不代表契约完全一样。

---

## 18.6 Workflow SSE：每个事件究竟修改哪一部分页面

后端当前 Workflow 事件集合是 `meta/message/finish/done/cancel/reject`。前端解析器还预留了 `title/error` 分支，但不能因此宣称后端当前一定会发送这两个事件。

| SSE 事件 | 关键 payload | `chatStore` 动作 | 是否代表持久完成 |
|---|---|---|---|
| `meta` | conversationId、taskId | 建立当前会话、写入任务 ID、更新会话列表 | 否 |
| `message(type=think)` | delta | 追加 thinking，开始/延续思考计时 | 否 |
| `message(type=response)` | delta | 追加回答，结束思考态 | 否 |
| `reject` | delta | 把拒绝文本追加到回答区 | 拒绝消息由后端后续终态持久化 |
| `finish` | messageId、title、sources、messageStatus | 替换临时 ID，结束回答，挂来源与业务状态 | 是主要业务完成投影 |
| `cancel` | messageId、title、sources、messageStatus | 标记 cancelled，追加停止提示，清理流控制 | 可能有持久部分消息，也可能无 messageId |
| `done` | 无业务 payload | 清理连接生命周期字段 | 本身不携带业务结果 |

这里最重要的区分是 `finish` 与 `done`：

- `finish` 回答“这轮业务最终保存成了什么”；
- `done` 回答“这条 SSE 流可以收尾了”。

如果只看到 `done` 就说消息已经落库，会丢掉 `messageId/sources/messageStatus` 等真正业务信息。

### 18.6.1 正常回答的完整投影

```text
发送：临时 user + 临时 assistant(streaming)
  ↓ meta
获得 conversationId/taskId，URL/会话列表有归属
  ↓ think*
thinking 累加，浏览器记录思考耗时
  ↓ response*
content 累加，思考面板封口
  ↓ finish
临时 assistant ID → 持久 messageId
status=done，messageStatus=NORMAL，挂 sources/title
  ↓ done
清空 taskId/streamAbort/streamingMessageId
```

`thinkingDuration` 是本次浏览器连接用 `Date.now()` 推导的显示信息，不是后端消息表提供的权威耗时。刷新后从历史消息映射回来时，这个 live 计时不天然可恢复。

### 18.6.2 reject 不是网络 error

RAG 的业务拒绝路径会发：

```text
meta → reject → finish(messageStatus=REJECTED) → done
```

前端把 reject 文本放进正常回答内容区，随后 finish 把持久消息 ID 和 `REJECTED` 状态带回来。刷新后这条拒绝消息仍能从服务端历史恢复。

组件对后续动作有细微差异：推荐追问明确只允许 `messageStatus=NORMAL`；反馈按钮只检查真实消息 ID 与非 streaming，因此当前实现中 REJECTED/INTERRUPTED 的持久消息仍可能显示反馈入口。不要把这两个按钮的出现条件混成一个。

### 18.6.3 cancel 为什么不直接 abort fetch

两套 store 的 `cancelGeneration()` 都没有调用已经保存的 `streamAbort`。它们设置 `cancelRequested=true`，若已知 taskId 就调用后端 stop API，然后继续保持 fetch：

```text
用户点击停止
   ├─ 已有 taskId → POST/调用 stop
   └─ meta 尚未到 → 记 cancelRequested
                         │
                         └─ onMeta 得到 taskId 后补发 stop

fetch 继续等待 ← 后端 finalizer 落库部分内容 ← cancel + done
```

这是一个有意识的状态闭环：立刻 abort 会让页面收不到后端最终的 messageId、INTERRUPTED 状态和持久化结果。`streamAbort` 仍用于真正放弃连接的内部场景，但“用户停止生成”走的是业务取消，不是浏览器断网模拟。

Workflow 收到 `cancel` 后，会给当前内容追加 `（已停止生成）`，把 UI `status` 设为 `cancelled`，把持久业务状态设为 `INTERRUPTED`。后端只有在部分回答非空时才可能持久化助手消息，所以 cancel payload 的 messageId 可以为空。

### 18.6.4 error 是临时显示，不等于服务端有一条 ERROR 消息

网络失败、解析失败或最终重试失败进入 `onError`：临时助手消息变成 `status=error`，页面提示“生成已中断”，并清理流控制。普通后端异常路径不一定持久化助手消息，但用户消息在请求早期已经入库。

所以刷新后可能出现：

```text
本次页面：user + 红色 error assistant
刷新历史：user（仍在）+ 没有对应 assistant
```

这不是前端“丢了一条持久错误消息”，而是临时错误投影本来就没有服务端消息 ID。

---

## 18.7 Workflow 会话切换与迟到事件：页面必须面对并发时间线

`selectSession` 在当前仍 streaming 时先调用 `cancelGeneration()`，再请求目标会话历史。异步返回后还会检查 `currentSessionId`，避免更早发出的慢请求覆盖用户后来选择的会话。这是典型的“请求返回顺序不等于用户操作顺序”防护。

但 Workflow 流增量还有一个更细的边界：`onMessage/onThinking` 最终调用 store 方法，后者按当时全局 `streamingMessageId` 找消息，而不像 Agent 路径那样在每个事件入口都检查捕获的 `assistantId`。如果旧流停止尚未真正关闭、用户又启动新流，旧流迟到 delta 理论上可能命中新的全局 streaming 消息。

可以把这里的两种 guard 区分为：

| guard | 防什么 | 当前覆盖 |
|---|---|---|
| history request 的 sessionId 复核 | 旧历史请求覆盖新会话 | Workflow 已有 |
| SSE handler 的本轮 assistantId 复核 | 旧流事件写入新临时消息 | Agent 更完整；Workflow 部分终态有，delta 路径较弱 |

这是从 store 更新条件得到的竞态边界，不需要把它夸大为“必现 bug”。面试里应描述触发前提与责任窗口，而不是只给标签。

Agent 侧边栏在 streaming 时直接禁止切换到其他会话，Workflow 侧边栏则允许触发“先停止、再加载”。两套 UI 因此用了不同的竞态控制策略。

---

## 18.8 来源不是模型正文里的装饰：`sources` 与 citation 是两条相互校验的线

正常 RAG `finish` payload 带 `sources`。历史消息 API 也能返回 sources。每个 `SourceRef` 至少以 `docId` 定位来源，还可以带 index、docName、sourceType、fileType、url 和 excerpt。

前端存在两种打开路径：

- external source 有 URL：新窗口打开 URL；
- local document：新窗口打开 `/preview/doc/{docId}`，再由受认证的预览接口取文件。

这说明 `docId` 是来源定位符，不是把原文件塞进消息正文。

### 18.8.1 Markdown 角标怎样与 source 对齐

`MarkdownRenderer` 使用 React Markdown、GFM、`rehypeRaw` 和 `rehypeSanitize`。引用识别的规范形式是：

```markdown
[1](#cite-1)
```

渲染器按 `source.index` 找到对应 source，点击角标后打开该消息的来源面板。它还有一个谨慎规则：只有正文至少出现过一个规范 `[N](#cite-N)`，才会把其他裸 `[N]` 也解释为引用。这样可以减少把普通数学编号或列表编号误判成来源角标。

因此来源展示不是简单正则把所有方括号数字变蓝，而是：

```text
模型正文中的 citation index
          │
          ├─ 必须匹配可识别的引用语法
          └─ 必须在 sources 中找到同 index 的来源
                         │
                         └─ 打开 source card / preview
```

### 18.8.2 预览页做的是格式适配，不改变来源事实

`DocumentPreview` 按文件类型选择展示器：PDF 用 canvas，DOCX 转 HTML，Excel/CSV 用表格，图片直接显示，Markdown/文本按文本展示，不支持的格式提供下载回退。

这些是同一 `docId` 的不同浏览器呈现方式。它们不生成新的检索来源，也不改变回答当时引用的 source index。

---

## 18.9 反馈和推荐追问：两个“回答之后”的异步闭环

### 18.9.1 反馈先乐观更新，再请求后端

点赞/点踩时，`chatStore.submitFeedback` 先记住旧值并立刻更新消息 UI，然后调用：

```text
有 like/dislike → POST /conversations/messages/{messageId}/feedback
取消反馈       → DELETE /conversations/messages/{messageId}/feedback
```

请求失败会回滚旧值。这个交互让按钮即时响应，但“按钮已经变色”只代表乐观态；API 成功后才代表后端接收了动作。结合第 17 章，反馈写入又经过 MQ 链路时，HTTP/MQ 发送成功仍不能被扩写成消费者数据库处理已经完成。

### 18.9.2 推荐追问的状态挂在每一条消息上

推荐追问不是一个全局弹窗数据，而是消息字段：

```text
recommendedState: loading | ready | error
recommendedOpen:  true | false
recommended:      string[]
```

只有真实持久 ID、非 streaming、`messageStatus=NORMAL` 的 assistant 消息可以触发。`loading` 和 `ready` 时不会重复请求；`error` 可再次尝试。发送新问题会收起历史消息的推荐面板，让视觉焦点回到最新一轮。

历史 API 若已经返回 `recommendedQuestions`，store 直接映射为 ready，所以刷新后不必把已持久的推荐重新生成一遍。

---

## 18.10 Agent SSE：回答不再只是一段字符串，而是一条 block 时间线

Agent 当前事件集合是 `meta/message/tool/hint/finish/done/cancel`。Agent hook 也预留了 `error` 解析分支，但后端枚举当前没有把业务失败定义为一条 `error` SSE 事件；连接/执行异常主要走 hook 的 error handler。

| 事件 | 页面对象 | 作用 |
|---|---|---|
| `meta` | conversation/task | 绑定会话和停止目标 |
| `message(type=think)` | reasoning block | 累加模型推理片段 |
| `message(type=response)` | answer block | 累加最终回答片段 |
| `tool(start)` | running tool block | 显示准备/开始调用工具 |
| `tool(end)` | tool terminal block | 标记 done/failed 并保存 result |
| `hint` | hint block | 显示本次运行提示，不落库 |
| `finish` | assistant + blocks | 持久 ID、NORMAL、标题、总耗时 |
| `cancel` | assistant + blocks | INTERRUPTED、停止提示、工具中断 |
| `done` | stream lifecycle | 清空运行控制字段 |

Agent store 的核心不是简单的 `thinking` 和 `content` 两个字符串，而是顺序 blocks：

```text
reasoning → tool → reasoning → tool → answer
```

`appendText(kind, delta)` 会把连续同 kind 文本合并进当前 open block；kind 改变或工具/hint 到来时，旧文本块被封口。reasoning 块在实时生成时默认展开，封口后可以折叠。最终页面按用户消息和紧随其后的助手消息组成一个 Turn card。

### 18.10.1 工具 start/end 怎样配对

后端持久 `AgentBlock` 有 `toolCallId`，用于标识供应商侧同源 tool use/result。但当前前端 `AgentToolProgress` 和 `AgentBlock` 类型没有暴露/使用 toolCallId。实时 `tool(end)` 到达后，store 从后向前查找“同名且仍 running”的工具块，即 LIFO 配对。

```text
tool A start #1
tool A start #2
tool A end   → 先闭合 #2
tool A end   → 再闭合 #1
```

对串行 ReAct 常见路径足够直观；若出现并发或嵌套的同名调用，实时 UI 无法靠 name 无歧义识别供应商调用 ID。这是“后端模型比前端事件契约更丰富”的具体例子。

`ok === false` 时工具块标记 failed；ok 缺省则兼容性地视为成功。结果文本保存在 block 中，组件会尽量解析 JSON 做摘要，也允许展开查看完整结果。

### 18.10.2 页面上的工具折叠不是执行合并

`AgentTurn` 为了减少视觉噪音，会把连续同名、同结果、同状态的工具行折叠显示。这个渲染优化不代表后端只执行了一次，也不修改持久 blocks。面试时看到 UI 合并不能倒推出运行时去重。

---

## 18.11 hint、原始帧和计时：三种有用但会消失的前端证据

### 18.11.1 hint 明确不落库

Agent `hint` 会单独生成前端 block，例如迭代接近边界的提示。类型注释与 store 都明确说明它只存在于流式时间线，后端 `blocks` 不包含 hint。刷新会话后提示自然消失。

这不是恢复失败，而是持久化契约本来就没有承诺保存 hint。

### 18.11.2 原始帧抽屉只是当前连接的观测窗口

Agent `onEvent` 会在具体事件处理前把 event name 和解析后 payload 推入 `frames`。最多保留 2000 条，超出时丢弃最旧帧；新建或切换会话时清空。

所以 raw frame 能回答：

- 当前浏览器连接按什么顺序收到了哪些 SSE 事件；
- 某个工具/回答 block 是由哪一帧驱动的；
- UI 映射是否漏掉了一个已收到事件。

它不能回答：

- 另一台浏览器收到过什么；
- 刷新前的完整历史帧；
- 后端每个 RAG node 的耗时；
- 模型上下文中保存的完整 Agent State。

RAG Trace、Agent State、持久 blocks 和 raw frames 是四种不同证据，owner 与寿命都不同。

### 18.11.3 live duration 与 replay duration 的口径不同

实时 Agent 轮次耗时是 `finish/cancel` 到达时用 `Date.now() - startedMs` 计算；工具块还能记 startMs/durationMs。后端持久 block 不保存前端 duration。

历史回放时，store 用 assistant createTime 减去紧邻 user createTime 近似轮次耗时。这个值包含服务端持久化时刻差，和本次浏览器连接的精确起止不是同一测量口径。历史工具行也不会恢复 live duration。

正确表达是“实时计时”和“回放估算”，不能把二者放进同一性能统计表而不说明口径。

---

## 18.12 Agent 的正常、取消、失败与回放

### 18.12.1 正常完成

`finish` 到达时，Agent store：

- 用持久 `messageId` 替换临时 assistant ID；
- 把仍 running 的 blocks 收成 done；
- 记录本次浏览器总耗时；
- 设置 `messageStatus=NORMAL`；
- 更新标题、会话时间和本地轮数徽标。

随后 `done` 清理 streamTaskId、Abort 句柄和 open block 指针。

### 18.12.2 取消

Agent 取消同样保持 fetch 等待后端 `cancel + done`。收到 cancel 后：

- running 工具块变成 interrupted；
- 回答正文或最后一个 answer block 追加 `（已停止生成）`；
- 若还没有 answer block，则新建一个只含停止提示的 answer block；
- UI status 设为 cancelled；
- 持久业务状态设为 INTERRUPTED；
- 有 messageId 就升级临时 ID，无则继续保持临时 ID。

后端会在已有正文、reasoning 或工具轨迹时尝试持久化中断助手消息；若尚无可保存内容，messageId 可以为空。

### 18.12.3 失败

Agent error 会把 running 工具投影成 interrupted，把临时助手状态设为 error，并显示 toast。它同样不自动生成一条持久 ERROR 助手消息。刷新后临时 error 投影会消失。

### 18.12.4 历史回放

加载历史时：

- 有持久 blocks 就按顺序映射为 UI blocks；
- 旧数据没有 blocks 时，用 `thinkingContent` 和 `content` 合成 reasoning/answer；
- 所有服务端消息的 UI status 映射为 done，同时保留 `messageStatus`；
- hint、raw frames、展开状态、live block duration 不会重建。

页面因此可以恢复“业务轨迹”，但不能复刻当时浏览器屏幕的每个瞬时细节。

---

## 18.13 `status` 与 `messageStatus` 是两条正交轴

两套 store 都同时保存一个 UI status 和一个服务端业务 status：

| 字段 | owner | Workflow 取值 | Agent 取值 | 用途 |
|---|---|---|---|---|
| `status` | 浏览器 | streaming/done/cancelled/error | 同左 | 当前组件怎样显示 |
| `messageStatus` | 服务端消息 | NORMAL/INTERRUPTED/REJECTED | NORMAL/INTERRUPTED | 持久业务语义 |

它们不能一一等同。例如历史加载时，一条 INTERRUPTED 消息的 UI status 会被映射成 done，因为它已经不是“当前正在取消的连接”；但其 messageStatus 仍是 INTERRUPTED。

当前 Workflow `MessageItem` 只用 messageStatus 限制推荐追问，没有为回放中的 INTERRUPTED 自动重新追加停止标签。Agent 也把停止后缀作为客户端正文修改。于是：

```text
实时取消页面：正文 + “（已停止生成）”，status=cancelled
刷新历史页面：服务端保存的部分正文，status=done，messageStatus=INTERRUPTED
```

停止后缀会消失，是因为它不是持久正文的一部分。真正稳定的事实是 `messageStatus=INTERRUPTED`。

这正是“前端投影不等于数据库镜像”的最佳例子。

---

## 18.14 刷新恢复矩阵：什么回来，什么不回来

| 内容 | 实时 owner | 服务端是否保存 | 刷新后 |
|---|---|---|---|
| 会话标题、持久消息正文 | 服务端业务表 | 是 | 恢复 |
| RAG sources、推荐追问、反馈结果 | 消息及相关服务 | 是/按接口返回 | 可恢复 |
| RAG thinkingContent | 服务端消息 | 是 | 恢复 |
| Agent reasoning/answer/tool blocks | Agent 消息 blocks | 是 | 恢复 |
| NORMAL/INTERRUPTED/REJECTED | 服务端消息 | 是 | 恢复 |
| `assistant-{timestamp}` 临时 ID | 浏览器 | 否 | 消失 |
| streaming/cancelled/error UI 瞬时态 | 浏览器 | 否 | 重建为历史 done 或消失 |
| “（已停止生成）”客户端后缀 | 浏览器 | 否 | 消失 |
| Agent hint | 当前 SSE/store | 否 | 消失 |
| raw frames | Agent store，最多 2000 | 否 | 消失 |
| 展开/收起面板 | React/store | 否 | 回到默认 |
| live thinking/tool/turn duration | 浏览器计时器 | 否 | 丢失或改用历史近似 |

路由恢复也有边界：访问 `/chat/:sessionId` 时，页面先取会话列表并验证 ID。无效或不属于当前用户的 session 不会仅凭 URL 被接管，而是回到新对话并导航 `/chat`。真正的数据归属仍由后端 userId 条件保证。

---

## 18.15 管理后台不是一页大表：每个页面投影一类后端事实

`AdminLayout` 把管理能力按业务对象分组。下面这张导航图比记住菜单颜色更有价值：

```text
/admin
  ├─ dashboard          → /admin/dashboard/*           业务概览/趋势/性能
  ├─ agents             → /agents、prompts、activate   Agent profile 与提示词
  ├─ knowledge          → /knowledge-base、docs/chunks 知识库固定写路径对象
  ├─ knowledge-graph    → /admin/kg/*                  图谱查询与维护
  ├─ intent-tree/list   → /intent-tree/*               闭集意图结构
  ├─ ingestion          → /ingestion/pipelines/tasks   独立通用入库子系统
  ├─ mappings           → /mappings                    查询词归一化
  ├─ traces             → /rag/traces/runs*            确定性 RAG 执行诊断
  ├─ change-logs        → /biz-change-logs*            管理变更审计
  ├─ users              → /users*                      用户/角色
  ├─ sample-questions   → /sample-questions*           欢迎页示例问题
  └─ settings           → GET /rag/settings            运行配置只读投影
```

### 18.15.1 知识文档页与数据通道页不能混为一条链

知识库、文档和 chunks 页面对应第 4～7 章的固定知识文档主链。`/admin/ingestion` 则调用 `/ingestion/pipelines` 与 `/ingestion/tasks`，对应第 6 章已经区分的通用 IngestionEngine 子系统。

两者都出现“入库/任务”词汇，不代表一个页面只是另一个页面的详情页。前端 API 分组再次印证了两套后端对象的边界。

### 18.15.2 Trace 页展示的是 RAG Trace，不是 Agent raw frames

Trace 列表请求 RAG run 分页数据，页面顶部统计卡由**当前页 rows**计算，UI 也明确提示是当前页口径，不是全库监控总量。详情页再加载一次 run 与 nodes，展示各节点状态、时长、输入输出摘要和异常。

它服务于确定性 RAG 的后端执行诊断。Agent 页的 raw frame drawer 服务于当前浏览器 SSE 投影核对。二者不能互相替代。

### 18.15.3 变更审计页查看的是“谁改了什么”

`BizChangeLogPage` 支持筛选、分页和详情，详情里查看 diff、before、after 与 context。它与 Trace 的提问不同：

- Trace：一次 RAG run 经过哪些 node，哪里慢/失败；
- Change Log：哪个用户对哪个业务对象执行了什么管理变更，前后值是什么。

前端把它们放在不同菜单，正好对应第 17 章的不同后端 owner。

### 18.15.4 系统配置页是只读投影

`settingsService.ts` 只有 `getSystemSettings()`，页面文案也明确写“application.yaml 运行时生效配置的只读视图”。它展示 engine、存储/向量/关键词/图谱后端、RAG 开关与预算、模型候选和上传限制，但没有保存配置的 API。

AI provider 的 apiKey 不是原文返回：`RAGSettingsController.maskApiKey()` 对短 key 返回 `******`，长 key 只保留前 6 位和后 4 位；Web Search 只返回 `apiKeyConfigured` 布尔值。教程或面试演示都不应把页面上掩码值称为可用密钥。

---

## 18.16 欢迎页示例不是运行证据

Agent 欢迎页包含一个硬编码 `DEMO_TURN`，组件还明确标注“示例”。它用于让用户理解 reasoning、tool、answer 等时间线长什么样，并没有调用后端执行那一轮。

欢迎页还会读取后台配置的 sample questions。点击问题只把文本填入 draft，不会自动发送；用户仍需要主动提交。

所以看到欢迎页里有工具结果，不能说“该工具刚刚运行成功”；看到示例问题，也不能说“系统已经检索并回答过这些问题”。这是页面教学素材与真实业务证据的边界。

Workflow 页保留“深度思考”开关并把选择传给后端；Agent 页没有同样的逐轮开关，因为 Agent 自身的 ReAct 流程会产生 reasoning。这是两套引擎交互模型不同，而不是 Agent 忘了实现一个按钮。

---

## 18.17 用四个故障场景检查自己是否真的理解了前端

### 场景一：用户在 `meta` 前立刻点击停止

1. 临时消息已创建，`isStreaming=true`；
2. 尚无 taskId，store 只能写 `cancelRequested=true`；
3. `meta` 到达后 handler 得到 taskId；
4. handler 检查 cancelRequested 并补发 stop；
5. fetch 保持打开，等待后端 cancel/done；
6. 若后端有可持久内容，cancel 可能带 messageId，否则为空。

### 场景二：网络在回答中途断开

1. 页面已经有部分 token，但它们只是当前流投影；
2. hook 会再发一次完整 GET，而不是从最后 token 恢复；
3. Agent 新请求可能被 RunGate 拒绝；Workflow 无同构完整 gate；
4. 最终失败时临时 assistant 变 error；
5. 刷新只恢复服务端真实保存的消息，临时 error 不回来。

### 场景三：Agent 工具执行到一半被取消

1. live tool block 原为 running；
2. cancel handler 把所有未完成工具收成 interrupted；
3. 页面追加停止提示；
4. 后端若保存 blocks，刷新后恢复持久工具轨迹和 INTERRUPTED；
5. live duration、raw frame、hint 和客户端停止后缀不会恢复。

### 场景四：普通用户手工输入 `/admin/traces`

1. `RequireAdmin` 会根据 authStore role 把页面导航回 `/chat`；
2. 这改善 UI 访问路径；
3. 它不能证明对应后端接口有 admin role check；
4. 后端真实授权仍以第 17 章检查到的拦截、角色检查和资源边界为准。

---

## 18.18 面试追问：怎样证明你不是只看过截图

### 问：为什么发送后先出现一条空助手消息？

答：前端做乐观投影，先创建临时 user 和 `assistant-{timestamp}`，让等待态立即可见。收到 finish 后才用服务端 messageId 替换临时 ID。反馈和推荐等动作只允许真实 ID。

### 问：`done` 是否表示回答已保存？

答：不能直接等同。finish/cancel 携带 messageId、messageStatus、sources、title 等业务终态；done 主要清理 SSE 生命周期。需要结合终态事件判断持久结果。

### 问：点击停止为什么不 abort 网络请求？

答：用户停止是业务取消。前端发送 task stop 后保留 fetch，以便接收后端 finalizer 的 cancel/done 和可能的持久 messageId。直接 abort 只能断开浏览器，拿不到完整收尾投影。

### 问：前端 SSE 重试能否避免重复生成？

答：不能把它说成断点续传。源码没有 event id/Last-Event-ID，只会重新 GET。Agent 的完整 RunGate 可在旧任务仍运行时拒绝新任务，但那是并发保护，不是 resume。

### 问：Agent 的工具轨迹怎样恢复？

答：后端把 reasoning/answer/tool blocks 随助手消息保存，历史 API 返回后按顺序重建。hint、raw frames、展开态和 live duration 是当前浏览器态，刷新不恢复；旧消息没有 blocks 时，前端用 thinking/content 兼容合成。

### 问：Trace 页和原始帧抽屉有什么区别？

答：Trace 是服务端确定性 RAG run/node 诊断记录；raw frames 是当前 Agent 浏览器连接收到的最近 2000 个 SSE payload。owner、寿命和问题域都不同。

### 问：`/admin` 有前端守卫，是否意味着管理 API 都只对管理员开放？

答：不能推出。RequireAdmin 是客户端路由体验；后端权限要找真实拦截器或 role check。当前源码显式 admin check 只确认到用户管理四处。

### 问：刷新后为什么停止提示没了？

答：`（已停止生成）` 是 cancel handler 在浏览器临时追加的文案，没有写进持久正文。刷新后恢复的是服务端部分内容和 `messageStatus=INTERRUPTED`，UI 瞬时 status 重新映射为 done。

---

## 18.19 源码定位卡

### 入口、认证与引擎选择

- `frontend/src/main.tsx`
- `frontend/src/router.tsx`
- `frontend/src/stores/authStore.ts`
- `frontend/src/stores/engineStore.ts`
- `frontend/src/components/common/EngineGate.tsx`
- `frontend/src/services/api.ts`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/controller/RAGSettingsController.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/controller/AgentMetaController.java`

### Workflow 流与证据

- `frontend/src/hooks/useStreamResponse.ts`
- `frontend/src/stores/chatStore.ts`
- `frontend/src/types/index.ts`
- `frontend/src/components/chat/MessageItem.tsx`
- `frontend/src/components/chat/MarkdownRenderer.tsx`
- `frontend/src/components/chat/SourceCitation.tsx`
- `frontend/src/components/document/DocumentPreview.tsx`
- `frontend/src/services/chatService.ts`
- `frontend/src/services/sessionService.ts`

### Agent 流与轨迹

- `frontend/src/hooks/useAgentStream.ts`
- `frontend/src/stores/agentChatStore.ts`
- `frontend/src/types/agent.ts`
- `frontend/src/components/agent/AgentTurn.tsx`
- `frontend/src/components/agent/AgentRawLog.tsx`
- `frontend/src/components/agent/AgentWelcomeScreen.tsx`
- `frontend/src/services/agentService.ts`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/dto/AgentBlock.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/controller/vo/AgentMessageVO.java`

### 管理闭环

- `frontend/src/pages/admin/AdminLayout.tsx`
- `frontend/src/pages/admin/settings/SystemSettingsPage.tsx`
- `frontend/src/pages/admin/traces/RagTracePage.tsx`
- `frontend/src/pages/admin/traces/RagTraceDetailPage.tsx`
- `frontend/src/pages/admin/change-logs/BizChangeLogPage.tsx`
- `frontend/src/pages/admin/ingestion/IngestionPage.tsx`
- `frontend/src/services/settingsService.ts`

---

## 18.20 读完本章必须能回答的自检题

1. `EngineGate` 的选择依据是什么？请求失败时为什么会进入 Workflow？
2. `RequireAdmin` 与后端 `checkRole` 为什么不是同一道安全边界？
3. 临时 assistant ID 在哪个事件上升级为持久 messageId？messageId 为空意味着什么？
4. 手写 SSE parser 为什么必须保存 buffer 和多行 data？
5. 为什么当前 retry 是新请求而不是断点续传？
6. Workflow 的 finish、cancel、done、reject 各自改变什么状态？
7. 用户点停止时，为什么要处理“meta 尚未到达”的竞态？
8. RAG source index、docId、citation link 和文档预览之间怎样连接？
9. 反馈的乐观更新和推荐追问的 per-message 状态机有何不同？
10. Agent tool start/end 当前怎样配对？后端 `toolCallId` 为什么没有解决实时 UI 的同名歧义？
11. Agent hint、raw frame、live duration、持久 blocks 各自由谁保存？
12. 为什么历史 INTERRUPTED 消息的 UI status 可以是 done？
13. 哪些停止/失败标记会在刷新后消失？哪些业务事实会回来？
14. 知识文档页与数据通道页为什么不能当成同一条入库链？
15. RAG Trace、BizChangeLog、Agent State 和 raw frames 分别回答什么问题？

如果这些问题能沿“owner → 事件 → store 更新 → 持久边界 → 刷新结果”完整回答，就已经不是在背页面功能，而是在解释前后端状态契约。

下一章不再沿某一次请求，而是沿 Spring 配置和条件装配反向阅读：同一个接口背后为什么会选择某个存储、检索通道、模型或引擎；看到一个实现类时，怎样证明它真的进入了当前默认拓扑。
