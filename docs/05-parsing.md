# 第 5 章：文档怎样变干净——MIME、解析器路由与结构化 Block

> 本章的主角不是向量数据库，而是解析层。如果标题、表格、代码和图片在这一层被压成一堆无结构字符，后面再精巧的分块和检索也无法完全恢复原结构。

## 5.1 你现在位于总体图的哪里

第 4 章交给本章的是三个对象：

- 原始文件字节 `byte[]`；
- 用于探测的原始文件名；
- 文档 ID，用来给解析产生的图片资产建立稳定归属。

本章要追踪的流程是：

```text
byte[] + filename
       ↓
MimeTypeDetector
       ↓ actual MIME
ParserRegistry.require(MIME, ParseProfile)
       ↓ DocumentParser
parseStructured(...)
       ↓
ParsedDocument
  ├─ blocks: Heading / Paragraph / Table / HTML Table / Image / Code / List
  └─ metadata: parser / MIME / 解析器专有信息
```

第 6 章会解释这条链如何嵌入完整摄取内核。本章先专注于“字节怎样变成结构”。

## 5.2 第一个核心问题：格式该信谁

对一份名为 `report.pdf` 的文件，系统可以看到至少三种“类型”：

| 类型信息 | 从哪里来 | 在 AsterRAG 里的用途 |
|---|---|---|
| 扩展名 / `fileType` | 文件名 | 展示、预览和下载时的内容类型辅助 |
| HTTP `Content-Type` | 上传请求或远程响应 | 输入线索，但远程站点可能给错 |
| 字节探测的 MIME | `MimeTypeDetector.detect(bytes, filename)` | Parser 路由的最终依据 |

`MimeTypeDetector` 内部使用 Apache Tika。有文件名时调用 `TIKA.detect(bytes, fileName)`，没有文件名时只用字节。字节为空则返回 `null`。

这里的“字节是唯一权威”不要理解成“文件名完全不参与”。Tika 的 API 同时收字节和文件名，文件名是探测线索；关键在于 Parser 不是直接按用户填的扩展名分发。

## 5.3 ParserRegistry：把“选哪个解析器”变成可校验的路由表

### 5.3.1 路由键不是只有 MIME

Parser 的完整路由键是：

```text
(MIME, ParseProfile) → DocumentParser
```

`ParseProfile` 表示用户愿意付出多少成本换多少结构保真度：

- `FAST`：默认档，也是全局兜底档；
- `FIDELITY`：保真档，当某个 MIME 有专用高保真路径时选用它。

ParserRegistry 的查找顺序是固定的：

```text
精确 MIME + 请求档位
    → 同大类通配 MIME + 请求档位
    → 精确 MIME + FAST
    → 通配 MIME + FAST
    → 无命中，显式报错
```

例如，请求一个没有专属 `FIDELITY` Parser 的 Markdown 文档时，Registry 会回落到 Markdown 的 `FAST` 路由，不是回落到任意通用 Parser。

### 5.3.2 路由冲突不等到用户上传时才暴露

每个 `DocumentParser` 通过 `supportedMimeTypes()` 显式声明自己认领哪些 `(MIME, Profile)`。Registry 在构造时建表：

- Parser 没有声明任何路由，启动失败；
- 两个 Parser 认领同一个键，启动失败；
- 非 `FAST` 档使用 `type/*` 通配，启动自检失败；
- 对外声明支持的扩展名被 Tika 探测成某 MIME，但 `FAST` 精确表无人认领，启动失败。

自检清单包含 PDF、Word、PPT、Excel、CSV、Markdown/TXT、HTML/JSON/XML/RTF 和 PNG/JPEG/SVG 等 21 个扩展名。它不只问“是否有 `text/*` 兜底”，而是要求这些已声明格式都有精确路由，避免 CSV 或 Markdown 悄悄落入 Tika 平文本兜底。

### 5.3.3 `canParse` 和 `require` 责任不同

- `canParse(mime)` 遍历所有档位，只回答“这种 MIME 是否有任何可用路线”，用于上传前置拦截；
- `require(mime, profile)` 根据本次摄取配置选实际 Parser，无法路由时抛出客户端错误。

因此“上传时确认可解析”和“本次按指定档位选出了 Parser”是前后两次不同粒度的判断。

## 5.4 当前解析器全景

