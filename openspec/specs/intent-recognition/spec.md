# intent-recognition Specification

## Purpose

两阶段（规则层 + MiniLM 模型层）识别查询意图，输出结构化路由信息供下游检索层消费，并识别产品实体映射到标准名与 Collection ID。

## Requirements

### Requirement: 两阶段意图分类
系统 SHALL 通过规则层（正则 + 关键词匹配）和 MiniLM 分类器两阶段识别查询意图，总延迟 SHALL 不超过 15ms。规则层置信度高时直接输出，低置信度时进入模型层。

#### Scenario: 规则层直接命中比较意图
- **WHEN** 查询包含"对比"、"区别"、"vs"、"哪个更好"等比较关键词
- **THEN** 系统 SHALL 直接分类为 Intent-2，跳过模型层，延迟 < 1ms

#### Scenario: 模型层处理边界查询
- **WHEN** 规则层置信度低于阈值（< 0.85）
- **THEN** 系统 SHALL 将查询送入 MiniLM 分类器，返回意图类型和置信度，延迟 < 15ms

#### Scenario: 整体分类准确率达标
- **WHEN** 在 500 条人工标注测试集上评估
- **THEN** 整体 Accuracy SHALL ≥ 92%，每类 F1 SHALL ≥ 0.90

### Requirement: 产品实体识别
系统 SHALL 从查询中识别产品名、技术术语等实体，与预维护的产品实体词典（存储于 Redis）匹配，输出标准化实体列表及对应 Collection ID。

#### Scenario: 别名映射到标准名
- **WHEN** 查询包含产品别名或缩写
- **THEN** 系统 SHALL 将其映射到标准产品名，并返回对应的 collection_id

#### Scenario: 未知实体处理
- **WHEN** 查询中实体未命中词典
- **THEN** 系统 SHALL 回退到全局检索，不返回错误

### Requirement: 意图识别输出结构
系统 SHALL 输出结构化结果：`{intent: Intent-1|2|3, confidence: float, entities: [{name, collection_id}], routing_hint: string}`，供下游检索层消费。

#### Scenario: 输出完整路由信息
- **WHEN** 意图识别完成
- **THEN** 输出 SHALL 包含 intent 类型、置信度、识别到的实体列表及路由提示，下游无需二次解析
