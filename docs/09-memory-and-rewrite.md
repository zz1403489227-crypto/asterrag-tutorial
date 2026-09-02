# 第 9 章：用户说的话不等于该搜的词——会话记忆、归一化、改写与拆分

> 上一章的请求取得许可后，`StreamChatPipeline` 并不先搜向量。它先读取会话记忆、持久化本轮 USER 消息，再把自然语言问题改造成适合后续意图识别和检索的形式。
>
> 本章要建立两个清晰模型：记忆不是无限聊天记录，查询也不是只有一条字符串。

## 9.1 固定 Pipeline 的前两步

`StreamChatPipeline.execute` 的开头顺序是固定的：

```java
loadMemory(ctx);
rewriteQuery(ctx);
resolveIntents(ctx);
```

把前两步展开：

```text
ConversationMemoryService.load(conversationId, userId)
    ├── 读最新摘要
    └── 读最近若干轮原文消息
          ↓
ConversationMemoryService.append(USER(question))
          ↓
callback.onReplyToMessageId(questionMessageId)
          ↓
QueryRewriteService.rewriteWithSplit(question, history)
          ↓
RewriteResult(rewrittenQuestion, subQuestions)
```

这里有一个很重要的时序：**先读取旧历史，再写入本轮 USER。** 因而传给查询改写和最终 Prompt 的 `history` 不含本轮问题；本轮问题由调用方在消息末尾显式添加，不会重复出现。

同时，USER 消息在改写、意图、检索和模型调用之前已经落库。若后续任何阶段失败，数据库中可能留下本轮 USER 而没有对应 assistant，这不是“消息事务漏提交”，而是当前异步业务时序的直接结果。

---

## 9.2 三张表承担三种长期事实

RAG 会话记忆使用 PostgreSQL，而不是把完整历史只放在 JVM 或 Redis：

| 表 | 保存什么 | 不等于什么 |
|---|---|---|
| `t_conversation` | `conversationId + userId` 对应的标题、最近时间 | 不保存完整消息正文 |
| `t_message` | USER/assistant 消息、thinking、sources、grounding、replyTo、状态 | 不等于本轮正在运行的 task |
| `t_conversation_summary` | 压缩后的摘要、覆盖到的 `last_message_id` | 不替代原消息，也不是事实来源 |

`StreamTaskManager` 的本地/Redis task 状态属于运行协调；这三张表属于可恢复业务事实。进程重启后，可以从消息表恢复历史，但不能从一行 message 恢复正在流式执行的模型句柄。

### 9.2.1 所有权不是只靠 conversationId

会话和消息查询都同时带 `conversationId` 与 `userId`。`t_conversation` 还有 `(conversation_id, user_id)` 唯一约束。

因此 conversationId 本身不是跨用户共享访问凭证。相同的字符串必须结合 userId 才构成业务归属，这与上一章 task owner 的安全思想一致。

---

## 9.3 USER 消息落库还会创建或刷新会话

`JdbcConversationMemoryStore.append` 先把 `ChatMessage` 映射为 `ConversationMessageBO`，保存：

- role、content；
- thinking 内容与耗时；
- sources、retrieved chunks；
- replyTo message ID；
- message status。

若角色是 USER，它随后调用 `ConversationService.createOrUpdate`：

- 新会话用首个问题生成标题并插入 `t_conversation`；
- 已有会话只刷新 `last_time`。

assistant append 不执行这段会话创建逻辑。因此主 Pipeline 在任何回答工作之前先持久化 USER，也保证了新会话和标题有机会先建立。

标题生成和会话摘要不是同一件事：标题用于列表导航；摘要用于以后提供历史语义。两者使用不同表、不同触发时机和不同 Prompt。

---

## 9.4 记忆窗口：默认只保留最近 8 轮原文

默认配置是：

```yaml
rag:
  memory:
    history-keep-turns: 8
    summary-enabled: true
    summary-start-turns: 9
    summary-max-chars: 400
    title-max-length: 30
```