| Parser | 主要认领 | 输出结构 | 关键边界 |
|---|---|---|---|
| `MarkdownDocumentParser` | Markdown 和 `text/plain`，`FAST` | Heading、Paragraph、Code、List、Table、HtmlTable、Image | 使用 CommonMark AST；不是按空行粗暴切字符串 |
| `CsvDocumentParser` | CSV，`FAST` | 一个 `TableBlock` | 首行是表头；支持引号内逗号/换行和 `""` 转义 |
| `ExcelDocumentParser` | Excel 和 Tika Office 别名，`FAST` | 每个非隐藏 sheet 一个 H1 + 一个 `TableBlock` | POI 展开合并单元格、展平多行表头、格式化公式/链接 |
| `TikaDocumentParser` | HTML、JSON、XML、RTF 与其他 `text/*`，`FAST` | 只有 `ParagraphBlock` | 平文本兜底；用空行分段，不保留复杂版面 |
| `MinerUDocumentParser` | PDF/Word/PPT 由 `FAST` 认领；Excel 的 `FIDELITY` | 从 MinerU zip 中的 Markdown/图片重建多类 Block | 外部服务、分布式并发许可、上传+轮询+下载 zip |
| `ImageDocumentParser` | PNG/JPEG/SVG，`FAST` | 单个 `ImageBlock` | SVG 先柵格化；VLM 必须产生非空描述；原图写资产桶 |

两个容易误解的点：

1. **PDF 并不是 Tika Parser 的当前主路。** `TikaDocumentParser.supportedMimeTypes` 没有认领 PDF，PDF 由 MinerU 路由认领。
2. **`FIDELITY` 不等于所有文档都走另一套 Parser。** 当前明确的档位差异主要体现在表格类：Excel 的 `FAST` 走 POI，`FIDELITY` 走 MinerU。其他格式没有专属保真路由时回落 `FAST`。

## 5.5 ParsedDocument 为什么是一个重要的分层边界

`DocumentParser.parseStructured` 统一返回：

```java
record ParsedDocument(List<Block> blocks, Map<String, Object> metadata)
```

它把 Parser 的专有实现隐藏在同一个中间表示后面。分块层不需要知道这是 MinerU、POI 还是 CommonMark 的结果，只需要根据 Block 类型分发。

### 5.5.1 Block 是一个 sealed 类型集合

`Block` 是 sealed interface，当前只允许七种实现：

| Block | 保留的语义 | 对后续分块的影响 |
|---|---|---|
| `HeadingBlock` | 标题级别和文本 | 更新章节路径，并影响切分边界 |
| `ParagraphBlock` | 段落文本，可包含 Markdown 链接/行内代码/HTML | 可按字符预算切开，也可跨短段合并 |
| `TableBlock` | headers + rows | 按数据行切，每块重复表头 |
| `HtmlTableBlock` | 原始 `<table>` HTML | 不强制展开复杂合并单元格，另路切行 |
| `ImageBlock` | 资产 URL、caption/alt、可选 VLM description | 图片链接是不可切碎的原子单元，description 用于召回 |
| `CodeBlock` | 语言和代码 | 不为凑预算而切碎代码 |
| `ListBlock` | 有序/无序和列表项 | 短列表原子化，长列表按项分组 |

sealed 的价值不只是语法上“更安全”。当新增一个 Block 类型时，处理 Block 的 switch/分发点必须显式考虑它，不容易被无声当成普通段落。

### 5.5.2 展示文本和检索文本从这里开始分岔

Block 只表达内容与结构，不直接存储最终向量文本。后续 chunker 会产生：

- `content`：保留 Markdown 展示形式，给前端预览和 LLM 上下文；
- `embeddingText`：加入章节路径、去掉无意义 URL 噪声后的检索文本。

这是为什么图片 Block 既保留资产链接，又要有 VLM description：URL 适合展示，描述适合语义召回。

## 5.6 四条典型解析路径

### 5.6.1 Markdown：语法树映射，不是正则拆行

`MarkdownDocumentParser` 使用 commonmark-java 构建 AST，然后用 Visitor 只处理顶层 block。它会：

- 将 Heading 转成 `HeadingBlock`；
- 将 fenced/indented code 转成 `CodeBlock`；
- 将 BulletList/OrderedList 转成 `ListBlock`；
- 将 GFM table 转成结构化 `TableBlock`；
- 将原生 HTML table 保留为 `HtmlTableBlock`；
- 将独占段落的图片提升为 `ImageBlock`，行内图片仍保留在段落 Markdown 中。

链接保留成 `[text](url)`，行内代码保留反引号，强调标记被移除但文本不丢失。

### 5.6.2 Excel：表格的问题不是“读出所有单元格”

`ExcelDocumentParser` 使用 POI，但具体规范化由 `ExcelTableNormalizer` 完成。它会：

