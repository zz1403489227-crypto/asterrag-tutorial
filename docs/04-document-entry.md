# 第 4 章：文档从哪里来——上传、远程来源、定时刷新与并发保护

> 本章只回答“原始文档如何进入系统”。文档怎样解析、分块和建索引，分别留给第 5～7 章。

## 4.1 你现在位于总体图的哪里

第 3 章建立了文档、Chunk、向量和对象文件的状态边界。本章从知识生产线最左侧开始：

```text
本地文件 / 远程 URL
        ↓
UploadRateLimitFilter
        ↓
KnowledgeDocumentController.upload
        ↓
KnowledgeDocumentServiceImpl.upload
        ├─→ 对象存储：保存原文件
        └─→ PostgreSQL：保存 PENDING 文档元数据
```

这条链路的输出是“系统已经知道有这份文档”，不是“这份文档已经可检索”。

## 4.2 先记住一个结论：上传和摄取是两个动作

`KnowledgeDocumentController` 故意提供两个接口：

| 接口 | 责任 | 成功后的核心状态 |
|---|---|---|
| `POST /knowledge-base/{kb-id}/docs/upload` | 收到文件或 URL，保存原文件和文档元数据 | `PENDING`、`chunkCount=0` |
| `POST /knowledge-base/docs/{doc-id}/chunk` | 发起后续解析、分块、Embedding 和索引替换 | 先进入 `RUNNING`，后台收尾为 `SUCCESS` 或 `FAILED` |

这个拆分解决了一个实际问题：用户可以先创建文档记录，选择摄取参数，再显式启动重处理。同时，它也带来一个面试时必须说清的边界：

> “上传成功”基本可以理解为原文件和元数据已经进入系统，但不能完全等同于文档已被解析，更不能等同于已经能被 RAG 召回。

## 4.3 本地文件上传的完整调用链

### 4.3.1 第一道门：在 multipart 解析前限制并发

`UploadRateLimitFilter` 的优先级是 `Ordered.HIGHEST_PRECEDENCE`。它只拦截同时满足三个条件的请求：

1. HTTP 方法是 `POST`；
2. URI 包含 `/knowledge-base/`；
3. URI 以 `/docs/upload` 结尾。

它从 Redisson 的 `RPermitExpirableSemaphore` 申请一个带租约的许可。默认 YAML 配置是：

```yaml
ragent:
  semaphore:
    document-upload:
      name: rag:document:upload
      max-concurrent: 10
      max-wait-seconds: 5
      lease-seconds: 300
```

申请不到许可时，Filter 直接返回 HTTP 429，不继续调用 `chain.doFilter`。这个位置很重要：它在大文件被 multipart 完整解析、甚至可能产生临时文件之前就拒绝过量请求。

`SemaphoreInitializer` 在启动时把最大许可数写入同名信号量。Filter 在 `finally` 中尝试释放许可；如果租约已过期或许可已被释放，只记录告警。

### 4.3.2 Controller 不做重处理

`KnowledgeDocumentController.upload` 只做 HTTP 参数绑定：

- `kb-id` 来自路径；
- `file` 是可选 multipart 部分；
- 其他字段通过 `KnowledgeDocumentUploadRequest` 接收。

“文件可选”不是说本地文件模式可以没文件，而是同一个接口还支持 URL 来源。Service 会根据 `sourceType` 做真正的分支校验。

### 4.3.3 Service 按“先纯校验，后副作用”的顺序执行

`KnowledgeDocumentServiceImpl.upload` 的顺序不是随意排列：

```text
1. 查询知识库
2. 规范化 sourceType
3. 校验 URL / 定时配置
4. 校验 processMode / ingestionSpec / pipelineId
5. 上传本地文件，或拉取 URL 后写入对象存储
6. 用 ParserRegistry.canParse 检查 MIME 是否有解析路由
7. 插入 KnowledgeDocumentDO，状态=PENDING，chunkCount=0
8. 返回 KnowledgeDocumentVO
```

第 4 步被明确放在第一个外部副作用之前。如果摄取配置根本不合法，系统不应先上传对象，再留下没有文档引用的孤儿文件。

对象写入后，Service 用存储结果中的 MIME 询问 `ParserRegistry.canParse`。无解析器时，它会删除刚写入的对象再抛错，不创建文档行。

最后插入的 `KnowledgeDocumentDO` 同时保存两类信息：

| 类别 | 代表字段 | 含义 |
|---|---|---|
| 对象与展示 | `fileUrl`、`docName`、`fileType`、`fileSize` | 原文件在哪里、前端怎样展示 |
| 解析路由 | `mimeType` | 后续应选哪类解析器；摄取时还会用真实字节重新探测 |
| 来源 | `sourceType`、`sourceLocation` | 本地文件还是 URL；URL 时保留来源地址 |
| 定时刷新 | `scheduleEnabled`、`scheduleCron` | 只对 URL 来源有意义 |
| 处理选择 | `processMode`、`ingestionSpec`、`pipelineId` | 后续直接分块的规范化参数，或 Pipeline 标识 |
| 当前生命周期 | `status=PENDING`、`chunkCount=0` | 还未完成摄取 |

