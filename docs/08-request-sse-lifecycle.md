# 第 8 章：一次问题从哪里开始——HTTP、并发闸门、任务与 SSE 生命周期

> 写路径已经把资料变成可检索候选。现在从读路径入口重新出发：浏览器发来一句问题后，AsterRAG 并不会立刻调用大模型。它先建立 SSE 通道、分配会话与任务身份、进入分布式排队，再把取消和收尾动作注册起来。
>
> 本章的目标是让你能完整解释“请求被接收”和“回答完成”之间的生命周期，而不是把一个返回 HTTP 200 的长连接误当作已经成功回答。

## 8.1 入口只做三件事

确定性 RAG 的入口是：

```http
GET /rag/v3/chat?question=...&conversationId=...&deepThinking=false
```

`RAGChatController.chat` 的方法体非常短：

1. 用 `rag.default.sse-timeout-ms` 创建 `SseEmitter`；当前 YAML 是 300000 毫秒，即 5 分钟；
2. 调用 `RAGChatService.streamChat(...)`；
3. 把 emitter 交还给 Spring MVC。

这说明 Controller 只负责建立 HTTP/SSE 边界，不拥有检索、模型调用、持久化或取消状态。

请求参数中：

- `question` 经过 `@ChatQuestion` 校验；
- `conversationId` 可空，空时服务层生成雪花 ID；
- `deepThinking` 默认 false，后面进入 `StreamChatContext`，最终影响模型请求，而不改变本章的排队协议。

停止接口是：

```http
POST /rag/v3/stop?taskId=...
```

它最终调用 `StreamTaskManager.cancelByUser(taskId)`。注意停止使用的是本次流的 `taskId`，不是 `conversationId`。

---

## 8.2 四种 ID 不要混在一起

一次问答会同时接触多种身份：

| ID | 表示什么 | 何时产生 | 主要用途 |
|---|---|---|---|
| `userId` | 当前登录用户 | 认证上下文 | 所有权、隔离、并发与持久化归属 |
| `conversationId` | 多轮会话 | 调用方传入或服务新建 | 读取历史、追加消息、显示会话 |
| `taskId` | 这一次流式执行 | 每次 `streamChat` 新建 | SSE META、停止、上游取消、任务收尾 |
| `messageId` | 一条持久消息 | USER/assistant 落库时产生 | 回复关系、完成事件、历史查询 |

同一个会话可以有多条消息，也可以先后产生多个 task；task 是运行身份，message 是持久事实。面试时若用“会话 ID”泛指所有东西，后面会无法解释停止权限和 `replyToMessageId`。

---

## 8.3 回调对象在排队前就建立

`RAGChatServiceImpl.streamChat` 的顺序是：

```text
确定 actualConversationId
    ↓
生成 taskId
    ↓
StreamCallbackFactory.createChatEventHandler
    ↓
ChatQueueLimiter.enqueue
    ↓  取得许可后
StreamChatTraceRunner.run
    ↓
StreamChatPipeline.execute
```

`StreamChatEventHandler` 在构造时立即执行 `initialize()`：

1. 发送 `META`，其中包含 `conversationId` 和 `taskId`；
2. 在 `StreamTaskManager` 注册本地取消收尾回调；
3. 将 task 的属主写到 Redis。

所以前端在真正检索之前就能获得停止所需的 taskId。若等模型开始输出后才注册，用户在排队或改写阶段点击停止就没有稳定目标。

这里也有一个分支差异：正常流的 `META` 在 callback 构造时发送；排队超时/线程池拒绝走 `ChatQueueLimiter.handleReject`，它会自行构造一组拒绝事件。

---

## 8.4 `@IdempotentSubmit` 保护的是同步提交窗口

`chat` 方法带有：

```java
@IdempotentSubmit(
    key = "T(...UserContext).getUserId()",
    message = "当前会话处理中，请稍后再发起新的对话"
)
```

`IdempotentSubmitAspect` 获取一把基于用户 ID 的 Redisson 锁，在 `joinPoint.proceed()` 返回后的 `finally` 中立刻解锁。Controller 在启动异步流程并返回 `SseEmitter` 后，切面就结束了。

因此它防的是两个同步提交同时穿过 Controller 的窄窗口，不是“一位用户直到整条 SSE 结束都不能再提问”。覆盖真正业务执行时长的全局容量控制是下一节的 `ChatQueueLimiter`。

