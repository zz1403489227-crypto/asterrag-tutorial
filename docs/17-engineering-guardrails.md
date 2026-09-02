# 第 17 章：业务主线之外的护栏——认证、幂等、并发、MQ、Trace 与审计

> 前面的章节已经分别走完知识写入、确定性 RAG 和 ReAct Agent。真实工程里，这三条主链并不是裸奔的：请求要先证明“你是谁”，服务要判断“这份资源是不是你的”，并发入口要防止重复和过载，跨节点任务要能取消，数据库与消息队列要协调，最后还要留下可诊断、可追责的记录。
>
> 本章不按 Redis、RocketMQ、Sa-Token 等技术名词逐个介绍，而是把每道护栏放回它实际保护的那条箭头。最重要的阅读原则是：**存在一个通用类，不等于当前主链已经使用它；保护了一个短窗口，也不等于保护了整个业务生命周期。**

## 17.1 先建立全局模型：护栏保护的是“箭头”，不是“系统”两个字

把三条主链压缩成下面这张图：

```text
浏览器请求
   │
   ├─ 登录拦截：这个请求是否有有效登录态？
   ├─ UserContext：后续代码以哪个 userId/role 执行？
   └─ 服务层归属条件：这个用户能否操作这个 conversation/message/task？
          │
          ├─ 写接口短窗口：@IdempotentSubmit / 上传许可
          ├─ 长流完整窗口：ChatQueueLimiter / AgentRunGate / StreamTaskManager
          │
          └─ 业务方法
               ├─ PostgreSQL 事务：本地业务事实
               ├─ RocketMQ：把后续耗时动作交给消费者
               ├─ Redis：跨节点协调态
               ├─ RAG Trace：一次确定性 RAG 到底慢在哪、错在哪
               └─ BizChangeLog：谁修改了哪个管理对象、前后发生了什么变化
```

这里至少有六种不同问题：

| 问题 | 当前主要机制 | 保护窗口 | 不能自动推出 |
|---|---|---|---|
| 请求是否登录 | Sa-Token 登录拦截器 | MVC 请求入口 | 已做所有角色与权限校验 |
| 当前执行身份是谁 | `UserContext` | 当前线程及正确包装的异步任务 | 任意新线程/MQ 消费线程都会自动有用户 |
| 资源是否属于请求者 | Mapper 条件、服务层校验、任务 owner key | 具体资源操作 | 只要登录就能操作任意 ID |
| 是否重复/过载 | 防重锁、信号量、公平队列、Agent gate | 各自不同 | 一个锁包住完整 SSE 生命周期 |
| 数据库与异步动作如何衔接 | 本地事务 + RocketMQ 事务消息/普通消息 | 发送及后续消费 | 下游处理一定成功一次且仅一次 |
| 怎样回看发生过什么 | Trace、变更审计、业务表 | 各自不同 | 日志、Trace、审计是同一个对象 |

面试时不要笼统地说“项目做了分布式锁、MQ、链路追踪，所以高可用”。更准确的回答方式是：

1. 先指出被保护的具体箭头；
2. 再说机制的 owner 和有效窗口；
3. 最后主动说明窗口之外还剩什么风险。

---

## 17.2 HTTP 入口：登录检查、演示只读和用户上下文是三道不同的门

`SaTokenConfig` 给 MVC 注册了两道拦截器，另一道演示模式拦截器由 `RagentWebMvcConfiguration` 注册。顺序常量明确写成：

```text
order 0   Sa-Token 登录检查
   ↓
order 10  DemoModeReadOnlyInterceptor
   ↓
order 20  UserContextInterceptor
   ↓
Controller
```

这三个动作不能合并理解：

- 登录检查回答“有没有有效会话”；
- 演示只读回答“当前演示配置是否允许写操作”；
- 用户上下文回答“后续业务代码应以哪个用户身份执行”。

登录拦截器覆盖 `/**`，只排除 `/auth/**` 和 `/error`。普通业务 URL 因此默认需要登录。

### 17.2.1 为什么 OPTIONS 和 ASYNC 会被跳过

源码对两类请求直接放行：

- `OPTIONS` 是 CORS 预检，不应在浏览器真正发业务请求前就被登录拦截挡住；
- `DispatcherType.ASYNC` 是 SSE 完成后可能发生的异步 dispatch，此时原 Sa-Token 上下文已经不在，重复检查会把正常的异步收尾误判成未登录。

`UserContextInterceptor` 对这两类请求也同样跳过。这里的含义不是“异步请求无需认证”，而是：**初始业务请求已经在同步 dispatch 中完成认证，后续容器内部的 ASYNC dispatch 不再重复套用原入口上下文。**

### 17.2.2 每个普通请求为什么还要查一次用户表

登录检查通过后，`UserContextInterceptor.preHandle`：

```text
StpUtil.getLoginIdAsString()
  ↓
UserMapper.selectById(loginId)
  ↓
LoginUser(userId, username, role, avatar)
  ↓
UserContext.set(...)
```

因此后续业务拿到的不只是 token 里的登录 ID，还包括数据库当前的用户名、角色和头像。请求结束时，`afterCompletion` 调用 `UserContext.clear()`，避免 Web 线程被复用后把 A 用户身份泄漏到 B 请求。