`JdbcConversationMemoryStore.loadHistory` 计算 `maxMessages = historyKeepTurns × 2`，默认最多取最近 16 条消息。数据库先按时间和 ID 倒序取最近记录，Service 再反转为时间正序，交还给模型。

加载后还做三件清理：

1. 只保留 USER 和 ASSISTANT 且正文非空的消息；
2. assistant 正文中的引用标记通过 `CitationMarkup.strip` 去除，避免把旧回答里的 `[N](#cite-N)` 当作新一轮事实；
3. 若窗口开头是一段孤立 assistant 消息，连续丢弃，直到第一条 USER，避免从不完整半轮开始。

这里恢复成 `ChatMessage` 时只取 role 和净化后的 content。旧消息原本保存的 sources、thinking、grounding 和 status 不会作为本轮普通历史重新送入查询改写。这些字段仍可用于历史展示或其他功能，但“聊天上下文”不是数据库行的原样复制。

### 9.4.1 为什么按轮限制而不是无限累积

源码事实是最多保留 8 轮原文，设计上这样可以：

- 限制每次改写和生成的输入规模；
- 保留最近指代关系和当前任务状态；
- 把更久历史压成摘要，而不是重复付出全部 token；
- 避免旧错误或旧话题长期挤占注意力。

代价是窗口外的逐字细节不可由 recent history 还原，只能依赖摘要是否准确保留。

---

## 9.5 摘要与最近原文怎样拼接

`DefaultConversationMemoryService.load` 并行启动两个任务：

```text
summaryFuture  → loadLatestSummary
historyFuture  → loadHistory
```

二者各自有失败回退：摘要失败返回 null，历史失败返回空列表；外层仍出现异常时返回空历史。加载记忆失败不会直接阻断整次问答，而是降级为无历史处理。

成功后合并顺序是：

```text
SYSTEM: 被 summary-wrapper 包装的长期摘要
USER/ASSISTANT: 最近 8 轮原文
```

摘要被装饰为 SYSTEM 消息，明确告诉后续 Prompt 它是上下文，而不是用户刚说的一句话。`attachSummary` 在 recent messages 为空时直接返回空列表，因此当前实现不会单独返回一条“只有摘要、没有最近消息”的历史。

---

## 9.6 摘要何时生成：assistant 落库后异步触发

每次 `ConversationMemoryService.append` 完成后都会调用 `summaryService.compressIfNeeded(...)`。但摘要服务只在以下条件继续：

1. `summary-enabled=true`；
2. 刚追加的消息角色是 ASSISTANT；
3. 异步任务取得该 `userId + conversationId` 的 Redisson 锁；
4. USER 消息总数达到 `summary-start-turns`，当前是 9；
5. 有尚未被最新摘要覆盖、且即将滑出最近窗口的消息。

所以 USER append 不会立即摘要，正常、取消或拒绝分支追加的 assistant 都可能触发检查，因为当前条件只判断 role，不区分 `NORMAL`、`INTERRUPTED`、`REJECTED` 状态。

### 9.6.1 为什么摘要只覆盖窗口的一部分

服务先取最近 `historyKeepTurns` 条 USER 作为轮次锚点，再选其中约一半位置为 `summaryCutoffId`。它只摘要上次 `lastMessageId` 之后、这个 cutoff 之前的消息。

这形成有重叠的滑动结构：

```text
更久历史 ──压成摘要──┐
                      ├─ 下一轮上下文
最近 8 轮原文 ────────┘
```

摘要不是每个 assistant 回答后都重写。只有旧摘要的覆盖边界已经滑出原文窗口，才生成下一代摘要，减少重复模型调用。

### 9.6.2 摘要 Prompt 的事实约束

生成请求使用 FAST 档、temperature 0.3、topP 0.9、thinking false。若已有摘要，会以 assistant 消息加入，并明确要求：

