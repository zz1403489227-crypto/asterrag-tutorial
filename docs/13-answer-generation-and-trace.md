# 第 13 章：证据怎样变成答案——来源、Prompt、模型路由与流式收尾

> 第 12 章结束时，系统手里已经有一批经过后处理的证据。但这批 `RetrievedChunk` 还不是用户看到的回答：它既要变成模型可读的上下文，又要变成用户可追溯的来源，还要留下后续推荐问题所需的 grounding，最后才通过模型路由和 SSE 收尾形成一条 assistant 消息。
>
> 本章沿 `StreamChatPipeline#streamRagResponse` 的真实顺序，把这四条输出解释清楚。重点不是背 Prompt 文案，而是理解同一批证据在不同消费者之间怎样分流、编号和持久化。

## 13.1 先看完整闭环

`streamRagResponse` 的主干可以压缩为：

```text
RewriteResult + RetrievalContext + IntentGroup + history
                       │
                       ├─ intentChunks ──> SourcesAssembler ──> sources
                       │                         │
                       │                         └─ 给 KB 上下文注入 ref 编号
                       │
                       ├─ intentChunks ──> GroundingChunksAssembler ──> grounding
                       │
                       └─ kbContext / mcpContext
                                  │
                                  ▼
                    RAGPromptService.buildStructuredMessages
                                  │
                                  ▼
                         ChatRequest + 模型路由
                                  │
                    thinking/content/complete/error
                                  │
                                  ▼
                StreamChatEventHandler + StreamChatTraceRunner
                                  │
             SSE 事件 / assistant 消息 / Trace 终态
```

这里最重要的认识是：`sources`、`grounding` 和 `kbContext` 都由最终知识库证据派生，但不是同一种数据，也不去同一个地方。

| 派生物 | 主要内容 | 主要消费者 | 是否进入本轮回答 Prompt |
|---|---|---|---|
| `kbContext` | 最终 Chunk 正文、意图规则、引用编号 | 回答模型 | 是 |
| `sources` | 文档级名称、类型、链接、100字摘录、编号 | 前端来源面板、完成事件、消息持久化 | 编号会进入；来源对象本身不作为消息列表单独传入 |
| `groundingChunks` | 每篇文档最高分 Chunk 全文，最多8篇 | assistant 消息、后续推荐追问生成器 | 否 |
| `mcpContext` | 动态工具结果及工具规则 | 回答模型 | 是，但不生成文档引用编号 |

因此不能把“来源”“检索上下文”“推荐追问 grounding”当成三个字段名不同、内容相同的副本。

---

## 13.2 来源编号只建立一次

`SourcesAssembler.assemble(intentChunks)` 把意图下的 KB Chunk 扁平化，然后：

1. 过滤没有 `docId` 的 Chunk；
2. 按 `docId` 去重，每篇文档只保留最高 `score` 的 Chunk；
3. 按每篇文档最高分降序排列，分数相同再按 `docId`；
4. 批量查询 `KnowledgeDocumentDO`；
5. 从1开始依次赋予 `SourceRef.index`；
6. 生成文档名、来源类型、文件类型、外链和最多100字符的摘录。

于是同一文档即使贡献多个 Chunk，也只在来源面板出现一次：

```text
doc-A / chunk-2 / score 0.83
doc-A / chunk-7 / score 0.72   ──> SourceRef(index=1, docId=doc-A, excerpt=chunk-2前100字)
doc-B / chunk-1 / score 0.76   ──> SourceRef(index=2, docId=doc-B, excerpt=chunk-1前100字)
```

### 13.2.1 来源对象为什么是文档级

模型回答可能综合同一文档的多个相邻 Chunk；如果每个 Chunk 都成为一条来源，前端会出现大量重复文档。当前实现让 Chunk 负责提供正文，让 `SourceRef` 负责用户可理解的文档入口。

其中外链有明确边界：只有 `sourceType=url` 或 `feishu` 时才把 `sourceLocation` 暴露为 `url`；普通文件来源依靠 `docId` 走项目内部的预览路径。

### 13.2.2 MCP 结果不进入这套编号

`SourcesAssembler` 的输入是 `retrievalCtx.intentChunks`，这里承载 KB Chunk，不是 MCP `CallToolResult`。因此动态工具结果可以进入 Prompt，但不会被伪装成知识文档来源。引用规则模板也明确要求：混合场景的数字引用只用于带编号的知识资料。

---

## 13.3 引用编号怎样进入模型上下文

