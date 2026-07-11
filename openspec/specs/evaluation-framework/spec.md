# evaluation-framework Specification

## Purpose

分层评估体系：L1 意图识别、L2 检索质量、L3 生成质量（RAGAs）、L4 端到端业务指标，以及版本发布评估门禁。

## Requirements

### Requirement: 意图识别组件评估
系统 SHALL 维护 500 条人工标注的意图分类评估集，在每次模型更新后自动评估，Accuracy ≥ 92%、每类 F1 ≥ 0.90 为发布门禁。

#### Scenario: 意图分类评估自动化
- **WHEN** 意图识别模型或规则更新后
- **THEN** 系统 SHALL 自动在评估集上运行评估，低于阈值阻断发布

### Requirement: 检索质量评估（L2）
系统 SHALL 维护标注了 ground-truth 文档的检索评估集（冷启动 300 条，持续扩充），按三类意图分别计算 MRR、Recall@K、NDCG@K。

#### Scenario: 三类意图分别评估
- **WHEN** 执行 L2 检索评估
- **THEN** 系统 SHALL 输出 Intent-1/2/3 各自的 MRR、Recall@5、NDCG@5，不合并为单一指标

#### Scenario: 隐式反馈扩充评估集
- **WHEN** 用户点击引用来源或复制文本
- **THEN** 系统 SHALL 将该 <query, doc_id> 对记录为弱正样本，定期人工抽查后加入评估集

### Requirement: 生成质量评估（L3）
系统 SHALL 集成 RAGAs 框架，对每次回答自动计算 Faithfulness（≥ 0.90）、Answer Relevance（≥ 0.85）、Context Utilization（≥ 0.60）三项指标。

#### Scenario: Faithfulness 自动检测幻觉
- **WHEN** LLM 生成回答后
- **THEN** 系统 SHALL 异步计算 Faithfulness 分数，低于 0.90 的回答 SHALL 记录到低质量样本库供分析

#### Scenario: Intent-2 对称性检查
- **WHEN** 生成 Intent-2 比较分析回答后
- **THEN** 系统 SHALL 检查回答对每个产品的覆盖维度是否对称，不对称时记录为质量问题

### Requirement: 端到端业务指标监控（L4）
系统 SHALL 实时采集会话解决率、用户否定反馈率、追问率、引用点击率四项业务指标，否定反馈率 > 5% 持续 1 小时触发人工介入告警。

#### Scenario: 否定反馈实时告警
- **WHEN** 否定反馈率（"这不对"/"没帮助"类）在滚动 1 小时内超过 5%
- **THEN** 系统 SHALL 触发告警通知，同时自动采样该时段低分回答供根因分析

### Requirement: 版本发布评估门禁
系统 SHALL 在每次版本发布前，在 Golden Set（200 条人工标注标准问题）上运行全量评估，端到端准确率 ≥ 85%，任意 L1-L4 指标相比基线下降 > 2% 则阻断发布。

#### Scenario: 回归检测阻断发布
- **WHEN** 新版本提交发布
- **THEN** CI 系统 SHALL 自动运行 Golden Set 评估，任意指标回归超过 2% 时阻断，输出对比报告

#### Scenario: 每日自动评估
- **WHEN** 每日凌晨定时触发
- **THEN** 系统 SHALL 对前一天 1000 条真实请求样本运行 L1-L3 自动评估，生成报告推送团队