这也带来一个很直接的工程取舍：普通请求会多一次用户表查询，但角色等用户资料不会永久冻结在一个很久以前签发的 token 快照里。

---

## 17.3 登录不等于授权：当前权限边界必须按源码精确描述

Sa-Token 的 `StpInterface` 实现提供了两个列表：

```text
getPermissionList(...) → 永远返回空列表
getRoleList(...)       → 根据 loginId 查询用户表，返回用户 role
```

这意味着当前项目有登录态和角色数据，但没有建立细粒度 permission code 列表。

全仓冻结源码中，显式 `StpUtil.checkRole("admin")` 出现在 `UserController` 的四个用户管理操作：分页、创建、更新、删除。没有发现 `@SaCheckRole`、`@SaCheckPermission` 或其他显式 permission check。

因此需要避免两个常见误读：

1. **URL 叫 `/admin/...` 不会自动触发管理员校验。** `@RequestMapping("/admin/dashboard")` 和 `@RequestMapping("/admin/kg")` 本身只是路径映射。
2. **前端是否隐藏菜单不是后端授权。** 真正的后端边界必须能在拦截器、注解、显式 check 或带 owner 条件的查询里找到。

当前源码能够确认的是：

- 除认证路径外的普通接口默认要求登录；
- 用户管理四个写/读操作显式要求 `admin` role；
- permission 列表当前为空；
- 其他资源要继续看各自的 service/mapper 归属条件，不能用“都登录了”代替。

这不是在评价项目对错，而是在面试中准确划定源码实现范围。

---

## 17.4 资源归属：ID 是定位符，不是访问凭证

雪花 ID 很长，但并不等于不可猜的授权 token。项目在对话、消息和流式任务上都体现了这个原则。

### 17.4.1 RAG 与 Agent 会话按 userId 收口

确定性 RAG 的会话查询、消息查询、重命名、删除等路径，把 `conversationId` 与 `UserContext.getUserId()` 一起交给服务。Mapper 条件继续同时限定 conversation 与 user。

Agent 路径同样使用 `(conversationId, userId)`：

- `listByUserId` 只列当前用户会话；
- `listMessages` 同时过滤 conversation 和 user；
- `touchConversation` 不会仅凭 conversationId 接管他人的会话；
- rename、delete、deleteBatch 都带 userId；
- Agent State 的身份键也是 `(userId, sessionId)`。

因此正确心智模型是：

```text
conversationId 负责找到“哪一段对话”
userId          负责证明“这段对话属于谁”
二者一起        才构成业务查询边界
```

### 17.4.2 主动停止为什么还要保存 task owner

`StreamTaskManager` 为每个运行任务在 Redis 写：

```text
ragent:stream:owner:{taskId}  → ownerUserId
ragent:stream:cancel:{taskId} → requester
```

用户调用停止接口时，`cancelByUser` 先读取 owner key。若 owner 存在且不是当前用户，就统一抛出“任务不存在或已结束”，既拒绝越权，也不向攻击者暴露任务是否真实存在。

取消广播的 payload 还会带 `taskId|requester`。真正运行任务的节点收到广播后再次比对本地 owner，避免只在发布节点检查、执行节点却无条件中断。

这形成两次校验：

```text
停止请求落点                    真正运行任务的节点
读取 Redis owner                读取本地 StreamTaskInfo.owner
       │                                  │
       └── 通过后发布 taskId|requester ───┘
                                          ↓
                                requester 匹配才 cancel
```

属主 key 还未落地时，用户取消标记会先被写入 Redis；任务注册时再复核标记和 owner。这是在处理“停止请求比任务注册更早到达”的竞态。

### 17.4.3 SYSTEM 取消与用户取消不是同一种权限

SSE 超时、断线等容器回调线程可能没有登录上下文，所以系统侧使用 `__system__` requester，可以无条件回收任务。用户主动停止则必须精确匹配 owner。

这里不能为了复用而把两条路径都设计成“无条件 cancel(taskId)”，否则时间有序的 taskId 就可能成为越权中断入口。

---

## 17.5 UserContext 跨线程：TTL 解决“传递”，不解决“凭空创建”

`UserContext` 使用 `TransmittableThreadLocal<LoginUser>`，项目线程池又普遍用 `TtlExecutors` 包装。因此，当 HTTP 线程把任务提交给这些已包装 Executor 时，用户上下文快照可以随任务传过去。

但 TTL 的边界必须说清：

- 它能捕获提交时已有的上下文；
- 它要求任务经过 TTL 包装的执行器或显式 `TtlRunnable`；
- 它不会让任意新线程、Broker 消费线程、定时调度线程自动知道用户是谁；
- 仍然必须在生命周期结束时清理，避免线程复用污染。

源码中两个非 HTTP 例子说明了这一点：

1. `KnowledgeDocumentChunkConsumer` 从消息事件读取 operator，手工设置一个包含 username 的 `LoginUser`，执行 `executeChunk` 后在 `finally` 清理；
2. `ScheduleRefreshProcessor` 以 SYSTEM 身份设置上下文，处理完成再清理。

所以面试时可以这样解释：

