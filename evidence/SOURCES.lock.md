# AsterRAG 教程来源锁

> 创建日期：2026-09-01  
> 工作区：私有远程教程工作区  
> 规则：本文件记录教程事实来源的固定身份。写作期间不得静默移动任何锁定提交。

## 1. 教程产品源码：AsterRAG

- 用途：教程实现事实的最高权威。
- 远程仓库：`https://github.com/zz1403489227-crypto/AsterRAG.git`
- 本地路径：`sources/AsterRAG`
- HEAD：`98894c2c42c015a3c874c6b3c986ac863c85b731`
- Tree：`19b1702464b756670138554e70894ede5ba4198a`
- Checkout：detached HEAD
- 初始工作树：clean
- 写入策略：只读分析；教程开发不得修改该工作树。

归属文件校验：

| 文件 | SHA-256 |
|---|---|
| `LICENSE` | `27f545e67602d343f9e8db9fff7f8b4819e7a31829f9fab0ee94a7cf013b2565` |
| `NOTICE` | `2777a93e892c04ea87af552e523b904a7526d7f3fe9d8ed2b9aa7e847272f8b6` |
| `docs/UPSTREAM.md` | `718a86fa60258a9d918bd8877350994717770f4884127bfbce67446ade88f249` |

## 2. 上游来源：nageoffer/ragent

- 用途：核对上游历史、原始实现、作者课程版本和二次开发归属。
- 远程仓库：`https://github.com/nageoffer/ragent.git`
- 本地路径：`sources/ragent-upstream`
- 当前上游基线 HEAD：`1cb684ed5df03f241d90c836466465f6aab37800`
- Tree：`1fb1efdf6595f2406cc4822544d5819a09565864`
- Checkout：detached HEAD
- 初始工作树：clean
- Ragent `1.0.0` tag commit：`5500546c4e4742752adaaebf51c9423bef5f3497`
- Ragent `1.0.0` tag tree：`2131df47c496b4ca0abeb238b3d251bd8b0b8567`
- 写入策略：只读参考；不作为 AsterRAG 当前行为的替代证据。

## 3. 教学设计参考：how-claude-code-works

- 用途：只借鉴总体架构先行、专题导航、快速阅读路径、主循环讲解和章节桥接方式。
- 远程仓库：`https://github.com/Windy3f3f3f3f/how-claude-code-works.git`
- 本地路径：`sources/how-claude-code-works`
- HEAD：`f4d6505ed9162a0ee6be089190f74c419ecacb19`
- Tree：`36e3674cf0162e1d0547bca62e23eeef56edfd52`
- Checkout：detached HEAD
- 初始工作树：clean
- 写入策略：只读参考；其中任何 Claude Code 机制都不是 AsterRAG 实现事实。

## 4. 作者教程

### 4.1 公开站点

- URL：`https://nageoffer.com/ragent/`
- 访问日期：2026-09-01
- 用途：作者公开的系统定位、设计动机、课程结构和背景概念。
- 限制：具体模块、版本、接口和调用顺序必须回到 AsterRAG 冻结源码核验。

### 4.2 知识星球专栏

- URL：`https://wx.zsxq.com/columns/51121244585524?column_id=281884884411`
- 访问日期：2026-09-01
- 用途：课程目录、讲解重点和作者版本说明。
- 已记录版本提示：页面 2026-08-12 更新说明称课程资料以 `1.0.0` 分支为准，项目结构和功能正在继续演进。
- 限制：仅在用户已有访问权限的页面内阅读；不复制受限文章正文、图片或评论，不将其打包进教程仓库。

## 5. 冲突裁决

1. AsterRAG 冻结源码、Schema、配置绑定和测试代码优先。
2. 当前环境的真实构建/测试/运行证据只证明对应环境和路径，不自动外推到所有配置。
3. AsterRAG 自带说明用于定位，但精确事实仍由源码确认。
4. 作者教程用于解释动机和背景；与当前源码冲突时必须标注版本差异。
5. `how-claude-code-works` 只影响教程组织，不增加任何 AsterRAG 产品能力。

## 6. 漂移检查命令

```bash
for repo in AsterRAG ragent-upstream how-claude-code-works; do
  git -C "sources/$repo" rev-parse HEAD
  git -C "sources/$repo" rev-parse 'HEAD^{tree}'
  git -C "sources/$repo" status --short
done
```

预期：HEAD/tree 与本文件一致，三个 `status --short` 均无输出。

## 7. 评测篇：RagentEval 与 RAGAS

- 官方评测项目：[nageoffer/ragenteval](https://gitcode.net/nageoffer/ragenteval)。
- 授权浏览器阅读日期：2026-09-08。
- 页面永久链接对应提交：`9d69c63cdca0bf730d8900c3076e0480e541360c`。
- 用途：第 26～31 章的评估数据、录制器、评分器与报告机制。
- 访问方式：已有授权网页，不提取会话凭据；未将原仓源码或完整评估集加入教程仓库。
- 归属：页面为私有、未设置许可证，产品仓库的 Apache-2.0 不自动适用于评测仓库。教程使用独立解释及必要短样本说明，保留出处。
- 原理补充：RAGAS 官方 v0.2.14 指标文档与相应标签源码；只用作算法解释参考，不推断实际安装版本。
- 索引：[evaluation-source-map.md](evaluation-source-map.md)。
- 写作边界：不运行评测，不上传输入材料给模型裁判，不声称已有实测成绩。

## 8. 第 45 章学习问答的上游差异对照

- 访问日期：2026-09-11。
- 对照仓库：`https://github.com/nageoffer/ragent`。
- 固定提交：`ca93991abe4ffd838e48d600d7ada24e010a884f`。
- 范围：AgentChatController、AgentStreamEventBridge、AgentSSEEventType、useAgentStream.ts、根 pom.xml 五个文件。
- 用途：解释聊天回答涉及的工具确认、新 POST SSE、错误收尾与客户端重试变化。
- 本项不改变第 1 节 AsterRAG 主实现基线，也不覆盖第 2 节同源历史锁；不把对照能力迁入产品。
- 核对记录：[request-study-source-review.md](request-study-source-review.md)，逐文件 SHA-256：[request-study-source-map.json](request-study-source-map.json)。
