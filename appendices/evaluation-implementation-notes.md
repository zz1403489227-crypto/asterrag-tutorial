# 附录 E：评测实现备查——原理之外的精确口径

第 26～31 章负责解释评测的原理与完整流程。本附录只在需要定位实现、核对版本或解释某个具体分数时查阅。

评测项目基准：`nageoffer/ragenteval`，提交 `9d69c63cdca0bf730d8900c3076e0480e541360c`。产品基准保持 AsterRAG `98894c2c42c015a3c874c6b3c986ac863c85b731`。二者不是一份代码，也不假定所有说明处于同一演进阶段。

## E.1 从问题找源码

| 想核对的内容 | 冻结源码入口 | 主要位置 |
|---|---|---|
| 样本、记录和指标各带什么 | [schemas.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/common/schemas.py#L31) | EvalSample、EvalRecord、MetricResult |
| 回答如何从流拼接 | [runner.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/pipeline/runner.py#L111) | stream_chat_one_query |
| 旁路请求与合成记录 | [runner.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/pipeline/runner.py#L192) | fetch_eval_retrieval、build_record |
| 默认题库、串行与并行 | [runner.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/pipeline/runner.py#L304) | run；默认题库常量在第 34 行 |
| 每项指标的样本过滤 | [_common.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/metrics/_common.py#L10) | slice_mean、is_retrieval_eligible |
| Hit、Recall、MRR | [retrieval.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/metrics/retrieval.py#L24) | _hit_at_k、_recall_at_k、_mrr_at_10 |
| 意图 Top1 | [intent.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/metrics/intent.py#L11) | intent_pred 与 intent_l2 精确比较 |
| 空召回、答案兜底、过召回 | [behavior.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/metrics/behavior.py#L16) | 三个 compute 子函数 |
| 首字与整流时间 | [latency.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/metrics/latency.py#L14) | compute、_first_token_or_total |
| 四文本输入与可评条件 | [ragas_judge.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/metrics/ragas_judge.py#L45) | filter_evaluable、_build_dataset |
| 裁判、指标和批量回退 | [ragas_judge.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/metrics/ragas_judge.py#L90) | _build_judges、_build_metrics、_run |
| 多轮均分与无效值 | [ragas_judge.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/metrics/ragas_judge.py#L229) | compute |
| 指标编排与结果落盘 | [score.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/pipeline/score.py#L81) | score |
| 人工分与失败样本 | [markdown.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/report/markdown.py#L97) | load_manual_overrides、apply_manual_overrides、get_failure_qids |
| 报告如何使用人工分 | [cli.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/common/cli.py#L84) | cmd_report |
| A/B 对比 | [diff.py](https://gitcode.net/nageoffer/ragenteval/-/blob/9d69c63cdca0bf730d8900c3076e0480e541360c/eval/rag/report/diff.py#L166) | compare |

## E.2 两个接口与产品版本

录制器对每题先调用 GET `/rag/v3/chat`，后调用 GET `/rag/eval`；两次均发送 question，没有把聊天 task/conversation ID 传给旁路。并发只发生在题与题之间。

AsterRAG 的 [EvalController](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/eval/EvalController.java#L53) 使用 `ragent.eval.enabled` 条件注册。评测 README 和 runner 注释提到 `app.eval.enabled`，不能把旧提示替换成当前产品配置事实。本篇不更改任何开关。

旁路用空历史执行 rewriteWithSplit，再 resolve 意图并 retrieve。它不是查询聊天 Trace 的读接口。它摊平 intentChunks，按 chunk ID 去重保留首次顺序，取得文本；通过数据库还原文档归属，再按文档首次出现顺序去重。跨意图摊平后的顺序不应另行宣称为全局相似度重新排序。

当前产品旁路已经把文档还原成 doc_name 去扩展名的业务编号。Python 仍加载内部 ID 到业务编号的映射，映射不到时保留原值；因此 returned raw 字段是“旁路原返回值”，不保证一定全是数字内部 ID。

旁路返回检索块文本，不等于聊天 prompt 的最终预算快照。它的 [EvalResponse](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/eval/EvalResponse.java) 也未提供 runner 所尝试读取的 traceId，因此对当前产品不能依赖该字段形成双请求的同源证明。

RAG v3 控制器调用 RAGChatService；Agent 是单独入口。见 [RAGChatController](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/rag/src/main/java/com/nageoffer/ai/ragent/rag/controller/RAGChatController.java#L51) 与 [AgentChatController](https://github.com/zz1403489227-crypto/AsterRAG/blob/98894c2c42c015a3c874c6b3c986ac863c85b731/agent/src/main/java/com/nageoffer/ai/ragent/agent/controller/AgentChatController.java)。

## E.3 样本与记录中的字段边界

EvalSample 保留 query、意图、难度、requires_rag、must/nice 文档、ground_truth、expected_answer_type 与 trap_type；from_dict 不保留数据里的 eval_metrics。因此它不是逐题控制评分器的指令。

EvalRecord 把 ground_truth 改名为 reference，把 query 改名为 user_input；保存聊天 response、thinking、状态、错误、首字/总时间，以及旁路文档/块/上下文、预测意图和 has_kb/has_mcp 等。expected_answer_type、trap_type 没有继续进入这个记录模型。

intent_pred 取旁路 intent_leaf_ids 中第一个非空项，不把整个列表做集合匹配。标准标签必须与服务端意图 ID 体系对齐，不能拿展示名称替代。

错误字段优先取聊天错误，否则取旁路错误；final_status 来自聊天。于是聊天 success 与旁路 error 可以同时存在，不能只看一个状态字段判断全部观测完整。

## E.4 当前指标完整口径

- 文档 K 值为 1、3、5、10；每个 K 有 hit、must recall、inclusive recall，另外有 mrr@10。
- Hit 与 must Recall/MRR：requires_rag 且 must 非空；inclusive Recall：requires_rag 且 must 或 nice 非空。
- 指标模块截取 retrieved_doc_ids[:K] 后计算，文档有序去重主要由产品旁路完成；不要假定任意手工 runs 都被 Python 自动全局去重排序。
- 意图、检索和行为模块并未统一按 success 过滤；不满足可评条件是 None，正常参与而未达到目标才是 0。
- 首字计时在 SSE 正式 response 非空时首次采样，不计 think 或 meta；聊天 latency 在聊天函数退出时结束。
- latency.py 输出 ttft_p50_ms、ttft_mean_ms、total_mean_ms。没有当前 P95/P99 输出；first_token_ms 缺失或为零时回退 latency_ms，过滤无可用时间项。
- RAGAS 统一要求非空 response、contexts、reference 和 success，再做 ragas_limit 前 N 条截取。这个限制不是随机抽样；被 limit 截掉的题也不计入原始 skipped 原因列表。

## E.5 RAGAS 原理参考与封装参数

五项指标从 ragas.metrics 导入传统实例，拷贝后使用。推理模型分支把 answer_relevancy.strictness 设为 1；其它模型遵循库实例配置。裁判模型默认 `gpt-5.4-mini`，裁判 Embedding 默认 `text-embedding-3-large`，均可由环境变量覆盖；这些是评分侧默认值，不是被评 RAG 模型配置。

RAGAS 内部算法参考：

- [Faithfulness v0.2.14](https://docs.ragas.io/en/v0.2.14/concepts/metrics/available_metrics/faithfulness/)
- [Context Recall v0.2.14](https://docs.ragas.io/en/v0.2.14/concepts/metrics/available_metrics/context_recall/)
- [Context Precision v0.2.14](https://docs.ragas.io/en/v0.2.14/concepts/metrics/available_metrics/context_precision/)
- [Response Relevancy v0.2.14](https://docs.ragas.io/en/v0.2.14/concepts/metrics/available_metrics/answer_relevance/)
- [AnswerCorrectness v0.2.14 源码](https://github.com/explodinggradients/ragas/blob/v0.2.14/src/ragas/metrics/_answer_correctness.py)
- [AnswerRelevancy v0.2.14 源码](https://github.com/explodinggradients/ragas/blob/v0.2.14/src/ragas/metrics/_answer_relevance.py)

多轮评分对每题每指标的有效值平均；所有轮都无效的项会尝试重评，仍失败保留 None。聚合不把 None 当零。最终结果没有保留完整每轮分数分布，也没有实现统计置信区间。

score 对 RAGAS 依赖缺失、配置错误或执行异常进行捕获，自建指标仍能落盘。因此有 _scores.json 不代表五项语义指标一定都算成功。

## E.6 人工复核与对比的衔接

人工列可用 0～1、0～100 或带百分号格式；1 表示满分，1% 表示百分之一。report 以人工值覆盖内存中的报告指标，重算总体/意图分组；原始 _scores.json 不因 report 被改写。CSV 的原指标列保留机器分，人工列单独保留人工值。

只有已有的 RAGAS MetricResult 会被人工覆盖；完全没有相应指标时，不会仅凭一列人工值自动创建一套新指标。自动 CSV 列还取决于是否存在逐题数据。

失败筛选包括 Hit@5=0、Correctness<0.5、Faithfulness<0.5、空召回代理及过召回。没有自动囊括所有错误状态。

diff 比较原 _scores.json，不读取人工列；其退化提示使用绝对变化阈值，不是统计显著性。当前 LOWER_IS_BETTER 未列入 total_mean_ms，不能机械照搬该项的箭头或告警方向；教程未修改工具，延迟解释以“更低通常更好”的实际含义为准。

## E.7 阅读与交付边界

本篇通过用户已获授权的 GitCode 页面读取实现与样本，不提取浏览器凭据，不发布原始评测代码、整套知识库或完整数据集。GitCode 页面标为私有且未设置许可证，不能把产品仓库的 Apache-2.0 自动套用到它。

本次只写原创解释、必要的短样本说明和来源链接，没有执行产品或评测。第 31 章中 HNSW/BM25/LightRAG 对比、证据快照、保留集和 Agent 评估是清楚标出的设计建议，不是新增产品功能或已有跑分。

[返回第 26 章](../docs/26-evaluation-overview.md) · [返回首页](../README.md)