> TTL 是上下文传播机制，不是认证机制。HTTP 入口先认证并建立 UserContext；正确包装的异步任务可以继承快照；MQ/调度等独立入口必须从可信事件或系统身份重新建立上下文，并负责清理。

---

## 17.6 防重复提交：锁住的是 Controller 同步窗口，不是 SSE 整条流

`@IdempotentSubmit` 的切面先看 `ragent.eval.enabled`：

```text
eval.enabled == true  → 直接 proceed，不执行防重
eval.enabled == false → 计算 Redis lock key，tryLock，方法结束后 unlock
```

冻结的 `application.yaml` 当前把 `ragent.eval.enabled` 配成 `true`，所以随仓库当前默认配置会绕过这套提交防重。

### 17.6.1 lock key 怎样生成

有两种方式：

- 注解指定 SpEL key 时，使用 `idempotent-submit:key:{表达式结果}`；
- 未指定时，用 servlet path + currentUserId + 参数 JSON 的 MD5。

MultipartFile 在参数 JSON 中只包含字段名、原始文件名、content type 和 size，不读取文件字节。因此两个文件若这些元信息完全相同，默认 key 不能区分它们的内容；反过来，这也避免为了计算防重键再读一遍大文件。

### 17.6.2 当前到底接到了哪里

全仓主代码只有 `RAGChatController` 两个实际使用点：

- `/rag/v3/chat`：key 只取当前 userId；
- `/rag/v3/stop`：使用默认 path/user/args key。

关键是切面在 `joinPoint.proceed()` 返回后立刻解锁。`chat` 方法只创建 `SseEmitter`、调用 `streamChat` 并返回 emitter；真正问答在后续异步线程继续。因此即便把 eval 关闭，这把锁也只覆盖 Controller 建立异步任务的同步窗口。

```text
tryLock
  ↓
Controller 创建 emitter / 提交异步任务
  ↓
Controller return
  ↓
unlock                         ← 锁到这里结束
  ↓
排队、检索、模型流式输出       ← 已不在这把锁里
```

这正是 `AgentRunGate` 注释强调的区别：Agent gate 覆盖完整流生命周期，而 `@IdempotentSubmit` 不覆盖。

---

## 17.7 同一“并发保护”在项目里其实有四种时间尺度

| 机制 | 保护对象 | 获取失败怎样处理 | 释放/过期 | 主要剩余边界 |
|---|---|---|---|---|
| `UploadRateLimitFilter` | multipart 上传入口 | 等待后返回 429 | 请求 finally 释放；许可带 lease | 只匹配指定上传 URL，不限制后续 MQ 分块全程 |
| `@IdempotentSubmit` | Controller 同步调用 | 立即报重复提交 | 方法返回即解锁 | 当前 eval 默认绕过；不覆盖异步长流 |
| `FairDistributedRateLimiter` | 确定性 RAG 全局并发槽 | 公平排队，超时写 REJECT 业务消息并结束 SSE | 业务 Runnable finally 释放；permit 有 lease | permit lease 与真实业务时长需要匹配 |
| `AgentRunGate` | 每用户一条 Agent 流 | 立即拒绝 | RunHandle 收尾 compareAndSet 释放；崩溃靠 TTL | TTL 到期后旧流若仍活着，新流可能获得新槽 |

### 17.7.1 上传许可为什么必须在 multipart 解析前

`UploadRateLimitFilter` 是最高优先级的 `OncePerRequestFilter`。它只匹配：

```text
POST + URI 包含 /knowledge-base/ + 以 /docs/upload 结尾
```

过滤器先从 Redis 的 `RPermitExpirableSemaphore` 获取许可，失败直接写 429，不进入 filter chain。这样过载请求不会先触发 multipart 临时文件生成，再在 Controller 里才被拒绝。

许可覆盖的是 HTTP 上传请求本身。请求完成后会释放；后续 RocketMQ 分块、解析、嵌入不继续占着这张上传许可。

### 17.7.2 公平队列为什么不只是一个 semaphore

`FairDistributedRateLimiter` 用 Redis 组合出：

```text
{name}:semaphore      全局许可
{name}:queue          ZSet 等待队列
{name}:queue:seq      单调序号
{name}:entry:{id}     带 TTL 的存活标记
{name}:queue:notify   跨节点唤醒主题
```

ZSet score 来自 Redis 原子序号，因此不同应用节点提交的请求可以进入同一全局次序。Lua claim 只允许队头窗口内的 ticket 抢占；若 claim 后没有拿到 permit，会用原 score 回队，避免丢失排队位置。

Ticket 的状态只允许一次从 `PENDING` 进入 `GRANTED`、`TIMED_OUT` 或 `CANCELLED`。permit 在提交给业务 Executor 后由包装 Runnable 的 `finally` 负责释放，防止 emitter 完成回调过早归还仍在使用的槽。

### 17.7.3 AgentRunGate 为什么用值比较释放

Agent gate 的 Redis value 是：

```text
taskId|conversationId
```

释放时不是无条件 delete，而是 `compareAndSet(slotValue, null)`。如果旧槽已因 TTL 到期消失、下一轮又占了同一个用户 key，旧任务迟到的 release 不会误删新任务的槽。

