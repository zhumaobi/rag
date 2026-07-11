# hybrid-retrieval Specification

## Purpose

按意图类型执行差异化混合检索：Intent-1 实体定向 Dense+Sparse 融合，Intent-2 并行多路检索，Intent-3 图谱辅助检索，并满足各意图检索质量指标。

## Requirements

### Requirement: Intent-1 精准定向检索
系统 SHALL 对 Intent-1 查询执行实体定向检索：优先在实体对应的 Milvus Collection 中进行 Dense 检索，同时在 ES 中执行 BM25 检索，融合后 Rerank，返回 Top-5 结果。

#### Scenario: 实体命中时缩小检索范围
- **WHEN** 意图识别输出包含有效 collection_id
- **THEN** Dense 检索 SHALL 限定在该 Collection 内，不跨租户、不跨产品扫描

#### Scenario: Dense + Sparse 融合
- **WHEN** 执行 Intent-1 检索
- **THEN** 系统 SHALL 同时执行向量检索和 BM25 检索，用 RRF（Reciprocal Rank Fusion）融合排序，Rerank 后返回 Top-5

### Requirement: Intent-2 并行多路检索
系统 SHALL 对 Intent-2 查询中识别到的多个产品实体并发执行检索，每个产品独立召回 Top-3，不串行执行。

#### Scenario: 并发检索多个产品
- **WHEN** Intent-2 查询包含 N 个产品实体（N ≥ 2）
- **THEN** 系统 SHALL 并发发起 N 路检索，总延迟接近单路检索延迟，不超过单路 1.5 倍

#### Scenario: 多路结果对齐聚合
- **WHEN** N 路检索结果返回
- **THEN** 系统 SHALL 按产品分组排列，保证每个产品至少有 1 条相关结果，送入 LLM 时结构化标注各产品的文档来源

### Requirement: Intent-3 图谱辅助检索
系统 SHALL 对 Intent-3 查询先执行图谱路径查询（最多 3 跳），再结合图谱节点关联的 doc_ids 进行向量补充检索，融合后送入 LLM。

#### Scenario: 图谱路径存在时优先使用
- **WHEN** 两个实体间在知识图谱中存在路径（≤ 3 跳）
- **THEN** 系统 SHALL 提取路径上所有节点的关联 doc_ids，与向量检索结果合并

#### Scenario: 图谱路径不存在时降级
- **WHEN** 图谱中两实体间无路径或实体不存在
- **THEN** 系统 SHALL 降级为纯向量检索，不返回错误，回答中不引用图谱关系

### Requirement: 检索质量指标达标
系统 SHALL 在标注评估集上满足：Intent-1 MRR > 0.80、Recall@5 > 0.88；Intent-2 每产品至少 1 条相关结果占比 > 85%；Intent-3 Recall@5 > 0.82。

#### Scenario: 定期评估不低于基线
- **WHEN** 每次索引更新后执行自动评估
- **THEN** 三类意图的检索指标 SHALL 均不低于基线值，否则阻断索引切换