这也是阅读异步代码的通用技巧：**切面包住一个返回异步句柄的方法，不代表它自动包住句柄背后的整个异步生命周期。**

---

## 8.5 全局并发闸门：排队，不是简单限频

默认配置为：

```yaml
rag:
  rate-limit:
    global:
      enabled: true
      max-concurrent: 10
      max-wait-seconds: 15
      lease-seconds: 30
      poll-interval-ms: 200
```

`ChatQueueLimiter` 在开关关闭时直接把任务提交给 `chatEntryExecutor`；开关开启时，把一份 `AcquireRequest` 交给 `FairDistributedRateLimiter`。

这不是“每秒允许多少请求”的令牌桶，而是：

```text
最多同时持有 10 个可过期 permit
其余请求按公平队列等待
等待超过 15 秒进入 reject 流程
```

### 8.5.1 Redis 和 JVM 各保存什么

分布式限流器把协调状态放在 Redis：

- `RPermitExpirableSemaphore`：可过期许可；
- `RScoredSortedSet`：全节点共享排队顺序；
- 递增序列：给请求分配稳定 score；
- entry TTL 标记：让崩溃后遗留的队列项可被识别为僵尸；
- topic：许可释放时通知各节点尽快轮询。

每个进程本地还持有 `Ticket`、轮询 future 和 notifier 注册。Redis 负责跨节点秩序，本地对象负责执行回调和 CAS 状态机；两者不是同一类状态。

### 8.5.2 `Ticket` 只有四种互斥状态

```text
PENDING ──grant────► GRANTED
   ├────timeout───► TIMED_OUT
   └────cancel────► CANCELLED
```

一个 `AtomicReference<State>` 是终态协调点。`grant`、`timeout`、`cancel` 竞争同一个 CAS，因此业务回调最多进入一次。资源清理另做幂等处理：移出 ZSet、删除 entry 标记、注销轮询、按状态释放 permit。

这种“状态互斥”和“资源清理幂等”分离很关键。仅靠 `finally` 不足以处理 grant 与断线同时发生的竞态；仅靠状态机又不会自动删除 Redis 队列痕迹。

### 8.5.3 公平性怎样实现

请求入队时获得递增 score。Lua 脚本原子地判断自己是否位于可抢占的队头窗口并从队列 claim；随后再尝试获取 semaphore permit。若 claim 成功但 permit 已被别的节点抢走，请求按原 score 重入队，而不是到队尾重新排。

源码同时使用固定间隔轮询和 Redis topic 唤醒：轮询提供兜底，通知减少许可释放后的等待。这里没必要背 Lua 每一行，面试中说清“共享有序队列 + 原子 claim + 失败按原位次重入”就能解释公平性的来源。

### 8.5.4 permit 在哪里释放

拿到许可后，业务 Runnable 被包装为：

```java
try {
    onAcquired.run();
} finally {
    releaseHeldPermit();
}
```

也就是说，不论 Trace/Pipeline 正常返回还是同步抛错，业务线程退出时都尝试释放许可。若任务还只是 `PENDING`，SSE 完成、超时或错误会通过 `cancelBinder` 取消排队；已经 `GRANTED` 后，Ticket 的 cancel 不会提前释放许可，因为业务仍可能在用这个并发槽，最终仍由包装 Runnable 的 `finally` 归还。这里的 cancelBinder 管的是**限流 Ticket**，不能自动等同于取消 `StreamTaskManager` 中的上游模型任务。

### 8.5.5 当前 lease 是兜底上限，不是续租型全程锁

源码通过：

```java
sem.tryAcquire(0, leaseSeconds, TimeUnit.SECONDS)
```

取得一枚显式过期的 permit，没有看到对该 permit 的续租。当前 YAML 的 lease 是 30 秒，而 RAG SSE 超时是 300 秒。因此对于超过 30 秒的执行，这枚 Redis permit 可能已经自动过期，业务结束时的 release 也可能提示“可能已过期”。

准确说法是：**该闸门为正常时长任务提供分布式并发控制，并用 lease 防止进程崩溃永久泄漏许可；当前配置并不证明一个 30 秒以上的长流始终占用同一 permit。** 这是由源码和默认值能直接观察到的运行边界，不应扩张成“全程严格最多 10 条流”的承诺。

---

## 8.6 被拒绝也要形成可结束的前端协议