第 12 章的最终 Chunk 在 `DefaultContextFormatter` 中先按文档分组。每篇文档被渲染为一个内部块：

```text
<content data-ragent-doc-id="doc-A">
该文档命中的若干 Chunk 正文……
</content>
```

这里故意不放文档标题。源码注释给出的原因是：标题进入 Prompt 后，模型容易在正文里输出“出自《某某文档》”；当前交互希望模型只写数字角标，而文档名留在来源面板。

`CitationContextEnricher.enrich(kbContext, sources)` 随后依据唯一的 `SourceRef.index` 做替换：

```text
data-ragent-doc-id="doc-A"  ──>  ref="1"
data-ragent-doc-id="doc-B"  ──>  ref="2"
```

所以 Prompt、完成事件、落库来源和前端面板复用同一套编号，不需要四个消费者各自排序。

### 13.3.1 引用开关关闭，不等于跳过 Enricher

当 `rag.citation-enabled=false` 时，Enricher 不注入 `ref`，但仍会移除 `data-ragent-doc-id`：

```text
<content data-ragent-doc-id="doc-A">  ──>  <content>
```

这一步是信息边界，不只是显示功能。内部文档 ID 无论引用开关如何都不应进入模型可见文本。

与此同时，`RAGPromptService` 只有在三个条件同时成立时才拼接引用规则：

```text
调用方允许 citation
AND PromptContext 中存在 KB 上下文
AND rag.citation-enabled=true
```

Agent 的知识检索门面没有来源编号渲染能力，会显式以 `citationEligible=false` 构造消息，并使用 `stripDocIdAnchors`。第 15 章会再解释这条共享边界。

### 13.3.2 引用规则约束的是输出格式

当前 `answer-citation-rules.st` 要求模型把编号输出为：

```markdown
[1](#cite-1)
```

并要求角标紧跟被支撑的段落、列表项或表格单元格，不允许另列来源清单，也不允许引用不存在的编号。前端再用 `#cite-N` 和完成事件中的 `sources[index=N]` 建立交互。

这仍是 Prompt 约束，而不是生成后的强制引用校验器。当前这条生成链没有在模型输出后解析每个角标并证明其陈述真的由对应文档支撑，因此面试中不能把它表述为“系统已做逐句事实验证”。

---

## 13.4 Grounding 是给下一步用的，不参加本轮回答

`GroundingChunksAssembler` 同样读取 `intentChunks`，但输出目标不同：

1. 只保留有 `docId` 且正文非空的 Chunk；
2. 每篇文档保留最高分 Chunk；
3. 按分数降序取最多8篇；
4. 保存 `docName + 完整 Chunk text`。

随后 Pipeline 调用：

```java
callback.onGroundingChunks(...)
```

它没有把 grounding 塞进 `PromptContext`。`StreamChatEventHandler` 只是暂存它，并在正常完成或已有正文的取消场景中把它写进 assistant 消息的 `retrievedChunks` 字段，供 `RecommendedQuestionGenerator` 后续生成推荐追问。

这形成了一个清晰的数据流：

```text
本轮最终证据
   ├─ kbContext ──> 本轮回答模型
   └─ grounding ──> 本轮 assistant 消息 ──> 后续推荐问题模型
```

如果把 grounding 也再次放进本轮 Prompt，同一证据会重复占用上下文。当前实现用“现在回答”和“回答后推荐”两个消费时点分离它们。

---

## 13.5 Prompt 不是字符串拼接，而是一组有角色的消息

`RAGPromptService.buildStructuredMessages` 的实际顺序是：

```text
1. system：场景模板 + 可选引用规则
2. history：记忆服务返回的摘要与历史消息
3. user：MCP证据 + KB证据 + 改写后的问题/子问题
```

注意，证据不是独立 `system` 消息，而是和当前问题合并成最后一条 `user` 消息。发给 OpenAI 风格端点时，每个 `ChatMessage.Role` 再被翻译为 `system/user/assistant`。

### 13.5.1 三种证据场景怎样选模板

| 场景 | 模板选择 |
|---|---|
| 只有 KB | 只有一个可用意图且节点有 `promptTemplate` 时用节点模板，否则用 KB 默认回答模板 |
| 只有 MCP | 只有一个 MCP 意图且节点有 `promptTemplate` 时用节点模板，否则用 MCP 默认回答模板 |
| KB + MCP | 使用 Mixed 默认回答模板，不套某个单节点模板 |