这是一条很值得面试展开的并发原则：**释放动作也必须证明“当前资源仍由我持有”。**

---

## 17.8 Redis 在 AsterRAG 中不是“缓存”，而是多种协调协议的载体

把当前主要用途按状态语义分类，比说“项目用了 Redis 做缓存”准确得多：

| Redis 状态 | owner | 是否业务真相 | 失效后的恢复方式 |
|---|---|---|---|
| Sa-Token 登录态 | 认证框架 | 登录会话事实的一部分 | 重新登录/会话过期 |
| 上传 expirable permit | 上传入口 | 否，协调态 | lease 到期或 finally 释放 |
| RAG 公平队列、entry、permit、notify | 全局限流器 | 否，排队/并发协调态 | entry/permit TTL、Lua 僵尸清理、重试 |
| Agent running slot | Agent gate | 否，运行互斥态 | 正常 release 或 TTL |
| stream owner/cancel key + topic | `StreamTaskManager` | 否，跨节点取消协议 | 结束时 unregister；30 分钟 TTL |
| 防提交锁 | `IdempotentSubmitAspect` | 否，短窗口互斥 | 方法 finally 解锁 |
| 消费幂等状态 | 通用切面 | 若接入则是消费协调态 | success 写 CONSUMED，失败删 key | 
| Snowflake worker/datacenter 分配 | ID 初始化器 | 是生成配置协调态 | 应用启动执行 Lua |

这张表还揭示一个共同风险：Redis 协调态大多带 TTL，是为了进程崩溃时能自行恢复；但 TTL 同时意味着业务耗时若超过 lease，保护可能提前失效。正确的面试回答不是“有 Redis 锁所以绝对不会并发”，而是继续说清 lease 与实际任务时长的关系。

---

## 17.9 分布式 ID：Redis 分配节点号，Hutool 生成 Snowflake ID

`SnowflakeIdInitializer` 在启动时执行 `snowflake_init.lua`，从 Redis Hash `snowflake_work_id_key` 分配：

```text
workId       0..31
datacenterId 0..31
```

拿到二元组后，它创建 Hutool `Snowflake` 并放入 Hutool `Singleton`。MyBatis-Plus 的 `CustomIdentifierGenerator` 再通过 `IdUtil.getSnowflakeNextId()` 或字符串版本生成 ID。

Lua 的分配规则是按 workId 递增，满 31 后递增 datacenterId；二者都到 31 后会回绕到 `(0, 0)`。所以源码能证明的是“通过 Redis 原子脚本为启动实例分配 1024 组节点号”，不能无限扩展成“任何规模、任何重启策略下都绝无 ID 冲突”。

它还有一个启动边界：Redis 调用或返回格式失败时，initializer 抛异常，项目没有回退成本机随机 workerId。换句话说，Redis 在当前默认装配中不仅服务运行协调，也参与 ID 生成器初始化。

---

## 17.10 RocketMQ：它保护的是“本地事实提交后，后续动作有机会继续”

当前冻结源码有三类实际消费者：

| 业务 | 生产方式 | Consumer | 消费后的动作 |
|---|---|---|---|
| 文档开始分块 | 事务消息 | `KnowledgeDocumentChunkConsumer` | 建立 operator 上下文，调用 `executeChunk` |
| 删除知识库 | 事务消息 | `KnowledgeBaseCleanupConsumer` | 清向量空间、对象目录，并按配置清关键词/图谱 |
| 点赞/点踩/取消反馈 | 普通同步消息 | `MessageFeedbackConsumer` | 校验消息归属，按提交时间 upsert 反馈 |

这里的价值不是“把所有业务都异步化”，而是把耗时、可重试的后续动作从原 HTTP/本地事务中拆开。

### 17.10.1 事务消息的两阶段事实

`RocketMQProducerAdapter.sendInTransaction` 为每条消息注册一个进程内 local transaction closure：

```text
txId → Consumer<Object>
```

Broker 要执行本地事务时，`DelegatingTransactionListener` 以 remove 方式取出 closure，并放进 Spring `TransactionTemplate`。执行一次后闭包即从本机 Map 消失。

但 Broker 回查可能落到任何实例，不能依赖这个 Map。因此项目另有：

```text
topic → TransactionChecker
```

Checker 必须只根据消息内容和持久数据库判断：

- 文档 checker 看文档是否已经是 `RUNNING`；
- 知识库 checker 看逻辑删除是否已对普通查询不可见。

这两种事实回答的是“发送所对应的本地事务是否提交”，不是“消费者后续工作是否已经成功”。

### 17.10.2 为什么回查不能读进程内回调

可能的时序是：

```text
实例 A 发送 half message
实例 A 本地事务提交
实例 A 随后宕机
Broker 把回查发给实例 B
```

实例 B 不可能拥有 A 的 closure。只有数据库中的 `RUNNING` 或逻辑删除事实是跨节点可见的。因此 `TransactionChecker` 接口注释明确要求从消息和 DB 重建判断。

### 17.10.3 事务消息没有把整条异步链变成一个事务

以文档分块为例：