## 4.4 URL 来源不是“数据库里存一个网址”

URL 来源也会在创建文档时把内容拉取到自己的对象存储。`resolveStoredFile` 对本地文件调用 `FileStorageService.upload`，对 URL 则调用 `RemoteFileFetcher.fetchAndStore`。

`fetchAndStore` 分两段限制大小：

1. 尽量先发 HEAD，如果服务器给出 `Content-Length`，可以提前拒绝超限文件；
2. 真正 GET 时仍流式统计字节，不相信 HEAD 一定准确。

HEAD 失败不会终止导入，代码会直接转入 GET。GET 的响应流先被复制到临时文件，再用“实际读到的字节数”上传对象存储，最后在 `finally` 中删除临时文件。

这里有两个不能混淆的概念：

| 概念 | 作用 |
|---|---|
| `sourceLocation` | 记住远程来源，便于以后重新拉取 |
| `fileUrl` | 指向系统自己已经保存的当前原文件副本 |

所以，URL 模式不是每次分块都直接读外网 URL；普通摄取会从已保存的 `fileUrl` 打开输入流。

## 4.5 定时刷新的核心不是 Cron，而是“何时切换当前文件”

只有 URL 来源才能启用定时刷新。创建时必须提供合法 Cron，且周期不能短于 `ragent.knowledge.schedule.min-interval-seconds`，默认是 60 秒。

### 4.5.1 变更检测有三层

`RemoteFileFetcher.fetchIfChanged` 按以下顺序判断：

1. HEAD 同时拿到新旧 ETag 时，优先比较 ETag；
2. ETag 不可比时，如果新的 `Last-Modified` 与上次一致，直接认为未变；
3. 仍不能确定时，GET 下载并计算 SHA-256，与上次 `contentHash` 比较。

注意，这不是 HTTP 304 流程。代码没有构造 `If-None-Match` 或 `If-Modified-Since` 条件 GET，而是自己做 HEAD 标识比较，必要时再下载比较内容哈希。

### 4.5.2 `ScheduleRefreshProcessor` 是一个显式的阶段机

这个类将一次刷新的关键阶段写成内部枚举：

```text
INIT
  → DOC_OCCUPIED
  → CHUNK_STARTED
  → CHUNK_COMPLETED
  → FILE_SWITCHED
```

其正常路径是：

1. 确认自己仍持有调度锁，启动锁心跳；
2. 读取调度、文档和知识库，过期、删除、禁用或非 URL 来源会结束本次任务；
3. 创建一条 `RUNNING` 的调度执行记录；
4. 检查远程内容是否改变，未变则记为跳过；
5. 通过 CAS 式状态更新争抢文档的运行权，进入 `DOC_OCCUPIED`；
6. 把新文件写入对象存储，但还不立即把数据库的 `fileUrl` 切到新文件；
7. 构造一个只在内存中改过文件元数据的 `runtimeDoc`，用它调用 `documentService.chunkDocument`；
8. 只有文档最终为 `SUCCESS` 时，才进入 `CHUNK_COMPLETED`；
9. 将数据库文档元数据切到新文件，进入 `FILE_SWITCHED`；
10. 写回调度成功状态，最后删除旧对象。

最值得记住的设计是第 6～9 步：

> 新文件先完成摄取，数据库的“当前文件指针”再切换。这样可以避免在新文件摄取失败时，先把当前文档指向一个未准备好的副本。

### 4.5.3 清理责任由进度决定

`finally` 不是统一“删新文件”，而是按阶段决定：

| 最终阶段 | 清理策略 | 原因 |
|---|---|---|
| `FILE_SWITCHED` | 删除旧文件 | 新文件已经成为当前副本 |
| 新对象已存，但早于 `CHUNK_COMPLETED` | 删除新文件 | 摄取未完成，新对象没有成为可用版本 |
| 已 `CHUNK_COMPLETED`，但未 `FILE_SWITCHED` | 保留新文件并警告 | 已经产生的 Chunk/索引可能与它有关，不能盲目删除 |

锁丢失后，Processor 会停止继续执行，并且不再以过期 owner 的身份写回调度主状态。这里的锁不只是“防止同时跑两次”，它还是写回状态时的 owner 凭证。

## 4.6 责任与非责任

| 组件 | 它负责什么 | 它不负责什么 |
|---|---|---|
| `UploadRateLimitFilter` | 上传请求的跨实例并发许可 | 文档业务状态、文件内容校验 |
| `KnowledgeDocumentController` | HTTP 路由和参数绑定 | 存储、MIME 路由、摄取 |
| `KnowledgeDocumentServiceImpl.upload` | 校验来源/处理选择，创建对象和 `PENDING` 元数据 | 解析、分块、Embedding、索引 |
| `RemoteFileFetcher` | HEAD/GET、大小限制、哈希、临时文件生命周期 | Cron 触发、文档状态、索引切换 |
| `ScheduleRefreshProcessor` | 定时刷新的 owner、阶段、切换和清理编排 | 具体解析/分块算法 |

## 4.7 失败窗口：哪些有补偿，哪些不能过度承诺

