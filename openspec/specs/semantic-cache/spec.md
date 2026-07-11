# semantic-cache Specification

## Purpose

基于 embedding 语义相似度的两级缓存（本地 L1 + Redis L2），命中时低延迟返回缓存答案，异步写入并维护 doc_id 反向索引，达成整体命中率目标。

## Requirements

### Requirement: 语义相似度缓存匹配
系统 SHALL 对每个入站查询计算 embedding，在 Redis VSS 中检索相似度最高的缓存条目，cosine 相似度 > 0.92 时视为命中，直接返回缓存答案。

#### Scenario: 语义等价问法命中缓存
- **WHEN** 用户查询与已缓存查询语义相似度 > 0.92
- **THEN** 系统 SHALL 直接返回缓存答案，延迟 < 10ms，不触发检索和 LLM 调用

#### Scenario: 时效敏感查询强制跳过缓存
- **WHEN** 查询包含"最新"、"当前版本"、"今天"等时效关键词
- **THEN** 系统 SHALL 强制跳过缓存，执行完整 RAG 流程

### Requirement: 两级缓存层次
系统 SHALL 维护本地内存缓存（L1，每实例约 1000 条，LRU 淘汰）和 Redis 集群缓存（L2，按租户 namespace 隔离），L1 未命中后查 L2，L2 未命中后执行完整流程。

#### Scenario: L1 命中极低延迟返回
- **WHEN** 查询命中本地内存缓存
- **THEN** 系统 SHALL 在 < 1ms 内返回，不访问 Redis

#### Scenario: 按租户 namespace 隔离
- **WHEN** 不同租户的相同查询到达
- **THEN** 系统 SHALL 在各自 namespace 下独立缓存，不共享缓存条目，不存在跨租户数据泄露

### Requirement: 缓存写入与 TTL
系统 SHALL 在 LLM 生成完成后异步写入语义缓存，TTL 为 24 小时，不阻塞响应返回。同时维护 doc_id → cache_key 反向索引。

#### Scenario: 异步写入不影响响应延迟
- **WHEN** LLM 生成完成
- **THEN** 系统 SHALL 立即返回响应给用户，缓存写入在后台异步执行

#### Scenario: 写入时更新反向索引
- **WHEN** 新缓存条目写入 L2
- **THEN** 系统 SHALL 同时更新该答案涉及的所有 doc_id 的反向索引集合

### Requirement: 整体缓存命中率目标
系统 SHALL 在稳态下维持语义缓存命中率 ≥ 50%，低于 40% 持续 1 小时时触发告警排查。

#### Scenario: 命中率持续监控
- **WHEN** 系统运行时
- **THEN** 监控系统 SHALL 每分钟计算滚动 1 小时命中率，低于 40% 时触发告警