```text
文档状态改为 RUNNING + schedule upsert  ← 本地事务
                 │
                 └─ RocketMQ COMMIT
                         ↓
                 Consumer 执行解析/分块/嵌入/索引
                         ↓
                 最终 SUCCESS 或 FAILED
```

事务消息只协调第一段 DB 事实与“消息是否应该投递”。解析到索引仍是独立的长业务过程，其失败与结算规则已经在第 6～7 章说明。

---

## 17.11 通用消费幂等切面存在，但当前三个 Consumer 没有接入它

`IdempotentConsumeAspect` 提供了一个可复用协议：

```text
Redis SET NX GET PX
  ├─ 已是 CONSUMING → 抛异常，让消息稍后重试
  ├─ 已是 CONSUMED  → 直接跳过
  └─ 首次获得       → 执行业务
                         ├─ 成功：写 CONSUMED + TTL
                         └─ 失败：删除 key，允许重试
```

但是全仓主代码没有任何实际 `@IdempotentConsume` 使用点，三个 `@RocketMQMessageListener` Consumer 都没有这个注解。

因此教程不能写成“MQ 消费通过 Redis 切面保证幂等”。准确说法是：

- framework 模块提供了通用消费幂等能力；
- 当前三条消费链没有接到这个切面；
- 它们实际能否安全重试，要分别看业务 upsert、状态机、删除幂等性和异常重抛，而不是引用一个未使用的类。

这正是源码阅读中“实现存在”与“主链生效”的典型区别。

---

## 17.12 三个 Consumer 的重复与乱序边界并不相同

### 17.12.1 文档分块

Consumer 直接调用 `executeChunk`。文档状态机、Chunk/向量写入顺序和最终结算决定重复执行的结果；不能仅凭 MQ 框架就宣称 exactly-once。第 6～7 章已经分别说明业务失败何时被吃掉、何时消息会重试，以及 SUCCESS 与所有外部索引一致性的边界。

### 17.12.2 知识库清理

Consumer 对各类物理资源执行删除。删除通常可以重复调用，但源码仍会在某项清理失败时抛异常，让 MQ 重试。逻辑删除是 DB 事实，物理清理是异步最终动作；两者之间允许存在时间差。

### 17.12.3 消息反馈

反馈使用普通消息，不与原请求的数据库事务绑定。Consumer 落库时先校验 assistant 消息确实属于事件 user，再按 submittedAt 做 upsert，避免旧消息晚到后覆盖新反馈。

这应回答成“利用业务主键与提交时间处理重复/乱序”，不能回答成“RocketMQ 天然保证严格顺序且只消费一次”。

---

## 17.13 线程池隔离：既分责任，也定义过载时谁承担工作

`ThreadPoolExecutorConfig` 没有只暴露一个万能线程池，而是按责任拆分：

| Executor | 主要用途 | 队列 | 拒绝策略 |
|---|---|---|---|
| `mcpBatchExecutor` | MCP 批调用 | `SynchronousQueue` | `CallerRunsPolicy` |
| `ragContextExecutor` | 子问题级上下文并行 | `SynchronousQueue` | CallerRuns |
| `ragRetrievalExecutor` | 检索通道并行 | `SynchronousQueue` | CallerRuns |
| `innerRetrievalExecutor` | 通道内部检索 | 有界 100 | CallerRuns |
| `intentClassifyExecutor` | 意图并行 | `SynchronousQueue` | CallerRuns |
| `memorySummaryExecutor` | 会话摘要 | 有界 200 | CallerRuns |
| `modelStreamExecutor` | 模型流式输出 | 有界 200 | `AbortPolicy` |
| `chatEntryExecutor` | 排队成功后的入口 | `SynchronousQueue` | AbortPolicy |
| `knowledgeChunkExecutor` | 文档分块 | 有界 200 | AbortPolicy |
| `memoryLoadExecutor` | 摘要与历史并行加载 | 有界 200 | CallerRuns |

### 17.13.1 CallerRuns 与 Abort 的含义

`CallerRunsPolicy` 不会凭空增加容量。池满时，它让提交任务的调用线程自己执行，等价于把背压推回上游、自然降低继续提交的速度。

`AbortPolicy` 则直接抛 `RejectedExecutionException`，要求调用方显式处理。例如：

- `ChatQueueLimiter` 捕获 chat entry 拒绝并走 REJECT 流程；
- 模型流/分块路径必须由各自调用链处理提交失败，不能假设任务总能排进队列。

### 17.13.2 SynchronousQueue 为什么不是“无限快”

它没有存储队列容量。提交时必须立即找到空闲线程，否则扩线程或触发拒绝策略。这样可以避免大量延迟任务静默堆在内存里，但会把压力更早暴露给上游。

### 17.13.3 TTL 包装和线程池隔离解决的是两件事

- 独立线程池隔离不同资源预算与过载传播；
- `TtlExecutors` 负责 UserContext、RagTraceContext 等上下文快照传播。

有 TTL 不代表容量受控；有有界队列也不代表身份和 Trace 自动传递。两者缺一会出现不同类型的问题。

---

## 17.14 RAG Trace：回答“一次问答经过了什么、耗时多少”

`StreamChatTraceRunner` 是确定性 RAG 的顶层 trace owner。开启 `ragent.trace.enabled` 后，它创建一条 `t_rag_trace_run`：