KB 的“单意图”判断只看 `eligibleIntentIds` 中的意图。也就是说，一个意图虽然被分类为候选，但其检索资格没有建立时，不会仅凭存在于候选列表就控制最终回答模板。

如果既没有 KB 也没有 MCP，上游 `handleEmptyRetrieval` 已经短路输出固定提示；`RAGPromptService.plan` 本身也会对空上下文抛 `IllegalStateException`。两层职责并不相同：Pipeline 负责业务短路，PromptService 负责拒绝非法调用状态。

### 13.5.2 单问题与多问题的最后一条 user 消息

`RewriteResult.subQuestions` 多于1条时，Prompt 以编号形式列出多个子问题；否则使用改写后的单问题。上下文也在第 11 章所述的子问题检索阶段分别构造，再由 `RetrievalEngine` 加 wrapper 合并。

因此模型看到的是“改写/拆分后的检索问题”，而原始用户问题已经作为用户消息先写入持久化记忆。不要把“落库原问题”和“本轮模型最后一条 user 内容”混为一谈。

### 13.5.3 `promptSnippet` 与 `promptTemplate` 不同

- `promptTemplate`：可能替换整个场景级 system Prompt；
- `promptSnippet`：由 `DefaultContextFormatter` 放入证据侧 `<rules>`，和 Chunk 正文一起进入最后一条 user 消息；
- 全局 citation rules：只有满足引用条件才追加到 system Prompt。

这三类配置处于不同层次。面试中说“意图节点能配置 Prompt”还不够，最好说明它究竟覆盖场景模板，还是只注入该意图的回答规则。

---

## 13.6 MCP 场景为什么使用另一组采样参数

Pipeline 构造 RAG `ChatRequest` 时使用：

```text
纯 KB：temperature=0.0，topP=1.0
含 MCP：temperature=0.3，topP=0.8
thinking：等于用户的 deepThinking 开关
```

源码注释只明确写了“MCP 场景稍微放宽温度”。可以从实现解读：纯文档问答偏确定性；工具数据混合回答允许略微增加表达弹性。但这只是参数与合理作用的解释，不能杜撰成作者做过对照实验后得到的质量最优组合。

还有一个容易混淆的分支：`SYSTEM_ONLY` 意图不走这组参数，而是走 `streamSystemResponse`，固定 `temperature=0.7`、`thinking=false`，且不执行知识检索。

---

## 13.7 模型路由先选“档位”，再选具体模型

`RoutingLLMService.streamChat` 首先调用：

```java
selector.selectChatCandidates(request.thinking == true)
```

当前配置的默认规则是：

```text
thinking=false  ──> standard tier
                 qwen3-max → qwen-plus → qwen3-local → gpt-5.4

thinking=true   ──> deep tier
                 qwen3-max → deepseekv4pro
```

深度思考请求会过滤 `supportsThinking!=true` 的模型。`fast` 档位虽然存在，但这个无显式 Tier 参数的 RAG 流式入口不会自动选择 fast；它服务于传入 Tier override 的其他调用点。

每个 tier 还带首包等待预算：standard 120秒，deep 180秒，fast 5秒。这里的 budget 在流式路径中用于等待首个 thinking/content，而不是允许整个回答只运行这么久。外层 SSE 还有自己的全局超时，两者不应混称为同一个超时。

---

## 13.8 为什么 fallback 必须等到首包再“提交”

如果模型调用刚返回取消句柄就立即认定成功，会出现这种情况：首选模型连接建立后一直没有任何 token，系统已经失去切换机会。当前实现用 `ProbeStreamBridge` 在下游回调前加了一层缓冲：

```text
候选模型启动
   │
   ├─ 收到 thinking 或 content ──> SUCCESS ──> commit 缓冲 ──> 用户开始收到流
   ├─ 首包前 onError          ──> ERROR   ──> cancel ──> 下一个模型
   ├─ 等待超时                ──> TIMEOUT ──> cancel ──> 下一个模型
   └─ 未产生内容就 onComplete ──> NO_CONTENT ──> cancel ──> 下一个模型
```

缓冲的价值是防止失败候选先向用户泄露一段内容，再换模型从头回答。只有探测结果为 SUCCESS 时，已缓存事件才统一提交；失败候选的 error/complete 也不会发给最终 callback。

### 13.8.1 首包以后不再 fallback

`RoutingLLMService` 在第一个 thinking 或 content 到达后立刻 `markSuccess` 并返回当前取消句柄。之后如果同一个 provider 在回答中途断流，错误会沿 callback 送给当前 SSE，而不会回到候选循环切下一个模型。

