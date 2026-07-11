## ADDED Requirements

### Requirement: 租户身份解析与路由
系统 SHALL 在 API Gateway 层解析每个请求的租户身份（通过 JWT 或 API Key），注入 tenant_id 到请求上下文，后续所有组件使用此 tenant_id 做数据隔离。

#### Scenario: 无效租户身份拒绝请求
- **WHEN** 请求缺少有效的租户凭证
- **THEN** 系统 SHALL 返回 401，不进入 RAG 流程

#### Scenario: tenant_id 全链路传递
- **WHEN** 请求通过鉴权
- **THEN** tenant_id SHALL 在意图识别、检索、LLM、缓存各层全程携带，不丢失

---

### Requirement: 向量存储按租户独立 Collection
系统 SHALL 为每个租户在 Milvus 中维护独立的 Collection，Collection 命名规范为 `tenant_{id}_v{version}`，通过 Alias 指向 Active 版本。文档数量低于 1000 的小租户 SHALL 共享一个 Collection 并添加 tenant_id 字段过滤。

#### Scenario: 大租户独立 Collection 查询
- **WHEN** 大租户（文档数 ≥ 1000）发起检索
- **THEN** 系统 SHALL 仅在该租户的专属 Collection 中检索，不扫描其他租户数据

#### Scenario: 小租户共享 Collection 隔离
- **WHEN** 小租户（文档数 < 1000）发起检索
- **THEN** 系统 SHALL 在共享 Collection 中附加 `tenant_id == X` 过滤条件，确保结果仅包含本租户数据

---

### Requirement: 租户级限流
系统 SHALL 对每个租户独立限流，防止单租户流量峰值影响其他租户，默认每租户 QPS 上限可配置。

#### Scenario: 单租户超限时限流
- **WHEN** 某租户 QPS 超过其配置上限
- **THEN** 系统 SHALL 对该租户返回 429，不影响其他租户的正常请求

---

### Requirement: 知识图谱租户隔离
系统 SHALL 在 Neo4j 中为每个租户的节点和关系添加 tenant_id 属性，所有图遍历查询 SHALL 携带 tenant_id 过滤，不返回跨租户节点。

#### Scenario: 图遍历严格租户隔离
- **WHEN** 执行 Intent-3 图遍历查询
- **THEN** Cypher 查询 SHALL 包含 `WHERE n.tenant_id = $tenant_id` 条件，返回结果不包含其他租户节点