```text
traceName      rag-stream-chat
entryMethod    RAGChatService#streamChat
conversationId / taskId / userId
status         RUNNING
questionLength / question
startTime
```

然后把 `traceId` 和 `taskId` 放进 `RagTraceContext`，让内部节点记录在同一个 Run 下。

### 17.14.1 注解节点为什么有上下文才生效

`RagTraceAspect` 先检查：

1. Trace 配置是否开启；
2. `RagTraceContext` 中是否已有 traceId。

缺任一条件就直接执行原方法，不写节点。因此一个类上出现 `@RagTraceNode`，不代表从任何入口调用它都会产生 Trace；它必须处于顶层 Runner 建立的上下文里。

切面记录：

- nodeId、parentNodeId、depth；
- node type/name 和类/方法；
- RUNNING → SUCCESS/ERROR；
- start/end/duration 和截断后的错误。

### 17.14.2 并行节点为什么需要深拷贝栈

`RagTraceContext` 的节点栈是 `Deque<String>`。如果 TTL 只把同一个 Deque 引用传给多个子线程，它们并发 push/pop 会互相串父子关系。

源码覆盖 `copy()`，为子线程创建 `new ArrayDeque<>(parentValue)`。traceId 可以共享值，**可变节点栈必须复制结构**。这是线程上下文传播中非常典型的细节。

### 17.14.3 流式节点为什么不能只靠普通 AOP

普通 AOP 环绕一个返回异步流的方法，常常只能测到“提交异步任务”的时间。`RagStreamTraceSupportImpl` 因此显式提供 `beginStreamNode`，返回一个 `StreamSpan`：

```text
begin           写 RUNNING，push node
detach          调用线程结束时只 pop，不结束 span
finishSuccess   真正流完成后写 SUCCESS
finishError     真正流异常后写 ERROR
finishCancelledIfRunning → 写 CANCELLED
```

`AtomicBoolean` 保证同一 span 只收尾一次。

### 17.14.4 当前 Trace 范围不能扩大到 Agent 主链

顶层 runner 的名字和入口都指向 `RAGChatService#streamChat`。Agent 章节没有发现把 ReAct 主链接到这套 `t_rag_trace_run/node` 的顶层 Runner；AgentScope 自身可能有框架能力，也不能因此写成 AsterRAG 已把 Agent 轨迹落进当前 RAG Trace 表。

另外，第 13 章已经指出：正常完成和错误回调会结束顶层 Run，但当前显式取消链没有给出足够源码证据保证每次取消都触发 trace-aware callback 的 finish。流式 provider span 有 CANCELLED 收尾能力，不等于顶层 Run 的所有取消分支都已闭合。

---

## 17.15 变更审计：回答“谁改了哪个管理对象，改前改后是什么”

Trace 与审计虽然都“记录过程”，但问题完全不同：

| 对象 | RAG Trace | BizChangeLog |
|---|---|---|
| 关注点 | 一次 RAG 执行节点、状态与耗时 | 一次管理对象变更 |
| 主身份 | traceId/taskId/conversationId | bizType/bizId/operator |
| 数据 | 节点树、duration、error | before/after/diff、action、IP、UA |
| 当前主要范围 | 确定性 RAG | 有 `@LogRecord` 的服务写操作 |
| 能否互相替代 | 不能 | 不能 |

### 17.15.1 审计快照怎样生成

被注解的 service 在业务动作前后取得对象，并调用：

```text
bizChangeLogContext.put(bizId, before, after)
```

`BizChangeLogContext` 把对象转成 JSON tree，递归比较字段，产生：

```json
{
  "beforeSnapshot": {"name": "old"},
  "afterSnapshot":  {"name": "new"},
  "changeDiff": [
    {"field": "/name", "before": "old", "after": "new"}
  ]
}
```

对象字段按 JSON Pointer 风格记录；数组则按下标递归比较。`@LogRecord` 表达式再把 bizId、snapshot、成功/失败文案交给 log-record 框架。

### 17.15.2 最终审计行还包含什么

`BizChangeLogRecordService` 写入：

- 业务类型、业务 ID、操作类型和描述；
- before/after/changeDiff；
- operatorId/name/role；
- success 和 errorMessage；
- class/method；
- IP、User-Agent、createTime。

审计写入使用 `REQUIRES_NEW` 事务。当前线程有 UserContext 时优先记真实用户；没有时使用 logRecord operator 或 `SYSTEM`。非 HTTP 线程没有 request 时，IP 和 User-Agent 可以为空。

### 17.15.3 审计只覆盖实际注解的方法

冻结源码共有 40 个 `@LogRecord`，分布在 10 个 service 实现：

- 知识库、文档、Chunk；
- 通用 Ingestion Task/Pipeline、意图树；
- Agent Profile、查询术语映射；
- 示例问题；
- 用户管理。

因此正确表述是“这些受注解的管理变更会产生日志”，不能说“系统所有数据库写入都有审计”。聊天消息、Agent State、Trace 节点、MQ 消费等有自己的持久化语义，不会因为项目存在 BizChangeLog 就自动进入这张表。

---

## 17.16 失败时应该去哪张表找答案