- 旧摘要仅用于合并去重；
- 不得作为新增事实来源；
- 与本轮对话冲突时以本轮为准；
- 输出不超过配置字符数，当前 400。

assistant 历史在摘要前也会先移除引用角标。若摘要模型调用失败，源码返回 existingSummary；整体摘要任务捕获异常并记录，不让它破坏已经完成的聊天消息。

### 9.6.3 摘要为什么仍不是“可靠事实库”

摘要由 LLM 生成，可能遗漏、抽象或失真。源码的 Prompt 约束只能降低风险，不能数学上保证无幻觉。项目因此仍保留原始消息表，并将摘要定位为上下文压缩产物。

面试中应说“摘要是有边界的记忆投影”，而不是“系统把历史永久无损记住”。

---

## 9.7 三份问题，各自服务不同阶段

进入查询改写时，系统至少同时保留：

| 名称 | 示例 | 用途 |
|---|---|---|
| 原始 `question` | “那它的退款和发票呢？” | USER 消息持久化、原始输入追踪 |
| `rewrittenQuestion` | “产品 A 的退款规则和发票开具规则是什么？” | 意图总判断、最终回答的主问题 |
| `subQuestions` | “产品 A 的退款规则是什么？”；“产品 A 如何开具发票？” | 分别做意图解析和检索 |

`RewriteResult` 只包含后两者，原始问题仍留在 `StreamChatContext.question`。不要把“改写”理解为覆盖数据库中的用户原话。

---

## 9.8 改写前先做术语归一化

`QueryTermMappingService.normalize` 从 Redis 缓存读取启用的术语映射；缓存未命中时查数据库并回填。规则排序以 priority 降序为主，同优先级时较长 source term 优先，减少短词先替换破坏长词的机会。

当前 normalize 只应用 `matchType=1` 的启用规则，经 `QueryTermMappingUtil` 做映射。例如企业内部缩写、产品别名可以先转换成统一名称，再交给 LLM 或规则拆分。

这一步和 LLM 改写职责不同：

- 术语表提供确定、可管理的领域映射；
- LLM 负责结合最近对话消解指代、补全主语和拆分复合问题。

---

## 9.9 改写开关打开时：小历史、低随机、JSON 契约

默认 `rag.query-rewrite.enabled=true`。`MultiQuestionRewriteService` 的流程是：

```text
术语归一化
    ↓
加载 user-question-rewrite.st
    ↓
SYSTEM prompt
+ 最近最多约 4 条 USER/ASSISTANT 历史
+ 当前归一化问题
    ↓
LLMService.chat(..., Tier.FAST)
    ↓
解析 JSON: rewrite + sub_questions
```

请求参数为 temperature 0.1、topP 0.3、thinking false，偏向稳定结构输出。

### 9.9.1 改写不会读取长期摘要

构造改写请求时，源码只保留 role 为 USER/ASSISTANT 的最近消息，并过滤 SYSTEM 摘要。注释明确这样做是为了避免 token 浪费。

因此：

- 最终回答 Prompt 可以收到“摘要 + 最近原文”；
- 查询改写只看最近 1～2 轮普通消息；
- 很久以前只存在摘要中的指代信息，不保证能被改写阶段利用。

这说明“记忆加载结果”不是每个阶段无差别使用。不同消费者会做自己的投影。

实现还有一个微妙细节：`skip` 的数量用原始 `history.size()` 计算，再作用到过滤 SYSTEM 后的流。存在一条 summary 时，实际可能保留 3 条而不是完整 4 条普通消息。因此更稳妥的表述是“最多约最近 4 条、1～2 轮”，不要承诺严格两轮。

### 9.9.2 输出解析与回退

系统先移除可能的 Markdown 代码围栏，再期待 JSON：

```json
{
  "rewrite": "完整、可独立理解的问题",
  "sub_questions": ["子问题一", "子问题二"]
}
```

规则是：