这是必要的用户语义边界：已经把前半段回答展示给用户后，再让另一模型从头输出会拼成两份互相冲突的文本。当前 fallback 保障的是“首包前可替换”，不是“任意时刻无缝续写”。

同理，模型健康状态在此时记为 success；成功首包后的中途错误没有再经过路由器的 `markFailure` 分支。面试中不要把熔断描述成对整个流式答案质量和完整性的全程统计。

### 13.8.2 所有候选失败

每个失败候选都会被取消并标记 failure。循环耗尽后，路由器构造统一的“所有模型失败”异常，先调用下游 `callback.onError`，再把异常抛给调用者。

`ForwardingStreamCallback` 和 EventHandler 的终态防护需要避免重复收尾；从责任上看，模型路由只负责宣布模型侧失败，SSE/消息/Trace 各自通过 callback 完成收尾。

---

## 13.9 熔断器屏蔽的是暂时不健康的候选

`ModelHealthStore` 是进程内 `ConcurrentHashMap`，每个模型经历：

```text
CLOSED
  └─ 连续失败达到2次 ──> OPEN 30秒
                            └─ 到期后一次探测 ──> HALF_OPEN
                                   ├─ 成功 ──> CLOSED
                                   └─ 失败 ──> OPEN 30秒
```

`HALF_OPEN` 同时只放一个探测调用。`ModelSelector` 在组装候选时会跳过仍 OPEN 或已有 half-open probe 的模型，`allowCall` 在真正调用前再做一次许可判断。

这套状态没有持久化，也没有跨节点共享。因此在多实例部署中，一个实例把某模型熔断，不代表其他实例立即知道。它解决的是单进程对失败 provider 的短时自我保护，不是全局服务治理中心。

---

## 13.10 思考流与正文流是两条可见通道

OpenAI 风格 SSE parser 把 provider 增量拆为：

```text
reasoning  ──> callback.onThinking
content    ──> callback.onContent
完成标志   ──> callback.onComplete
```

`StreamChatEventHandler` 分别累积 `thinking` 与 `answer`，并通过同一种 `message` SSE 事件发送不同 type：

```text
type=think
type=response
```

当前 `ai.stream.message-chunk-size=1`，EventHandler 按 Unicode code point 重新分块，因此不会把一个增补字符拆成两个 UTF-16 surrogate。分块大小是应用向前端发送的粒度，不是 provider 原始 token 粒度。

思考耗时从第一段 thinking 到第一段正文 content 计算，并至少记1秒。若模型没有 thinking，或没有进入“思考后正文”形态，该字段可能为空。

---

## 13.11 正常、取消与错误不是同一种终态

### 13.11.1 正常完成

`onComplete` 会组装 assistant 消息：

```text
content = 累积正文
thinking = 累积思考（可空）
thinkingDuration
sources
retrievedChunks = groundingChunks
replyToMessageId
messageStatus = NORMAL
```

消息写入后发送：

```text
finish {messageId, title, sources, NORMAL}
done   [DONE]
```

然后注销 task 并完成 emitter。若 assistant 消息持久化本身失败，EventHandler 记录错误，但仍发送 finish/done；此时完成载荷里的 `messageId` 为空。由此可见，“前端收到 DONE”和“assistant 消息一定已成功落库”不是等价命题。

### 13.11.2 用户取消

取消时，如果已经积累了非空正文，EventHandler 尝试保存 `INTERRUPTED` assistant 消息，同样带 thinking、sources、grounding 和 replyTo；然后发送：

```text
cancel {..., status=INTERRUPTED}
done   [DONE]
```

若还没有正文，则不创建 assistant 消息。底层已绑定的模型取消句柄会被调用，provider stream span 也走 cancelled 收尾。

### 13.11.3 流式错误

`onError` 的当前路径是注销 task 并 `sender.fail(error)`。它不会像取消分支那样把已积累正文保存成一条 `INTERRUPTED` 消息，也不会发正常 `finish/done`。

因此三种终态的可恢复语义不同：正常答案是 `NORMAL`，用户主动停止可留下 `INTERRUPTED`，模型/网络错误当前不保证保存半截 assistant。第 8 章已经从 SSE 角度解释过事件序列，本章要记住它们还对应不同的持久化行为。

---

## 13.12 Trace 同时测三种“时间”

