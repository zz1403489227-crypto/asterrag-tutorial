# 评测篇来源与论断导航

阅读日期：2026-09-08。评测源码冻结 `9d69c63cdca0bf730d8900c3076e0480e541360c`；产品基准 `98894c2c42c015a3c874c6b3c986ac863c85b731`。

原始来源为用户已有权限的 [GitCode 评测项目](https://gitcode.net/nageoffer/ragenteval)。通过文件页面读取数据模型、CLI、runner、score、全部六个 metrics 文件（包括共享模块）、markdown 报告和 diff；读取两份完整 JSONL 数据及案例商品资料。未运行任何评测代码。

浏览器文件正文读取用于解释，未将原仓代码或完整评估集加入教程发布目录。精确文件链接和函数位置见[附录 E](../appendices/evaluation-implementation-notes.md)。

| ID | 关键论断 | 第一手来源 | 教学位置 |
|---|---|---|---|
| EV01 | 输入、记录、指标分为三类数据 | schemas.py 的三个 dataclass | 26 |
| EV02 | run/score/report 分离 | cli.py、runner.py、score.py、markdown.py | 26、28、31 |
| EV03 | 默认集 20，全量集 150，默认只读小集 | 两份 JSONL 全文；runner.py:34、run | 27 |
| EV04 | S2-01 是尺寸与刷新率，指向 PROD_PHONE_004 | 默认 JSONL 第 14 条；产品资料参数表 | 26～30 |
| EV05 | S3-01 的 must 有两款手机文档 | 默认 JSONL 第 15 条 | 27、29 |
| EV06 | 两个请求只发 question，旁路独立重查 | runner.py:111、192、286、304；产品 EvalController:63 | 28 |
| EV07 | 首字是正式 response 首个非空 delta | runner.py:111 | 28、29 |
| EV08 | 文档级有序去重与块级对应关系不同 | 产品 EvalController:73、105、123、181 | 28 |
| EV09 | Hit/Recall/MRR 的对象与过滤 | retrieval.py、_common.py | 29 |
| EV10 | 误拒率实为空召回代理，不是 refused 状态比较 | behavior.py:20 | 29 |
| EV11 | 当前延迟输出 P50/均值/整流均值，首字缺失会回退 | latency.py:14、33 | 29 |
| EV12 | 五项 RAGAS 的统一输入与筛选 | ragas_judge.py:45、66、125 | 30 |
| EV13 | 多轮逐题均分、None 和重试处理 | ragas_judge.py:229 | 30 |
| EV14 | 人工分优先，机器分不被原地覆盖 | markdown.py:97、125、387；cli.py:84 | 31 |
| EV15 | 失败判定的具体阈值与理由 | markdown.py:22、23、294 | 31 |
| EV16 | diff 使用原 scores 与阈值，未做统计检验 | diff.py:45、166 | 31 |
| EV17 | 现有 CLI 为 rag，agent 只有预留结构 | cli.py:180；仓库文件索引 agent 路径 | 26、31 |

## 算法背景的独立来源

RAGAS 官方 v0.2.14 的四篇指标文档及 AnswerCorrectness、AnswerRelevancy 源码，用于解释算法；链接在第 30 章和附录 E。版本标签是算法说明参考，不作为用户或作者机器上已安装依赖版本的证明。

## 教学演算和建议

以下均由教程构造：X/A/Y/B/Z 排名、四块相关性标记、故意错误或遗漏的手机回答、假设相似度 0.8、示意 SSE 时间、三轮裁判分与人工复核分。它们演示公式，不是 examples 目录里的运行产物，也不是本次调用得到的成绩。

保留集隔离、同请求证据快照、HNSW 精确近邻基线、图路径标注与 Agent 工具轨迹评估，是基于机制提出的下一步设计，不写成当前实现。

## 说明与源码的分歧处理

延迟模块的 README/注释存在旧 P95/P99 描述，正文按当前计算函数讲；默认集规模按 JSONL 条数讲；产品旁路开关按 AsterRAG 的 ragent.eval.enabled 讲。其余枝节集中到附录，正文不变成差异清单。
