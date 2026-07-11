# offline-index-pipeline Specification

## Purpose

批量索引流水线：文档变更检测、三索引并行构建、Shadow/Active 原子切换、切换前质量验证与精准缓存失效联动。

## Requirements

### Requirement: 文档变更检测
系统 SHALL 通过 content_hash 对比检测新增、修改、删除三类变更，跳过未变更文档，不重复计算 embedding。

#### Scenario: 未变更文档跳过处理
- **WHEN** 文档 content_hash 与已索引版本一致
- **THEN** 系统 SHALL 跳过该文档的所有处理步骤，不消耗 GPU 资源

#### Scenario: 删除文档延迟清理
- **WHEN** 文档标记为 deleted
- **THEN** 系统 SHALL 在 Shadow 索引中标记删除，切换后旧索引保留 24h 再物理删除

### Requirement: 三索引并行构建
系统 SHALL 并行构建向量索引（Milvus）、BM25 索引（Elasticsearch）和知识图谱（Neo4j），三者写入各自的 Shadow 目标，互不阻塞。

#### Scenario: 并行构建不相互依赖
- **WHEN** 文档处理完成后进入索引构建阶段
- **THEN** 三个索引构建任务 SHALL 并行启动，不等待彼此完成

#### Scenario: 任意索引构建失败整体回滚
- **WHEN** 三个索引中任意一个构建失败或验证未通过
- **THEN** 系统 SHALL 整体回滚，保留旧 Active 索引继续服务，不进行切换

### Requirement: Shadow/Active 原子切换
系统 SHALL 通过 Milvus Collection Alias 实现向量索引的原子切换，切换操作延迟 < 1ms，切换期间查询不中断。

#### Scenario: 验证通过后原子切换
- **WHEN** 三个索引全部构建完成且验证通过
- **THEN** 系统 SHALL 更新 Milvus Alias、ES 别名指向新索引，原子操作完成，切换过程中无请求失败

#### Scenario: 旧索引保留回滚窗口
- **WHEN** 切换完成后
- **THEN** 旧版本索引 SHALL 保留 24 小时，期间可一键回滚

### Requirement: 切换前质量验证
系统 SHALL 在切换前对新索引执行自动验证：chunk 数量对账、Top-50 热点 query 抽样检索质量检查，低于基线则阻断切换。

#### Scenario: 数量对账异常阻断切换
- **WHEN** 新索引 chunk 数量与预期差异 > 5%
- **THEN** 系统 SHALL 阻断切换并告警，不自动切换

#### Scenario: 抽样检索质量检查
- **WHEN** 执行切换前验证
- **THEN** 系统 SHALL 用上周 Top-50 热点 query 在新索引上执行检索，各项指标不低于旧索引基线

### Requirement: 精准缓存失效联动
系统 SHALL 在切换完成后，通过 doc_id → cache_key 反向索引精准失效与变更文档相关的语义缓存条目，不全量清空缓存。

#### Scenario: 只失效相关缓存
- **WHEN** 批量更新切换完成
- **THEN** 系统 SHALL 查询变更文档的反向索引，仅删除关联的 cache key，其余缓存条目保持有效
