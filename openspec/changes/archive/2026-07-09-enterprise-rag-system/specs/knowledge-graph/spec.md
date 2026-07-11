## ADDED Requirements

### Requirement: 离线实体和关系自动抽取
系统 SHALL 在批量索引流水线中自动从文档 chunks 抽取实体（NER）和预定义类型的关系三元组（头实体, 关系类型, 尾实体），关系类型限定为：属于、依赖、替代、集成、概念解释。

#### Scenario: 高置信度关系自动入图
- **WHEN** LLM 抽取关系三元组置信度 ≥ 0.85
- **THEN** 系统 SHALL 自动写入 Shadow 图谱，无需人工介入

#### Scenario: 低置信度关系进入审核队列
- **WHEN** 关系三元组置信度 < 0.85
- **THEN** 系统 SHALL 将其写入人工审核队列，不自动入图，等待人工确认

---

### Requirement: 图谱增量更新与冲突处理
系统 SHALL 在文档更新时重新抽取受影响文档的关系，与现有图谱做 diff，删除失效边、添加新边，并检测孤立节点决定是否删除。

#### Scenario: 关系变更时精确 diff
- **WHEN** 文档修改导致关系三元组变化
- **THEN** 系统 SHALL 仅删除失效的边，不重建整个子图；若节点仍有其他引用则保留节点

#### Scenario: 孤立节点清理
- **WHEN** 删除边后某节点无任何引用
- **THEN** 系统 SHALL 删除该孤立节点

---

### Requirement: 图节点关联向量索引
每个图谱节点 SHALL 存储节点描述的 embedding 向量及关联的 doc_ids 列表，支持在图遍历后快速定位关联文档 chunks。

#### Scenario: 图遍历后直接获取文档
- **WHEN** 图谱路径查询返回节点集合
- **THEN** 系统 SHALL 直接从节点的 doc_ids 字段获取关联文档，不需要二次检索

---

### Requirement: 图谱抽取质量达标
系统 SHALL 在人工标注的 50 篇文档评估集上满足：实体识别 Precision > 90%、Recall > 85%；关系抽取宽松匹配 Precision > 85%、精确匹配 > 75%。

#### Scenario: 定期质量评估
- **WHEN** 每次批量更新完成后
- **THEN** 系统 SHALL 自动在评估集上计算图谱抽取指标，低于阈值触发告警