`StreamChatTraceRunner` 在 Pipeline 之前创建一个 `rag-stream-chat` run，记录 conversationId、taskId、userId、入口方法、问题和问题长度。随后把 traceId/taskId 放入上下文，供带 `@RagTraceNode` 的改写、意图、检索和模型路由节点关联。

流式场景还需要三个不同概念：

| Trace | 起止 | 它回答的问题 |
|---|---|---|
| `llm-first-packet` | 等待某候选的第一段 thinking 或 content | 当前模型多久证明自己能开始输出 |
| `user-first-packet` | 整个 run 开始到第一个 `onContent` | 用户多久看到第一段正文 |
| `provider-stream-chat` span | provider 流启动到 complete/error/cancel | 这次 provider 流实际持续多久 |

这三个值不能互相替代。尤其是深度思考模型可能很快返回 thinking，因此 LLM first packet 已成功，但用户正文 TTFT 仍然较长。

### 13.12.1 为什么用户首包不在普通 AOP 方法里测

普通 AOP 只能包住同步方法返回。`RoutingLLMService.streamChat` 在首包确认后就返回取消句柄，而实际正文继续在异步线程产生。`ForwardingStreamCallback` 因此在第一次 `onContent` 时单独写 `user-first-packet` 节点；provider 则用显式 `StreamSpan` 跨线程等到真正终态。

### 13.12.2 Run 怎样收尾

Trace callback 用 CAS 保证 `onComplete` 或 `onError` 只把 run 收尾一次：

```text
onComplete ──> run SUCCESS
onError    ──> run ERROR + 截断后的异常
```

Trace 写入失败只记录告警，不应该反向破坏用户回答流。这体现了观测旁路的职责边界。

需要准确说明一个当前源码边界：用户取消由 `StreamTaskManager` 注册的 EventHandler cancel hook 和底层模型 handle 完成；在本章检查到的显式调用链中，没有看到它调用 trace-aware callback 的 `onComplete/onError`。所以可以确认 provider span 有 cancel 收尾，但不应进一步声称顶层 `rag-stream-chat` run 在所有取消场景都一定被标成终态。这里是源码观察，不把未出现的调用补写成事实。

---

## 13.13 同一批证据的四种身份

现在可以把本章主线再压缩一次：

```text
RetrievedChunk
   │
   ├─ 正文 + 意图规则 ──> kbContext ──> 回答模型
   │
   ├─ 每文档最佳块 ──> SourceRef ──> 编号/面板/完成事件/消息
   │
   ├─ 每文档最佳块全文 ──> GroundingChunk ──> 消息/推荐追问
   │
   └─ 分数与文档归属 ──> 决定上述排序和去重
```

数据来自同一批证据，但每个投影只保留消费者真正需要的部分。这比把完整检索对象原样塞进 Prompt、SSE 和数据库更容易维持安全边界与演进兼容性。

---

## 13.14 责任边界与设计解读

| 组件 | 负责 | 不负责 |
|---|---|---|
| `SourcesAssembler` | 文档级去重、排序、编号、来源元数据 | 不生成模型回答，不处理 MCP 来源 |
| `CitationContextEnricher` | 注入同源编号、始终移除内部 docId | 不验证模型引用是否事实正确 |
| `GroundingChunksAssembler` | 选择最多8篇后续推荐用证据 | 不参与本轮 Prompt |
| `RAGPromptService` | 场景模板、引用规则、消息角色和证据/问题布局 | 不执行检索，不调用模型 |
| `ModelSelector` | 按 thinking/tier/健康状态产生候选 | 不处理流式事件 |
| `RoutingLLMService` | 首包前 fallback、健康标记、返回取消句柄 | 首包后不跨模型续写 |
| `StreamChatEventHandler` | thinking/content 累积、SSE、消息终态 | 不决定模型候选 |
| `StreamChatTraceRunner` | run、用户正文首包、正常/error 收尾 | Trace 失败不应影响业务流 |

从实现可以解读：

- 来源编号先统一建立，再反向注入 Prompt，避免用户面板和模型角标错位；
- internal docId 即使关闭引用也会清理，显示开关没有破坏信息边界；
- 首包前缓冲让 fallback 对用户保持原子性；
- 首包成功和完整回答成功被明确分开，避免承诺不可能的“流中无缝换模型”；
- Trace 用 callback/span 延长观测生命周期，解决同步 AOP 覆盖不了异步流的问题。

---

## 13.15 面试追问与回答骨架

### 问：为什么来源编号不在格式化 KB Context 时直接生成？