### 4.7.1 摄取配置不合法

校验发生在存文件之前，因此没有对象存储副作用。

### 4.7.2 已存对象，但没有可用 Parser

Service 显式调用 `deleteByUrl`。这是一个可在方法体中直接看到的补偿。

### 4.7.3 已存对象，但数据库 insert 失败

当前 `upload` 方法在 `documentMapper.insert` 周围没有对称的对象删除分支。关系库事务也不能自动回滚 S3/OSS 写入。因此教程只能得出：

> 当前代码对“无 Parser”做了显式补偿，但不能将整个对象存储 + 数据库过程宣称为全局原子操作。

### 4.7.4 远程文件未改变

这不是失败。调度执行被记为跳过，不重复分块和建索引。

### 4.7.5 定时刷新的新文件摄取失败

文档被标记为失败，调度执行记录失败，新对象在尚未完成摄取时被删除，而数据库的当前文件元数据还没有切换到它。

## 4.8 为什么这样设计

下面是根据实现责任做出的设计解释，不冒充作者在文档中明示的原话：

- **上传和分块拆开**：把轻量元数据创建与重量 AI/索引任务解耦，文档状态也因此能表达“已收到但未摄取”。
- **上传限流放在 Filter**：保护的不只是 Service 线程，还有 multipart 解析前的内存、磁盘和网络资源。
- **URL 复制进自己的存储**：后续处理不再受制于远程站点短时不可达，同时保留了可定时刷新的来源指针。
- **刷新先摄取、后切文件指针**：把“新版本准备好”与“对外宣布它是当前版本”分开。
- **ETag / Last-Modified / SHA-256 分层判断**：优先用廉价标识短路，标识不可信时再付出下载和哈希成本。

## 4.9 面试官可能怎样追问

### 问题 1：用户上传文档后，为什么还不能立即检索？

参考回答：上传接口只完成对象存储和 `KnowledgeDocumentDO` 创建，初始状态是 `PENDING`、`chunkCount=0`。解析、分块、Embedding 和索引替换由另一个 `startChunk` 操作触发。

### 问题 2：为什么上传限流不写在 Controller 里？

参考回答：Filter 的优先级最高，目标是在 multipart 解析前就拒绝过量请求，避免先消耗临时文件、内存和 I/O。它用 Redisson 可过期信号量实现跨实例并发许可。

### 问题 3：URL 定时刷新如何避免新文件失败破坏当前版本？

参考回答：Processor 先上传新对象，用内存中的 `runtimeDoc` 运行摄取，只在文档变为 `SUCCESS` 后才调用 `applyRefreshedFileMetadata` 切换文档元数据。切换完成后才删旧文件。

### 问题 4：这条上传链路是不是完全事务化？

参考回答：不能这样概括。数据库事务不能自动回滚对象存储。当前代码对“存储后发现无 Parser”做了显式删除，但数据库 insert 失败后没有对称的对象补偿分支。

### 问题 5：定时刷新为什么既需要锁心跳，又要在关键点主动续约？

参考回答：心跳是长任务期间的持续维护，关键点续约/归属检查则是副作用前的 owner 门槛。锁一旦丢失，旧 worker 应停止继续并放弃写回主状态。

## 4.10 源码卡片

| 主题 | 路径 | 关键符号 |
|---|---|---|
| HTTP 入口 | `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/controller/KnowledgeDocumentController.java` | `upload`、`startChunk` |
| 上传编排 | `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/service/impl/KnowledgeDocumentServiceImpl.java` | `upload`、`resolveProcessModeConfig`、`resolveStoredFile` |
| 并发保护 | `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/filter/UploadRateLimitFilter.java` | `doFilterInternal`、`isUploadRequest` |
| 信号量初始化 | `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/config/SemaphoreInitializer.java` | `documentUploadSemaphoreInitialize` |
| URL 拉取 | `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/handler/RemoteFileFetcher.java` | `fetchAndStore`、`fetchIfChanged` |
| 定时刷新 | `rag/src/main/java/com/nageoffer/ai/ragent/knowledge/schedule/ScheduleRefreshProcessor.java` | `process`、`Phase` |
| 默认参数 | `bootstrap/src/main/resources/application.yaml` | `ragent.semaphore.document-upload`、`ragent.knowledge.schedule` |

所有锚点均以 AsterRAG 冻结提交 `98894c2c42c015a3c874c6b3c986ac863c85b731` 为准。

## 4.11 自我检查

不看本章，试着回答：

1. 上传成功后，对象存储和数据库各有什么？
2. `sourceLocation` 和 `fileUrl` 有什么不同？
3. 为什么 HEAD 判定过大后，GET 阶段还要再统计字节？
4. 为什么定时刷新不在上传新对象后立即更新 `fileUrl`？
5. 上传链的哪个失败窗口有显式补偿，哪个不能声称已全局原子化？

## 4.12 下一章桥梁

现在系统拿到了一串可信读取的原始字节，但“字节”还不是 RAG 能理解的证据。第 5 章将追踪这串字节如何经过 MIME 探测、Parser 路由和结构化 Block 建模，变成分块层能够正确处理的中间表示。
