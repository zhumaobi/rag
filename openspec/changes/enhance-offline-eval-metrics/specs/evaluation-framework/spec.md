## MODIFIED Requirements

### Requirement: 生成质量评估（L3）
系统 SHALL 集成 RAGAs 框架，对每次回答自动计算 Faithfulness（≥ 0.90）、Answer Relevance（≥ 0.85）、Context Utilization（≥ 0.60）三项指标。系统 SHALL  additionally 计算 Answer Similarity（生成回答与参考答案的余弦相似度）和 Key-Point Coverage（回答对关键得分点的覆盖率，embedding 模式 ≥ 0.80）作为 L3 补充指标。除既有的离线评估外，对于已启用 Agentic RAG 的 `(tenant, intent)` 组合，系统 SHALL 在查询路径内同步调用 RAGAs 的 Faithfulness 与 Answer Relevance 作为在线质量门禁；Context Utilization SHALL 保持仅离线评估（在线缺少 ground truth）。低于阈值的候选回答 SHALL 触发 Agentic 重写循环，并记录到低质量样本库。

#### Scenario: Faithfulness 自动检测幻觉
- **WHEN** LLM 生成回答后
- **THEN** 系统 SHALL 计算 Faithfulness 分数，低于 0.90 的回答 SHALL 记录到低质量样本库供分析

#### Scenario: Intent-2 对称性检查
- **WHEN** 生成 Intent-2 比较分析回答后
- **THEN** 系统 SHALL 检查回答对每个产品的覆盖维度是否对称，不对称时记录为质量问题

#### Scenario: 在线质量门禁触发重写
- **WHEN** 已启用 Agentic RAG 的请求生成候选回答后
- **THEN** 系统 SHALL 同步计算 Faithfulness 与 Answer Relevance，任一低于阈值时在预算内触发 HyDE 重写与重新检索
- **AND** Context Utilization 不参与在线门禁判定

#### Scenario: 在线门禁复用离线阈值
- **WHEN** 在线质量门禁评估候选回答
- **THEN** 系统 SHALL 使用与离线一致的阈值 Faithfulness ≥ 0.90、Answer Relevance ≥ 0.85

#### Scenario: Key-Point Coverage 离线评估
- **WHEN** 离线评估处理含有 key_points 的黄金集样本时
- **THEN** 系统 SHALL 使用 embedding 模式计算关键得分点覆盖率，均值低于 0.80 时报告失败

#### Scenario: Answer Similarity 离线评估
- **WHEN** 离线评估处理含有 reference_answer 的黄金集样本时
- **THEN** 系统 SHALL 计算生成回答与参考答案的余弦相似度并纳入 L3 报告

### Requirement: 检索质量评估（L2）
系统 SHALL 维护标注了 ground-truth 文档的检索评估集（冷启动 300 条，持续扩充），按三类意图分别计算 MRR、Recall@K、NDCG@K。系统 SHALL additionally 在 Nightly 评估层计算 Context Precision@K（基于 LLM 判定的 chunk 级相关性），按意图分别报告，并将判定结果导出为重排序模型微调训练数据。

#### Scenario: 三类意图分别评估
- **WHEN** 执行 L2 检索评估
- **THEN** 系统 SHALL 输出 Intent-1/2/3 各自的 MRR、Recall@5、NDCG@5，不合并为单一指标

#### Scenario: 隐式反馈扩充评估集
- **WHEN** 用户点击引用来源或复制文本
- **THEN** 系统 SHALL 将该 <query, doc_id> 对记录为弱正样本，定期人工抽查后加入评估集

#### Scenario: Context Precision 按意图评估
- **WHEN** 执行 Nightly 层 L2 评估
- **THEN** 系统 SHALL 对每个 golden 样本的 top-K 检索结果逐 chunk 判定相关性，按意图分别计算 CP@K 均值

#### Scenario: 重排序训练数据导出
- **WHEN** Context Precision 评估完成
- **THEN** 系统 SHALL 将 (query, chunk, relevance, reranker_score) 记录导出为 JSONL 格式训练数据，标记 hard negative 样本

## ADDED Requirements

### Requirement: 评估执行分层（CI / Nightly）
系统 SHALL 将离线评估分为两个执行层：CI 层（每次构建，< 2 分钟，无 LLM 依赖）和 Nightly 层（定时/按需，含 LLM 判定指标）。CI 层 SHALL 包含 L1 意图、L2 检索（MRR/Recall/NDCG）、Key-Point Coverage（embedding 模式）、Answer Similarity。Nightly 层 SHALL 额外包含 RAGAs 全套、Answer Correctness、Context Precision、NLI Key-Point 模式、Agentic Efficiency Report、KG 评估。

#### Scenario: CI 层无 LLM 调用
- **WHEN** 评估以 CI 层模式运行
- **THEN** 系统 SHALL 仅执行确定性计算（embedding 相似度、排序指标），不发起任何 LLM 推理请求

#### Scenario: Nightly 层包含全部指标
- **WHEN** 评估以 Nightly 层模式运行
- **THEN** 系统 SHALL 执行 CI 层全部指标并额外执行所有 LLM 判定指标

#### Scenario: 发布门禁引用两层结果
- **WHEN** 版本发布门禁评估时
- **THEN** 系统 SHALL 使用最近一次 CI 层结果加上最近一次 Nightly 层结果进行综合判定