以下情况会进入 `handleReject`：

- 排队超过最大等待时间；
- 关闭限流后的直通线程池拒绝任务；
- 已获许可但提交业务 Runnable 时线程池拒绝，限流器释放许可后降级到 timeout 回调。

拒绝路径并非抛一个普通 HTTP 错误。系统会尽量：

1. 保存本轮 USER 消息；
2. 保存内容为“系统繁忙，请稍后再试”的 assistant 消息，并标为 `REJECTED`；
3. 若是新会话，取生成标题或使用问题前若干字符作为回退标题；
4. 发送终止事件。

事件序列在记录成功时为：

```text
META → REJECT → FINISH(status=REJECTED) → DONE → complete
```

如果拒绝消息落库本身失败，源码会记录警告，但仍发送 `DONE` 并完成 emitter，避免前端一直等待。这体现了“持久化最好成功”和“流协议必须有终点”两个独立目标。

拒绝路径还没有进入 `StreamChatTraceRunner`，因此不能把它说成一条状态为 REJECTED 的正常 RAG Trace；它是 Trace 外层的容量拒绝协议。

---

## 8.7 取得许可后，才进入 Trace 和固定 Pipeline

成功取得许可后，`RAGChatServiceImpl` 构造 `StreamChatContext`：

```text
question
conversationId
taskId
deepThinking
userId
trace-aware callback
```

外层 `StreamChatTraceRunner.run` 先建立本次 Trace Run，再把原 callback 包成 trace-aware callback，最后调用 `StreamChatPipeline.execute`。Pipeline 的固定顺序在后续章节展开。

本章只需记住：并发许可包住的是 `traceRunner.run(...)` 这一整个同步调用。模型的流式实现若在该方法返回前持续阻塞，permit 会随主流程持有；若某个底层实现把真实流完全异步化并提前返回，则 permit 的实际覆盖时长也会随之改变。判断并发边界必须看调用是否阻塞，不能只看方法名里有 `stream`。

---

## 8.8 正常流的 SSE 事件不是一条字符串

`StreamChatEventHandler` 把模型 callback 翻译成命名 SSE 事件：

| 事件 | 载荷/含义 |
|---|---|
| `meta` | `conversationId`、`taskId` |
| `message` | 增量片段，类型是 `think` 或 `response` |
| `finish` | 消息 ID、可选标题、sources、消息状态 |
| `done` | 协议终点 `[DONE]` |
| `cancel` | 取消时的完成载荷 |
| `reject` | 容量拒绝提示 |

`messageChunkSize` 控制一次向前端发送多少 Unicode code point，当前 YAML 是 1。实现按 code point 而不是 Java `char` 切分，避免把代理对字符从中间切断。

`SseEmitterSender` 用 `AtomicBoolean closed` 让 complete/fail 幂等；发送发生异常时，它调用 `completeWithError` 并记录日志，而不会在流已经开始后再把异常抛给普通 MVC 异常处理器。

### 8.8.1 正常完成

`onComplete` 尝试保存 assistant 消息，其中包含：

- 累积 answer；
- 可选 thinking 与耗时；
- sources；
- grounding chunks；
- `replyToMessageId`；
- `MessageStatus.NORMAL`。

即使 assistant 落库失败，事件处理器仍会发：

```text
FINISH → DONE → unregister task → complete emitter
```

因此“前端收到完整答案”和“assistant 消息一定已经成功持久化”不是同一事实。

### 8.8.2 流错误

`onError` 在尚未取消时注销 task，并让 sender 异常结束 emitter。该 Handler 本身不会再保存一条“失败 assistant 消息”，Trace wrapper 则负责把 Run 终结为错误。

### 8.8.3 用户取消

取消 finalizer 会把已经累积的非空回答保存为 `INTERRUPTED`，然后发送：

```text
CANCEL → DONE → complete
```

取消分支不发送正常 `FINISH`。若在任何正文到达前取消，messageId 可以为空；这仍是一条有效的终止协议。

---

## 8.9 跨节点取消：标记、广播、本地动作三层配合

`StreamTaskManager` 同时使用本地缓存和 Redis：

```text
本地 Cache<taskId, StreamTaskInfo>
    ownerUserId
    cancelAction      中断上游模型流
    finalizer         保存已累积内容并发 CANCEL/DONE
    cancelled CAS

Redis
    ragent:stream:owner:{taskId}
    ragent:stream:cancel:{taskId}
    ragent:stream:cancel topic
```