- 跳过隐藏和 very-hidden sheet；
- 展开合并单元格；
- 将多行表头展平成一行，用 `|` 联结层级；
- 使用 `DataFormatter` 和 `FormulaEvaluator` 处理展示值与公式；
- 把超链接写成 Markdown 链接；
- 每个非空 sheet 先产生一个 H1，再产生一个 Table。

sheet 名转成 Heading 是一个关键适配：它不需要创造一套 Excel 专属的上下文系统，后续标题路径机制自然就能把 sheet 名加入向量文本和块元数据。

### 5.6.3 MinerU：它不是一个单纯的 `parse(byte[])`

MinerU 路径包含外部任务生命周期：

```text
申请上传票据
  → PUT 原文件到 MinerU OSS
  → 轮询 batch 状态
  → 下载结果 zip
  → 解包 Markdown + images
  → 图片上传到项目资产桶
  → 用资产 URL 重写 Markdown 中的图片地址
  → 必要时用 VLM 为内嵌图生成描述
  → ParsedDocument
```

`MinerUDocumentParser` 使用 Redisson 可过期信号量限制跨实例并发解析数。超时、中断或调度异常会转换为有 batchId 上下文的业务错误。解析成功后，`minerU.batchId` 和 `minerU.zipUrl` 被放入 `ParsedDocument.metadata`，用于排障。

`MinerUResultUnpacker` 对图片失败有两种不同策略：

- 资产上传失败会中断整份文档解析，因为块中无法建立有效图片引用；
- 单张内嵌图的 VLM 描述失败只记告警，不让整篇文档失败。

第二点是一个明确的质量与可用性权衡：少一张图的语义描述，通常比整篇文档不能入库更可接受。

### 5.6.4 独立图片：可展示不等于可检索

`ImageDocumentParser` 支持 PNG、JPEG 和 SVG。SVG 先用 Batik 柵格化成白底 PNG，再进入 VLM。VLM 输出如果为空，Parser 直接失败，因为只把 `![](url)` 做 Embedding 几乎没有可检索语义。

非空描述完成后，原图上传到 `assets/{documentId}/...`，然后构造同时包含 `AssetRef`、caption 和 description 的 `ImageBlock`。

## 5.7 Provenance 到底能定位到多细

`Block.provenance()` 提供来源信息。但教程必须以当前 record 的真实字段为准：

```java
record Provenance(String sourceFile, String sheetName)
```

因此当前结构化块能稳定保留原文件标识，Excel 还能保留 sheet 名。虽然接口注释对 provenance 的概念描述更宽，当前 `Provenance` 数据结构并没有 page、bbox 或单元格坐标字段。所以不能将它说成已经实现 PDF 页码或坐标级引用定位。

这一点很适合面试表达：你既能说出系统有 provenance 概念，也能准确说出当前实现的粒度边界。

## 5.8 责任与非责任

| 组件 | 负责 | 不负责 |
|---|---|---|
| `MimeTypeDetector` | 从字节+文件名得到 MIME | 决定解析成本档位 |
| `ParserRegistry` | 管理 `(MIME, Profile) → Parser` 路由和启动自检 | 实际解析文档 |
| `DocumentParser` | 把字节变成 `ParsedDocument` | 分块预算、Embedding、索引写入 |
| `ParsedDocument` / `Block` | 作为 Parser 与 Chunker 间的结构化内存契约 | 完整源文件存档或持久化格式 |
| `Provenance` | 当前保留 sourceFile/sheetName | 页码、bbox、单元格坐标级定位 |

## 5.9 解析质量的真实边界

源码已经对不同模态做了明确分流，但它不会自动解决所有数据质量问题：

- Tika 路径主动接受平面化，因为这些长尾格式没有专属结构 Parser；
- Excel 的多行表头展平是一种确定性规范化，但无法保证所有非规则表格的业务语义；
- MinerU 可以提供更好版面结构，但是外部服务、并发限制、轮询和超时都成为解析路径的一部分；
- VLM 描述把图片变成可召回文本，但描述的准确性仍受模型、Prompt 和图片质量影响；
- 当前 provenance 粒度不足以支持 PDF 精确页码/bbox 引用。

因此可以说“系统使用结构化 Parser 和 Block 模型保留标题、表格、代码、列表和图片语义”，但不能说“任意 PDF/Office 都能完美还原且精确定位”。

## 5.10 为什么这样设计

下列内容是从实现结构推导出的设计解释：