- 根不是对象、JSON 不合法或 `rewrite` 为空：解析失败；
- `rewrite` 有值但 `sub_questions` 为空：把 rewrite 自身作为唯一子问题；
- LLM 调用或解析失败：回退为“归一化问题 + 单一同名子问题”。

注意当前 enabled 分支失败时**不会再执行规则多问句拆分**，而是单问题回退。源码中 `rewriteAndSplit` 末尾有一条“规则拆分兜底”的注释，但真正控制流已经从 `callLLMRewriteAndSplit` 返回；不能把注释当作已执行分支。

---

## 9.10 改写开关关闭时：确定性规则路径

若 `rag.query-rewrite.enabled=false`：

1. 仍执行术语归一化；
2. 按 `?？。；;` 和换行拆分；
3. 去空白；
4. 给每个片段补问号；
5. 无有效片段时以完整归一化问题作为唯一子问题。

这条路径不调用 LLM，也不使用历史做指代消解。开关关闭不等于“原句完全不处理”，术语映射和规则拆分仍存在。

---

## 9.11 改写为什么不是最终答案生成

`rewriteWithSplit` 使用 FAST 档并只产出结构化查询，不访问知识库，也不把输出直接发给用户。下一阶段会对每个 `subQuestion` 做意图解析，再决定知识库 scope 和检索通道。

最终生成阶段则接收：

- `rewrittenQuestion` 作为主问题；
- `subQuestions` 帮助 Prompt 组织；
- 更完整的 history（含摘要）；
- 实际检索证据。

所以查询改写是“把问题变成检索计划的输入”，不是“让便宜模型先回答一遍”。

---

## 9.12 失败窗口和可观察结果

| 失败位置 | 当前行为 | 留下的状态 |
|---|---|---|
| 摘要读取失败 | 跳过摘要，继续读 recent history | 原消息仍在数据库 |
| history 读取失败 | 回退空历史 | 本轮按单轮问题处理 |
| 两者外层失败 | `load` 返回空列表 | 不直接阻断聊天 |
| 本轮 USER append 失败 | 异常继续抛出，Pipeline 中断 | 不能保证会话/USER 行存在 |
| USER 已保存，后续改写失败 | 改写内部回退归一化单问题 | USER 已是持久事实 |
| 摘要异步生成失败 | 记录错误，不影响已完成 assistant | 继续沿用旧摘要或无摘要 |
| assistant 完成时落库失败 | 第 8 章所述，仍可能发 DONE | 可能出现只有 USER 的持久历史 |

这张表解释了为什么会话消息不应被理解为“USER+assistant 永远成对事务提交”。长流程跨越模型、检索和 SSE，源码选择了逐阶段持久化与降级。

---

## 9.13 与 Agent 记忆不要混为一谈

本章讲的是确定性 RAG 的 `ConversationMemoryService`：PostgreSQL 消息 + 最近窗口 + 会话摘要。

ReAct Agent 在后续章节还有自己的 session/message/state、上下文压缩和长期记忆工具。即使两条路径都叫 memory，也不能推出：

- RAG 摘要能恢复 Agent 的工具循环；
- Agent state 就是 `t_message` 的另一种名字；
- 两边使用完全相同的窗口和摘要算法。

项目复用了 `ChatMessage` 等基础约定，但运行状态所有权是分开的。

---

## 9.14 责任边界与设计解读

| 组件 | 负责 | 不负责 |
|---|---|---|
| `StreamChatPipeline.loadMemory` | 固定“读旧历史→写本轮 USER→绑定 replyTo”顺序 | 不生成摘要内容 |
| `DefaultConversationMemoryService` | 并行加载、降级、合并、append 后触发压缩 | 不决定数据库 SQL 细节 |
| `JdbcConversationMemoryStore` | recent history 和消息持久化投影 | 不保存运行中 task |
| `JdbcConversationMemorySummaryService` | 异步、加锁、增量摘要和包装 | 不替代原消息事实 |
| `QueryTermMappingService` | 确定性领域术语统一 | 不消解长对话指代 |
| `MultiQuestionRewriteService` | 归一化、历史投影、LLM/规则改写与拆分 | 不检索、不回答 |

