# P3 远程开发环境普查

> 普查日期：2026-09-01  
> 范围：只读检查宿主工具、磁盘、端口、Docker 资产和项目自带 Compose；未读取或输出任何凭据。

## 1. 直接结论

- 宿主默认 Java 是 OpenJDK 11.0.31，而项目要求 Java 17；不能直接用宿主 JDK 声称构建可复现。
- 已提供 Maven Wrapper 3.9.11；宿主 Node.js 22.22.3、npm 10.9.8。
- Docker 29.1.3、Docker Compose v5.1.4 可用。
- `/data2` 仍约有 1.8 TiB 可用空间，内存不是当前瓶颈。
- 服务器已有 `corpusbeacon-*` PostgreSQL、Qdrant、后端和前端容器，它们属于另一项目，不能停止、改名、复用其数据库或网络作为 AsterRAG 验证证据。
- 9090 等多个常用端口已占用；AsterRAG 集成环境必须使用隔离 Compose project 和重新映射的宿主端口。

## 2. 本阶段采取的隔离策略

```text
冻结源码（只读事实）
  <tutorial-workspace>/sources/AsterRAG
                |
                | shared clone, same detached commit
                v
测试工作副本
  <tutorial-workspace>/runtime-work/AsterRAG
                |
                +-- Docker image: maven:3.9.11-eclipse-temurin-17
                +-- scoped cache volume: asterrag-tutorial-m2
                +-- target/ 只产生在 runtime-work，不污染 frozen source
```

工作副本固定为 `98894c2c42c015a3c874c6b3c986ac863c85b731`。每轮测试后同时检查 frozen source 和 runtime-work 的 Git 状态；源码文件保持干净，`target/` 是忽略的构建产物。

## 3. 为什么不安装宿主 JDK 或复用现有容器

- 安装系统 JDK 会扩大服务器全局变更范围，而容器已经能提供精确 Java/Maven 版本。
- 复用 CorpusBeacon 的数据库/网络会混淆所有权，测试通过也不能证明全新 AsterRAG 环境可复现。
- 项目自带 RocketMQ Compose 使用固定 `container_name` 与 9876/10911/8080～8082 等宿主端口；项目自带 Milvus Compose 也有自己的固定网络/卷假设。P3 将复制所需语义到教程专用栈，而不是直接启动并可能冲突。

## 4. 证据分层

| 层级 | 当前环境 | 能证明 | 不能证明 |
|---|---|---|---|
| Hermetic | JDK 17 Maven 容器 + Mockito/fixture | 编译、纯逻辑、状态机与异常边界 | Broker、数据库、对象存储、向量库真实协作 |
| Integration | 待建立教程专属 Compose | 上传、事务消息、解析、Chunk、索引、召回与失败恢复 | 外部商用模型质量 |
| Live | 只有在不暴露凭据且配置明确时执行 | 真实模型/Embedding 调用 | 可重复的确定性质量结论 |
| Browser | 后续真实前端访问 | 页面协议、状态刷新与用户可见结果 | 后端内部一致性本身 |

## 5. 仍需在启动前决定的端口

实际端口分配必须在 Compose 启动前再次用只读命令检查，不能把本次快照永久写死。至少要为以下服务分配项目专属端口：PostgreSQL/pgvector、Redis、S3-compatible object storage、RocketMQ NameServer/Broker、AsterRAG backend，以及后续 Browser 验证的 frontend。