### 8.9.1 为什么 owner 必须在 Redis

停止请求可能落到另一台应用节点。`cancelByUser` 先读取 owner，若明确存在且与当前用户不同，返回统一的“任务不存在或已结束”，既阻止越权停止，也避免把接口变成他人任务探测器。

taskId 是时间有序的雪花 ID，不是访问凭证。权限来自 user ownership，而不是“知道 taskId 就能操作”。

### 8.9.2 为什么先写取消标记再广播

停止可能早于 task 在执行节点完成注册。发布方先写带 TTL 的取消标记，再广播 `taskId|requester`。若执行节点当时没有本地 task，广播可以暂时没有动作；等 `register` 落下 owner 和 finalizer 后，会回查 Redis 标记并再次校验 requester。

这补上了“取消先到、注册后到”的竞态窗口。

### 8.9.3 为什么有两种回调

取消时顺序是：

```text
cancelAction → finalizer
```

- `cancelAction` 由模型流建立后通过 `bindHandle` 注入，用于中断上游；
- `finalizer` 在 Handler 初始化时注册，用于持久化已积累内容和关闭 SSE。

若取消发生在模型 handle 绑定之前，本地 `cancelled` 已经置位；之后 `bindHandle` 会立即执行 cancelAction。这样取消不会因为“上游句柄晚到”而丢失。

管理器本身还提供系统侧 `cancel(taskId)`，使用特殊 requester 无条件回收；用户侧 `cancelByUser` 则必须精确匹配 owner。**但在当前 RAG 接线中，emitter 的 completion/timeout/error 只经 `ChatQueueLimiter.cancelBinder` 绑定到 Ticket cancel，没有找到把这些回调继续接到 `taskManager.cancel(taskId)` 的调用。** Agent 路径有显式系统取消接线，RAG 本章不能沿用那条结论。

因此当前 RAG 的准确边界是：用户调用 `/rag/v3/stop` 可以进入跨节点任务取消协议；客户端断线/超时会关闭 sender 并清理尚在排队的 Ticket，但源码不能证明它一定同步广播取消已开始的上游模型流。后者应当作为当前接线边界讲清，而不是根据 `StreamTaskManager` 中存在一个公有方法推断已经生效。

---

## 8.10 一张终态表看懂“完成”

| 情况 | 消息持久化 | SSE 终点 | task 清理 | Trace |
|---|---|---|---|---|
| 正常完成 | 尝试保存 `NORMAL` assistant | `FINISH → DONE` | `unregister` | wrapper 收为成功 |
| 用户主动停止 | 有回答时尝试保存 `INTERRUPTED` | `CANCEL → DONE` | 跨节点取消协议触发 | 以 callback 实际终结语义为准，不能仅从 SSE 名称推断 |
| RAG 客户端断线/SSE 超时 | sender 标记关闭；尚在排队时 Ticket 被取消 | 连接本身已关闭 | 当前接线未证明会调用 `taskManager.cancel(taskId)` 取消已开始的上游流 | 不能从断线单独推断 Run 如何收尾 |
| 流错误 | Handler 不保存失败 assistant | `completeWithError` | `unregister` | wrapper 收为错误 |
| 排队/线程池拒绝 | 尝试保存 USER + `REJECTED` assistant | `REJECT → FINISH → DONE`，记录失败时至少尽力 `DONE` | 未进入正常 Pipeline task | 不进入正常 Trace Runner |
| Controller 防重失败 | 正常 MVC 业务异常 | 尚未建立本次业务 SSE 流 | 无 task | 无 Run |

因此验证或解释一条流时，要分别问：HTTP 是否建立、SSE 是否有协议终点、消息是否持久化、task 是否注销、Trace 是否收尾。任何一个“成功”都不能自动替代其他四个。

---

## 8.11 责任边界与设计解读

| 组件 | 负责 | 不负责 |
|---|---|---|
| `RAGChatController` | 参数边界、创建 emitter、停止接口 | 不执行 Pipeline |
| `IdempotentSubmitAspect` | 同步 Controller 提交窗口防重 | 不覆盖整个异步流生命周期 |
| `ChatQueueLimiter` | 开关、排队入口、reject 业务协议 | 不执行检索和模型调用 |
| `FairDistributedRateLimiter` | 跨节点公平排队、许可、Ticket 竞态与清理 | 不理解会话或消息语义 |
| `StreamChatEventHandler` | callback→SSE、累积答案、正常/取消持久化 | 不决定检索结果 |
| `StreamTaskManager` | task owner、跨节点取消、上游动作和 finalizer | 不把 task 本身当作持久业务记录 |
| `SseEmitterSender` | 线程安全发送和幂等关闭 | 不定义业务终态 |