从结构可以推断：

- USER 先落库使拒绝以外的正常主线也能保留用户意图，但接受了“孤立 USER”可能性；
- 摘要和原文重叠可以平滑滑窗切换，减少刚被压缩的信息瞬间消失；
- 改写只取极短 recent history 可以控制成本和主题漂移，但牺牲了对很久以前指代的解析能力；
- 术语映射放在 LLM 前能把确定规则与概率推理分开。

---

## 9.15 面试追问与回答骨架

### 问：项目如何实现多轮对话记忆？

原始消息持久化在 `t_message`，每轮加载最近 8 轮 USER/ASSISTANT；第 9 个 USER 轮次后，assistant append 会异步检查并增量生成最长 400 字的 `t_conversation_summary`。最终历史是 SYSTEM 摘要加最近原文，加载任一部分失败可降级。

### 问：为什么查询改写不把全部历史都给模型？

改写只需消解最近指代并形成检索问题。源码过滤 SYSTEM 摘要并最多保留约 4 条普通消息，以控制 token、延迟和旧话题干扰；最终回答阶段才使用更完整历史。

### 问：查询改写失败会不会导致整次问答失败？

通常不会。LLM 调用或 JSON 解析失败时回退为术语归一化后的问题，并把它作为唯一子问题。只有更早的本轮 USER 持久化等未在改写内部捕获的异常才会中断 Pipeline。

### 问：为什么原问题、改写问题和子问题都要保留？

原问题是用户事实；改写问题补全上下文，适合作为最终主问题；子问题让意图与检索可以分别处理复合需求。覆盖原句会损失审计和真实表达，只保留原句又会让“那它呢”无法独立检索。

### 问：摘要能否保证无损？

不能。它由 FAST 档 LLM 生成，Prompt 要求不新增事实并保留原消息表，但依旧是有损投影。系统通过保留 recent 原文和持久原始消息降低风险，而不是宣称摘要就是事实库。

### 问：关闭 query rewrite 后系统是否原样检索？

不是。仍先做术语映射，再按中英文问号、句号、分号和换行做规则拆分，只是不再使用 LLM 和历史做语义改写。

---

## 9.16 源码定位卡

- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/pipeline/StreamChatPipeline.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/pipeline/StreamChatContext.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/memory/ConversationMemoryService.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/memory/DefaultConversationMemoryService.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/memory/JdbcConversationMemoryStore.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/memory/JdbcConversationMemorySummaryService.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/impl/ConversationServiceImpl.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/impl/ConversationMessageServiceImpl.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/config/MemoryProperties.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/rewrite/QueryTermMappingService.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/rewrite/MultiQuestionRewriteService.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/rewrite/RewriteResult.java`
- `rag/src/main/resources/prompt/user-question-rewrite.st`
- `bootstrap/src/main/resources/application.yaml`
- `resources/database/schema_pg.sql`

---

## 9.17 读完本章，你应该能自己回答

1. 为什么主 Pipeline 先 load history，再 append 本轮 USER？
2. `t_conversation`、`t_message`、`t_conversation_summary` 各持有什么事实？
3. 最近 8 轮和 400 字摘要怎样组合？摘要何时异步更新？
4. 为什么旧 assistant 回答进入历史前要去掉引用角标？
5. 原始问题、改写问题、子问题在后续分别怎样使用？
6. 改写开关打开和关闭时，失败回退有什么差异？
7. 为什么长期摘要不会被当前查询改写模型读取，却会进入最终回答上下文？

下一章将接住 `RewriteResult`：每个子问题怎样落到意图树，何时直接系统回答，何时提示用户澄清，以及知识库 scope 怎样从评分中算出来。
