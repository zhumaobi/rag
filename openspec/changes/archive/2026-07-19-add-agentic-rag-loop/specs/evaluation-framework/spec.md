## MODIFIED Requirements

### Requirement: 生成质量评估（L3）

系统 SHALL 集成 RAGAs 框架，对每次回答自动计算 Faithfulness（≥ 0.90）、Answer Relevance（≥ 0.85）、Context Utilization（≥ 0.60）三项指标。除既有的离线评估外，对于已启用 Agentic RAG 的 `(tenant, intent)` 组合，系统 SHALL 在查询路径内同步调用 RAGAs 的 Faithfulness 与 Answer Relevance 作为在线质量门禁；Context Utilization SHALL 保持仅离线评估（在线缺少 ground truth）。低于阈值的候选回答 SHALL 触发 Agentic 重写循环，并记录到低质量样本库。

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
