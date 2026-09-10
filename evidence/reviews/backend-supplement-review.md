# 后端增补篇：教学审读与发布前核对

日期：2026-09-10。范围：第 35～44 章、首页、后端增补计划、对照附录、source map 和文档检查脚本。

## 教学审读

- 第一部分从一个用户问题出发，依次讲装配、保存、协调、流式执行；停止和删除都接回同一任务生命周期。
- 第二部分接住第一部分留下的技术问题：单例 → 可见性/锁，删除 → 事务代理，历史 → 联合索引，闸门 → Redis 租期，流式 → 连接/重试/容量。
- 原理和具体例子位于正文，源码长路径集中到附录；不要求读者先理解 Java 类列表才能理解流程。
- 两部分均关联面经真实主题；末章明确组合模拟问答是教学重组，不伪装成原帖逐字对话。
- 现有 HNSW/BM25/LightRAG 和评测章节保持原编号；后端篇只补连接边界，不重复整套算法教程。

## 重点源码复核

| 易讲错的点 | 当前表述 |
|---|---|
| Maven 七模块 | 编译组织，不是七个微服务；Java 基线 17 |
| Agent 单例 | Provider 复用 Agent/目录；本轮句柄和事件桥单独创建 |
| 身份上下文 | TTL 与显式 user/session 传递并存；不保证所有异步线程自动传播/及时清理 |
| 消息与状态 | 业务消息、框架 JSONB、长期记忆分开，不冒充 Redis 全量对话记忆 |
| 终答落库 | 捕获失败可返回空 messageId，完成事件不作为持久化成功证明 |
| 会话历史 | 通过 replyToMessageId 配对，排除被打断答案；扫描窗口不保证永远凑满 |
| 索引 | 消息 create_time 索引不等同于 id 排序；索引声明不等于实际查询计划 |
| 删除事务 | 同库操作与 afterCommit 外部清理分开；自调用不抹去外层事务 |
| Redis 锁 | RBucket NX + TTL + owner CAS；没有 RLock watchdog |
| 取消 | 标记覆盖注册窗口；已注册任务漏广播时不能保证后来自动补到 |
| 统一收尾 | 本轮 CAS 至多一次进入；不夸大为跨进程 exactly-once |
| 超时 | Future 完成超时不等于下游操作已停止 |
| 搜索副本 | best-effort；图谱单块改删不同步；不等于自动最终一致 |
| 基础八股 | PostgreSQL 与 MySQL 分别解释；设计推演不当已实现功能 |

## 文档静态检查

本次执行：

```text
python3 scripts/audit-backend-supplement.py
chapters=10 chinese_characters=24002
checks=406 failures=0

python3 scripts/audit-tutorial.py
checks=1005 failures=0 warnings=0

python3 scripts/audit-evaluation-supplement.py
checks=105 failures=0

python3 scripts/audit-retrieval-supplement.py
checks=135 failures=0

git diff --check
通过
```

后端检查核对章节结构、两部分归属、导航、围栏、隐私路径/密钥形状、关键主题、26 个源码文件与符号片段、冻结源码版本、公开题源映射和教学算式。检查脚本只读，不运行产品或评测，也不导入业务模块。

机械检查不证明文字解释天然正确；上述重点另行对照实际调用与字段。内嵌 Mermaid 共三张，完成文本结构审读，没有进行浏览器或图形渲染验收。官方文档按正文链接核对，但不把最新库能力推定为项目已采用。

## 发布边界

目标是现有私有教程仓库 main。只提交教程增补和导航/审计修改，不推送产品源码变化，不改可见性，不上传面经数据库。推送与远端提交核对在文档检查之后执行。