| 现象 | 第一观察对象 | 原因 |
|---|---|---|
| 用户未登录或 token 失效 | Sa-Token 响应/认证日志 | 请求尚未进入业务 service |
| 用户能登录但不能操作他人会话 | service/mapper owner 条件、Stream owner key | 这是资源授权，不是登录问题 |
| RAG 请求一直排队或被拒绝 | Redis 公平队列/permit + REJECT 业务消息 | 并发入口已经做出业务终态 |
| Agent 提示已有会话处理中 | Agent running slot | 是用户维度完整流闸门 |
| 点击停止没有终止目标流 | owner/cancel key、Redis topic、本地 task registry、上游 handle | 跨节点取消是组合协议 |
| 文档一直 RUNNING/FAILED | 文档、schedule、chunk log、MQ 消费日志 | Trace 不是入库业务状态机 |
| RAG 很慢 | `t_rag_trace_run/node` | 可按节点树看耗时与错误 |
| 管理员问“谁改了配置” | `t_biz_change_log` | 审计记录 actor 和 before/after/diff |
| Agent 刷新后上下文不一致 | `t_agent_state` + 业务消息 + compaction/memory 控制表 | 不能用 RAG Trace 代替 Agent State |

这张表体现了第 3 章的状态所有权原则：排障时先问“谁拥有这个事实”，再决定读 PostgreSQL、Redis、本地内存、MQ 日志还是 Trace。

---

## 17.17 六个最容易说错的面试回答

### 误区一：“用了 Sa-Token，所以所有后台接口都有管理员权限保护”

修正：普通业务接口默认要求登录；角色列表从用户表读取；当前显式 admin check 只在用户管理四个操作中找到。路径前缀本身不构成角色授权。

### 误区二：“用了分布式锁，所以同一用户只能跑一条 RAG”

修正：RAG Controller 的防重锁只覆盖同步返回 emitter 前的窗口，而且当前 eval 默认绕过；确定性 RAG 的完整并发主要由全局公平队列控制。Agent 才有用户维度完整流 `AgentRunGate`。

### 误区三：“用了事务消息，所以文档入库和向量索引是一个事务”

修正：事务消息协调文档 RUNNING/schedule 的本地事务与消息提交；消费者中的解析、分块、嵌入和索引是后续独立过程。

### 误区四：“MQ 消费有通用幂等切面，所以 exactly-once”

修正：通用切面存在，但当前 Consumer 没有使用 `@IdempotentConsume`。要逐条分析业务状态机、upsert、乱序条件和删除幂等性。

### 误区五：“Trace 就是审计日志”

修正：Trace 解释执行树和耗时；审计解释业务对象的 actor 与前后变化；聊天消息与 Agent State 又是另外两类事实。

### 误区六：“TTL 能保证所有异步线程都有用户身份”

修正：TTL 只能传播提交时已有的上下文，且任务必须经过正确包装。MQ 与定时任务要显式建立并清理 UserContext。

---

## 17.18 一道完整面试题：用户连续点击两次“发送”，系统如何处理

可以按当前源码分两种引擎回答。

### 确定性 RAG

```text
两次请求先分别通过登录/UserContext
  ↓
当前默认 eval=true，@IdempotentSubmit 不拦截
  ↓
两次都进入 ChatQueueLimiter
  ↓
全局 permit 有空位：都可能成为独立任务
无空位：按 Redis 全局次序排队，超时者持久化 REJECT 并结束 SSE
```

所以当前不能回答“第二次一定被同用户锁拒绝”。公平队列限制的是系统全局并发，不是每用户互斥。

### ReAct Agent

```text
第一次抢 ragent:agent:running:{userId} 成功
  ↓
完整流运行期间 slot 一直存在

第二次 setIfAbsent 失败
  ↓
立即返回“当前会话处理中”
```

第一条流正常、取消或失败收尾时执行 value-aware release；进程崩溃则靠 TTL 恢复。

这个对比能同时说明：同一个产品动作在不同引擎下，入口并发策略并不相同。

---

## 17.19 一道完整面试题：用户在节点 B 停止了节点 A 上运行的流

可以从状态流转回答：

```text
节点 A 注册任务
  ├─ 本地 Cache: taskId → owner/cancelAction/finalizer
  └─ Redis owner key: taskId → userId

节点 B 收到 stop(taskId)
  ↓
从 UserContext 得到 requester
  ↓
Redis owner 精确匹配
  ↓
先写 cancel key，再 publish taskId|requester
  ↓
所有节点监听；节点 A 找到本地任务
  ↓
再次校验 requester == owner
  ↓
CAS cancelled
  ↓
先 cancelAction 中断上游，再 finalizer 补业务终态
  ↓
正常 unregister 清本地缓存和 Redis key
```

为什么先写 key 再广播？因为广播可能早于任务本地注册；后注册时还可以读取预埋 cancel key 补执行。为什么执行节点再验 owner？因为 taskId 不是秘密，发布节点的一次检查不能代替真正副作用发生处的检查。

---

## 17.20 设计取舍：项目为什么没有追求“一种机制解决所有问题”

下面是基于实现的设计解读，不冒充作者原话：