因为编号的唯一真源是文档级 `SourceRef` 列表。先按文档最高分去重排序，再把编号注回上下文，能保证 Prompt 角标、来源面板、完成事件和消息落库一致。

### 问：关闭引用后会不会把内部 docId 发给模型？

不会。关闭只是不注入 `ref` 和引用规则，`CitationContextEnricher` 仍把 `data-ragent-doc-id` 清理成普通 `<content>` 标签。

### 问：sources 和 grounding 有什么区别？

sources 是文档级用户来源，带编号、类型、链接和100字摘录；grounding 是最多8篇文档的最高分 Chunk 全文，随 assistant 消息保存，供后续推荐追问。grounding 不进入本轮回答 Prompt。

### 问：最终发给模型的消息顺序是什么？

system 场景模板及可选引用规则，接着是 memory 返回的历史/摘要，最后是一条 user 消息，其中合并 MCP证据、KB证据和改写后的单问题或多子问题。

### 问：深度思考只是给同一个模型加参数吗？

不只是。`thinking=true` 会选择 deep tier，并过滤掉 `supportsThinking!=true` 的候选；当前 deep 候选是 qwen3-max 和 deepseekv4pro。请求参数也把 thinking 传给 provider 客户端。

### 问：流式 fallback 在什么时间点还能发生？

只在首包提交前。首个 thinking/content、首包前 error、timeout、无内容 complete 决定候选是否提交。一旦首包成功并发给用户，后续中途错误直接结束当前流，不再切模型拼接另一份回答。

### 问：模型首包 TTFT 和用户首字 TTFT 为什么不同？

模型首包把 thinking 或 content 都视为成功；用户首包节点只在第一段正文 `onContent` 时记录，并且从整个 Pipeline 开始计时。深度思考会扩大两者差距。

### 问：收到 DONE 是否证明消息落库成功？

不能。正常完成时 assistant 持久化异常会被记录，但 EventHandler 仍发送 finish/done，完成载荷的 messageId 可能为空。运行事件和持久化结果必须分别判断。

### 问：熔断状态是否跨实例共享？

不是。`ModelHealthStore` 是进程内 Map，失败2次后本实例 OPEN 30秒，到期只放一个 HALF_OPEN probe；其他实例维护自己的状态。

---

## 13.16 源码定位卡

- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/pipeline/StreamChatPipeline.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/retrieval/RetrievalEngine.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/source/SourcesAssembler.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/source/CitationContextEnricher.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/source/GroundingChunksAssembler.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/prompt/DefaultContextFormatter.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/core/prompt/RAGPromptService.java`
- `rag/src/main/resources/prompt/context-format.st`
- `rag/src/main/resources/prompt/answer-citation-rules.st`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/model/ModelSelector.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/model/ModelHealthStore.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/chat/RoutingLLMService.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/chat/ProbeStreamBridge.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/chat/AbstractOpenAIStyleChatClient.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/chat/ForwardingStreamCallback.java`
- `infra-ai/src/main/java/com/nageoffer/ai/ragent/infra/chat/StreamSpanCallback.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/service/handler/StreamChatEventHandler.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/trace/StreamChatTraceRunner.java`
- `rag/src/main/java/com/nageoffer/ai/ragent/rag/trace/RagStreamTraceSupportImpl.java`
- `framework/src/main/java/com/nageoffer/ai/ragent/framework/trace/RagStreamTraceSupport.java`
- `bootstrap/src/main/resources/application.yaml`

---

## 13.17 读完本章，你应该能自己回答

1. 一批最终 Chunk 怎样分别变成 `kbContext`、`sources` 和 `grounding`？
2. 来源编号为什么能同时对齐 Prompt 和前端面板？
3. citation disabled 时仍必须执行哪一步清理？
4. structured messages 的真实角色顺序是什么？
5. KB-only、MCP-only、Mixed 怎样选择 system template？
6. `thinking=true` 怎样同时改变模型候选和输出事件？
7. `ProbeStreamBridge` 为什么先缓冲，再 commit？
8. 首包前失败与首包后失败的 fallback 语义有何不同？
9. NORMAL、INTERRUPTED、error 三条终态分别怎样保存消息？
10. `llm-first-packet`、`user-first-packet` 和 provider stream span 分别测什么？

到这里，确定性 RAG 的闭环已经完整：问题经过记忆、改写、意图、检索、后处理、Prompt、模型和事件收尾，最终形成可展示、可追溯的回答。下一章转向另一条主链：既然固定 Pipeline 已经能回答知识问题，项目为什么还需要 ReAct Agent？