从实现可以合理解读出：

- 先发 META、先注册 finalizer，可以让用户在业务主链任何阶段都有可取消身份；
- Redis owner + requester 复核，可以防止可预测 taskId 变成越权操作凭证；
- reject 也采用完整事件协议，可以让前端只处理一套流式状态机；
- permit lease 可以兜底进程崩溃，但当前没有续租意味着必须结合任务时长设置，不能把默认值当成无限期并发占位。

这些是基于实现结构的解读，不冒充作者在文档中明确写出的设计宣言。

---

## 8.12 面试追问与回答骨架

### 问：为什么已经有 `@IdempotentSubmit`，还需要全局限流？

切面锁在 Controller 返回 `SseEmitter` 后就释放，只防同步重复提交。全局限流控制真正进入 Trace/Pipeline 的跨节点并发，并对等待、超时和许可泄漏建模，职责不同。

### 问：为什么用 `conversationId` 不能停止任务？

conversation 是多轮持久会话，一个会话可先后有多个流；task 才代表本次运行和上游句柄。停止还要校验 task owner，避免知道 ID 就能取消他人的流。

### 问：排队公平从哪里来？

Redis 有序队列给请求稳定次序，Lua 原子 claim 队头窗口；claim 后未取到 permit 时按原 score 重入。topic 唤醒加轮询兜底促进进展，Ticket CAS 保证 grant/timeout/cancel 互斥。

### 问：客户端断线会发生什么？

emitter 的 completion/timeout/error 会让 sender 进入 closed，并通过限流器的 cancelBinder 清理尚在等待的 Ticket。当前 RAG 代码没有把这些 emitter 回调显式接到 `taskManager.cancel(taskId)`，所以不能进一步承诺已开始的上游模型流一定随断线被广播取消；用户主动 `/stop` 才明确进入该协议。

### 问：前端收到 `[DONE]` 是否证明消息已入库？

不证明。正常和 reject 路径都把“不能让前端永久等待”放在优先位置；持久化失败会记录日志，但仍可能发送 DONE。要分别观察消息表和 SSE 终点。

### 问：默认配置是否严格保证最多 10 条流直到完成？

不能这样承诺。许可通过 30 秒显式 lease 获取，源码未显示续租，而 SSE 最长 300 秒。长于 lease 的流可能不再占有原 permit；默认值更像带崩溃兜底的正常时长并发闸门。

---

## 8.13 源码定位卡

- `rag/src/main/java/com/nageoffer/ai/ragent/rag/controller/RAGChatController.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/impl/RAGChatServiceImpl.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/idempotent/IdempotentSubmitAspect.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/ratelimit/ChatQueueLimiter.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/ratelimit/FairDistributedRateLimiter.java`
- `rag/src/main/resources/lua/queue_claim_atomic.lua`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/handler/StreamCallbackFactory.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/handler/StreamChatEventHandler.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/web/StreamTaskManager.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/web/SseEmitterSender.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/enums/SSEEventType.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/RAGRateLimitProperties.java`
- `bootstrap/src/main/resources/application.yaml`

---

## 8.14 读完本章，你应该能自己回答

1. `conversationId`、`taskId`、`messageId` 分别属于会话、运行还是持久消息？
2. META 为什么在排队前发送？
3. `@IdempotentSubmit` 为什么不能替代全局并发闸门？
4. Ticket 的 CAS 状态机怎样避免 grant、timeout、cancel 重复执行？
5. 用户停止为什么要同时有 Redis owner、取消标记和广播？RAG 断线是否也走了同一条接线？
6. `cancelAction` 与 `finalizer` 分别清理哪一层？
7. 为什么 HTTP 200、SSE DONE、消息入库和 Trace 成功要分开判断？

下一章从 `StreamChatPipeline.loadMemory` 继续：许可拿到后，系统第一次真正的业务副作用不是检索，而是加载历史并先把本轮 USER 消息写入会话。