1. HTTP 登录、资源归属和操作审计拆开，允许不同资源采用不同 owner 规则；
2. 短请求用 lock/filter，长流用显式 gate、ticket 和 finalizer，因为生命周期完全不同；
3. Redis 只承载可过期、可重建的协调态，业务会话、Agent State 和审计仍落 PostgreSQL；
4. 事务消息只连接可判定的本地 DB 事实，不试图把远程索引纳入数据库事务；
5. Trace 与审计分别优化“性能诊断”和“业务追责”，避免一张万能日志表承担矛盾查询；
6. 独立线程池让不同负载有不同队列和拒绝语义，而 TTL 只负责上下文传播。

代价是阅读复杂度提高。面试中展现项目理解的关键，恰恰是能说清这些机制的边界，而不是背出依赖列表。

---

## 17.21 源码定位卡

### 登录、角色与上下文

- `system/src/main/java/com/nageoffer/ai/ragent/user/config/SaTokenConfig.java`
- `system/src/main/java/com/nageoffer/ai/ragent/user/config/UserContextInterceptor.java`
- `system/src/main/java/com/nageoffer/ai/ragent/user/config/SaTokenStpInterfaceImpl.java`
- `system/src/main/java/com/nageoffer/ai/ragent/user/controller/UserController.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/context/UserContext.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/context/LoginUser.java`

### 防重、限流、跨节点取消

- `framework/src/main/java/com/nageoffer/ai/ragent/framework/idempotent/IdempotentSubmitAspect.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/idempotent/IdempotentConsumeAspect.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/controller/RAGChatController.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/filter/UploadRateLimitFilter.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/ratelimit/ChatQueueLimiter.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/ratelimit/FairDistributedRateLimiter.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/ChatRateLimiterConfig.java`
- `agent/src/main/java/com/nageoffer/ai/ragent/agent/service/handler/AgentRunGate.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/web/StreamTaskManager.java`

### RocketMQ

- `framework/src/main/java/com/nageoffer/ai/ragent/framework/mq/producer/RocketMQProducerAdapter.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/mq/producer/DelegatingTransactionListener.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/mq/producer/TransactionChecker.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/mq/KnowledgeDocumentChunkConsumer.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/mq/KnowledgeDocumentChunkTransactionChecker.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/mq/KnowledgeBaseCleanupConsumer.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/mq/KnowledgeBaseCleanupTransactionChecker.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/mq/MessageFeedbackConsumer.java`

### ID 与线程

- `framework/src/main/java/com/nageoffer/ai/ragent/framework/distributedid/SnowflakeIdInitializer.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/distributedid/CustomIdentifierGenerator.java`
- `framework/src/main/resources/lua/snowflake_init.lua`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/ThreadPoolExecutorConfig.java`

### Trace 与审计

- `framework/src/main/java/com/nageoffer/ai/ragent/framework/trace/RagTraceContext.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/trace/RagTraceNode.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/trace/StreamChatTraceRunner.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/aop/RagTraceAspect.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/trace/RagStreamTraceSupportImpl.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/impl/RagTraceRecordServiceImpl.java`
- `system/src/main/java/com/nageoffer/ai/ragent/audit/support/BizChangeLogContext.java`
- `system/src/main/java/com/nageoffer/ai/ragent/audit/service/impl/BizChangeLogRecordService.java`
- `system/src/main/java/com/nageoffer/ai/ragent/audit/dao/entity/BizChangeLogDO.java`
- `bootstrap/src/main/resources/application.yaml`

---

## 17.22 读完本章，你应该能自己回答

1. 登录检查、UserContext、角色授权和资源归属分别在哪一层完成？
2. 为什么 `/admin/...` 路径本身不能证明有管理员授权？
3. TTL 能传播什么，为什么 MQ Consumer 还要手工建立 UserContext？
4. 当前 `@IdempotentSubmit` 为什么既默认被绕过，也不能覆盖整条 SSE？
5. Upload Filter、公平队列、AgentRunGate 分别保护多长的生命周期？
6. FairDistributedRateLimiter 怎样同时处理公平、取消、超时、节点崩溃和 permit 释放？
7. AgentRunGate 为什么必须 compareAndSet 释放自己的 slot？
8. StreamTaskManager 为什么在发布节点和执行节点都校验 owner？
9. RocketMQ 事务 checker 为什么必须查数据库，而不能查 local closure Map？
10. 事务消息能证明文档处理的哪一步，不能证明哪一步？
11. 为什么不能说当前三个 MQ Consumer 已由 `IdempotentConsumeAspect` 保护？
12. CallerRunsPolicy 和 AbortPolicy 分别把过载压力交给谁？
13. RagTraceContext 为什么要深拷贝节点栈？
14. 普通 AOP span 和显式 stream span 的计时终点有何不同？
15. RAG Trace、BizChangeLog、业务消息和 Agent State 各回答什么问题？

至此，后端三条主链和它们的工程护栏已经闭合。下一章转向前端：浏览器怎样选择确定性 RAG 或 Agent 入口，怎样消费 SSE 事件、投影消息与工具轨迹，以及管理页怎样对齐后端真实 API。只有把前端状态也接回这些后端 owner，才算真正理解用户眼中的完整系统。
