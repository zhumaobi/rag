## Why

企业内部知识库缺乏智能检索能力，员工在多个产品文档、术语库和知识系统间手动查找信息，效率低下且答案质量不稳定。需要构建一个支持 10k QPS、PB 级多租户文档检索的生产级 RAG 系统，通过意图识别驱动差异化检索策略，提供准确、可溯源的知识问答能力。

## What Changes

- 新增意图识别服务，将查询分为三类：`Intent-1: 精准产品问答`、`Intent-2: 多产品比较分析`、`Intent-3: 概念关系澄清`
- 新增混合检索层，融合 BM25 稀疏检索与 Dense 向量检索，针对三类意图采用不同检索策略
- 新增知识图谱模块，从文档自动抽取实体关系，支持 Intent-3 图遍历查询
- 新增离线索引流水线，支持批量文档更新、Shadow 索引构建与零停机原子切换
- 新增分级 LLM 推理层，Intent-1 路由 7B 模型，Intent-2/3 路由 14B 模型，基于 vLLM 私有化部署
- 新增两级语义缓存（本地 + Redis），目标命中率 50%，批量更新后精准失效
- 新增多租户隔离架构，按租户分 Milvus Collection，共享 ES 集群加字段过滤
- 新增四层评估体系（组件/检索/生成/业务），驱动持续迭代

## Capabilities

### New Capabilities

- `intent-recognition`: 两阶段意图识别——规则层 + MiniLM 分类器，识别三类意图及实体，延迟 < 15ms
- `hybrid-retrieval`: Sparse（BM25/ES）+ Dense（Milvus HNSW）混合检索，按意图差异化召回策略
- `knowledge-graph`: 离线自动抽取实体关系，构建产品知识图谱，支持 N 跳图遍历查询
- `offline-index-pipeline`: 文档变更检测、并行索引构建、Shadow/Active 双集合零停机切换、精准缓存失效
- `llm-serving`: vLLM 集群，分级模型池（7B/14B），Prefix KV Cache、连续批处理、弹性伸缩、熔断降级
- `semantic-cache`: 基于 embedding 相似度的两级语义缓存，按租户隔离，与索引更新联动失效
- `multi-tenant`: 租户路由、数据隔离、按租户分 Collection 的向量存储架构
- `evaluation-framework`: 四层评估体系，覆盖意图识别、图谱抽取、检索质量、生成质量、端到端业务指标

### Modified Capabilities

（无现有能力，全新系统）

## Impact

- **基础设施依赖**: Milvus（向量存储）、Elasticsearch（BM25）、Neo4j（知识图谱）、Redis Cluster（语义缓存）、PostgreSQL（元数据）、对象存储 S3/MinIO（原始文档）
- **LLM 部署**: vLLM serving，Qwen2.5-7B × N 卡（Intent-1 池）+ Qwen2.5-14B × M 卡（Intent-2/3 池），需 A100/H100 GPU 集群
- **API 层**: Kong/Nginx Gateway，承载 10k QPS，含限流、鉴权、租户解析
- **离线计算**: 批量 embedding GPU 任务、LLM 关系抽取任务，与在线服务资源隔离
- **评估系统**: RAGAs 集成，CI 每日自动跑评估，Golden Set 300 条人工标注