- **Registry 而非 if-else 链**：新增 Parser 通过声明路由加入，冲突能在启动时被发现，而不用改一个中央分支。
- **MIME 和 Profile 正交**：MIME 回答“这是什么文档”，Profile 回答“本次愿意付出多少成本”，二者不应混在一个枚举里。
- **先变成 Block，再分 Chunk**：Parser 关心文档语法，Chunker 关心预算与检索单元；分层后同一套 Chunker 可复用多种 Parser 产物。
- **复杂表格保留 HTML**：强制展开 rowspan/colspan 会引入不可逆信息损失，保留原 HTML 让展示和专用 chunker 接手。
- **图片分开展示 URL 和语义描述**：一个服务前端渲染，一个服务于召回与答题。

## 5.11 面试官可能怎样追问

### 问题 1：为什么不直接按文件扩展名选 Parser？

参考回答：扩展名可以伪造，远程 `Content-Type` 也可能不准。当前代码用 Tika 根据字节+文件名探测 MIME，再通过 `(MIME, ParseProfile)` 注册表选 Parser。

### 问题 2：ParserRegistry 如何避免两个 Parser 抢同一种格式？

参考回答：每个 Parser 显式声明认领键，Registry 在构造时建精确表和通配表，同键冲突直接抛错，另有 `@PostConstruct` 扩展名自检。

### 问题 3：为什么要保留标题 Block，而不是当成普通文本？

参考回答：标题是结构上下文。后续 `HeadingHandler` 用它维护 outline path，Chunk 的 `embeddingText` 可以加入章节路径，`ChunkPacker` 也用标题界定语义节。

### 问题 4：MinerU 和 Tika 在这个项目里是什么关系？

参考回答：它们不是先后必经的两步。Tika 一方面用于 MIME 探测，另一方面是 HTML/JSON/XML/RTF 和长尾文本的平文本 Parser；PDF/Word/PPT 的 Parser 路由当前由 MinerU 认领。

### 问题 5：项目已经能对 PDF 做页码/bbox 精确引用吗？

参考回答：当前不能这样声称。Block 确实有 provenance 概念，但当前 `Provenance` record 只有 `sourceFile` 和 `sheetName`，没有 page/bbox 字段。

### 问题 6：为什么独立图片的 VLM 返回空文本要让整个 Parser 失败？

参考回答：如果只生成一个带 URL 的图片 Chunk，Embedding 几乎没有图像语义，后续无法按图中内容召回。所以独立图片路径将非空描述作为有效输出的必要条件。

## 5.12 源码卡片

| 主题 | 路径 | 关键符号 |
|---|---|---|
| MIME 探测 | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/mime/MimeTypeDetector.java` | `detect` |
| Parser 端口 | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/DocumentParser.java` | `parseStructured`、`supportedMimeTypes` |
| 路由表 | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/registry/ParserRegistry.java` | `find`、`require`、`selfCheck` |
| 档位 | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/registry/ParseProfile.java` | `FAST`、`FIDELITY` |
| 统一产物 | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/model/ParsedDocument.java` | `blocks`、`metadata` |
| Block 集合 | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/model/Block.java` | sealed `permits` |
| 来源粒度 | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/model/Provenance.java` | `sourceFile`、`sheetName` |
| Markdown | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/MarkdownDocumentParser.java` | `BlockExtractingVisitor` |
| CSV | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/CsvDocumentParser.java` | `parseCsv` |
| Excel | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/excel/ExcelDocumentParser.java` | `buildSheetBlocks` |
| 长尾文本 | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/TikaDocumentParser.java` | `parseStructured` |
| MinerU | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/mineru/MinerUDocumentParser.java` | `doParseStructured` |
| MinerU 解包 | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/mineru/MinerUResultUnpacker.java` | `unpack`、`describeImages` |
| 独立图片 | `rag/src/main/java/com/nageoffer/ai/ragent/core/parser/image/ImageDocumentParser.java` | `parseStructured`、`rasterizeSvg` |

所有锚点均以 AsterRAG 冻结提交 `98894c2c42c015a3c874c6b3c986ac863c85b731` 为准。

## 5.13 自我检查

1. MIME 和 ParseProfile 分别回答什么问题？
2. ParserRegistry 的四级查找顺序是什么？
3. 为什么 CSV/Markdown 需要精确路由，不应落入 Tika `text/*`？
4. `ParsedDocument` 为什么能解耦 Parser 和 Chunker？
5. 独立图片和 MinerU 内嵌图的 VLM 失败策略为什么不同？
6. 当前 Provenance 的精确粒度到哪里？

## 5.14 下一章桥梁

本章已经把原始字节变成了一列有顺序的 Block。下一章要回答两个更大的问题：这个解析步骤在知识文档主链中由谁触发？仓库里另一套可配置 `IngestionEngine` 与当前固定五步摄取内核究竟是什么关系？
