## 1. 基础设施搭建

- [x] 1.1 部署 Milvus 集群，配置 Collection Alias 支持，验证 Shadow/Active 切换机制
- [x] 1.2 部署 Elasticsearch 集群，配置 Index Alias，验证 BM25 检索基础功能
- [x] 1.3 部署 Neo4j 实例，配置租户 label 隔离，验证 Cypher N 跳图遍历查询
- [x] 1.4 部署 Redis Cluster，安装 RedisSearch 模块，验证 VSS 向量相似度查询
- [x] 1.5 部署 PostgreSQL，创建文档元数据表（doc_id, tenant_id, content_hash, version, status）
- [x] 1.6 配置对象存储（S3/MinIO），划分原始文档桶和索引快照桶
- [x] 1.7 部署 API Gateway（Kong/Nginx），配置租户鉴权插件和限流规则

## 2. 多租户基础层

- [x] 2.1 实现 JWT/API Key 租户身份解析中间件，tenant_id 注入请求上下文
- [x] 2.2 实现租户 Milvus Collection 自动创建逻辑，大租户独立 Collection，小租户共享
- [x] 2.3 实现租户级 Redis namespace 隔离，格式：`cache:{tenant_id}:{query_hash}`
- [x] 2.4 实现租户级限流配置管理，支持每租户独立 QPS 上限配置
- [x] 2.5 在 Neo4j 所有写入和查询操作中强制添加 tenant_id 过滤

## 3. 离线索引流水线

- [x] 3.1 实现文档摄入模块：从对象存储读取文档，解析 PDF/Word/Markdown，写入 PostgreSQL 元数据
- [x] 3.2 实现 content_hash 变更检测，生成 {新增, 修改, 删除} 变更集，跳过未变更文档
- [x] 3.3 实现文档分块模块：512 tokens 窗口，50 tokens overlap，保留段落边界
- [x] 3.4 实现批量 embedding 任务：动态 batch size，GPU 利用率目标 > 80%，写入 Shadow Milvus Collection
- [x] 3.5 实现 ES BM25 索引构建任务：bulk index 写入 Shadow ES Index
- [x] 3.6 实现 NER 实体识别模块：spaCy + 领域词典，抽取产品名/技术术语
- [x] 3.7 实现 LLM 关系抽取模块：批量调用 LLM 抽取五类预定义关系三元组，输出置信度
- [x] 3.8 实现图谱增量 diff 模块：对比新旧关系集合，精确删除失效边，检测孤立节点
- [x] 3.9 实现图谱写入 Shadow Neo4j，高置信度自动入图，低置信度写入人工审核队列
- [x] 3.10 实现切换前验证：chunk 数量对账 + Top-50 热点 query 检索质量对比
- [x] 3.11 实现三索引原子切换：Milvus Alias 更新 + ES Alias 更新 + Neo4j 事务提交
- [x] 3.12 实现 doc_id → cache_key 反向索引维护和精准缓存失效逻辑
- [x] 3.13 实现流水线状态机：PENDING → PROCESSING → VALIDATING → READY → SWITCHING → DONE，支持回滚
- [x] 3.14 配置定时调度（每日凌晨低峰期），支持手动触发紧急更新

## 4. 意图识别服务

- [x] 4.1 实现规则层：比较词、关系词、时效词正则规则，输出意图和置信度
- [x] 4.2 构建产品实体词典：标准名 + 别名/缩写映射，存入 Redis Hash
- [x] 4.3 实现实体识别模块：查词典匹配，输出实体列表和对应 collection_id
- [x] 4.4 准备 MiniLM 分类器训练数据：500 条三类意图标注样本
- [x] 4.5 Fine-tune MiniLM 三分类模型，在评估集上验证 Accuracy ≥ 92%
- [x] 4.6 实现两阶段识别流程：规则层高置信度直出，低置信度转模型层
- [x] 4.7 封装意图识别服务接口，输出 `{intent, confidence, entities, routing_hint}`
- [x] 4.8 性能测试：验证端到端延迟 < 15ms（P99）

## 5. 混合检索层

- [x] 5.1 实现 Dense 检索模块：按 tenant_id 和 collection_id 定向查询 Milvus，返回 Top-K 向量结果
- [x] 5.2 实现 Sparse 检索模块：ES BM25 检索，支持按 tenant_id 过滤
- [x] 5.3 实现 RRF（Reciprocal Rank Fusion）融合排序
- [x] 5.4 集成 Rerank 模型（Cross-Encoder），对融合结果重排序
- [x] 5.5 实现 Intent-1 定向检索路由：实体命中时限定 Collection，未命中时全局检索
- [x] 5.6 实现 Intent-2 并行多路检索：asyncio 并发 N 路检索，结果按产品分组对齐
- [x] 5.7 实现 Intent-3 图谱辅助检索：Neo4j N 跳路径查询，提取关联 doc_ids，与向量检索融合
- [x] 5.8 实现 Intent-3 图谱降级逻辑：路径不存在时回退纯向量检索

## 6. 语义缓存层

- [x] 6.1 实现 L1 本地内存缓存：LRU 淘汰，每实例约 1000 条
- [x] 6.2 实现 L2 Redis VSS 缓存：embedding 向量存储，cosine 相似度查询
- [x] 6.3 实现缓存命中判断：相似度 > 0.92 命中，时效关键词强制跳过
- [x] 6.4 实现异步缓存写入：LLM 生成完成后后台写入，不阻塞响应
- [x] 6.5 实现 doc_id 反向索引写入：缓存写入时同步更新反向索引
- [x] 6.6 实现缓存命中率实时监控，滚动 1 小时命中率 < 40% 时告警

## 7. LLM 推理层

- [x] 7.1 部署 vLLM serving，配置 Qwen2.5-7B（TP=2，2×A100）和 Qwen2.5-14B（TP=4，4×A100）
- [x] 7.2 配置 vLLM Prefix KV Cache，验证相同租户 System Prompt 前缀命中率
- [x] 7.3 实现全局负载均衡：按 pending_tokens 最少路由，同租户一致性哈希亲和
- [x] 7.4 实现分级模型路由：Intent-1 → 7B 池，Intent-2/3 → 14B 池
- [x] 7.5 实现请求排队超时降级：Intent-1 > 2s 降级，Intent-2 > 5s 降级，Intent-3 > 8s 降级
- [x] 7.6 实现熔断降级链路：L1（实例摘除）→ L2（14B 降级 7B）→ L3（跳过 LLM 返回检索结果）→ L4（返回历史缓存近似答案）
- [x] 7.7 配置预测性扩容 cron：基于历史 QPS 规律，峰值前 30min 预热实例
- [x] 7.8 配置响应式扩容：GPU 显存 > 85% 持续 60s 触发，缩容满足 30% 持续 10min
- [x] 7.9 实现优雅排水：缩容时停止新请求，等待进行中请求完成后下线
- [x] 7.10 性能压测：模拟 5k QPS（缓存未命中场景），验证 P99 < 3s

## 8. 评估体系

- [x] 8.1 构建意图识别 Golden Set：500 条三类意图标注样本，含边界 case
- [x] 8.2 构建检索评估集：300 条 <query, ground-truth doc_ids> 标注对，覆盖三类意图
- [x] 8.3 构建端到端 Golden Set：200 条标准问题 + 参考答案
- [x] 8.4 集成 RAGAs 框架，实现 Faithfulness、Answer Relevance、Context Utilization 自动计算
- [x] 8.5 实现 Intent-2 对称性检查：自动检测比较分析回答的产品覆盖维度是否对称
- [x] 8.6 实现用户隐式反馈采集：点击来源、复制文本、否定反馈事件埋点
- [x] 8.7 实现每日自动评估流水线：采样前日 1000 条请求，运行 L1-L3 评估，推送报告
- [x] 8.8 实现 CI 发布门禁：Golden Set 全量评估，任意指标回归 > 2% 阻断发布
- [x] 8.9 实现图谱抽取质量定期评估：在标注文档集上计算实体 Precision/Recall 和关系抽取准确率

## 9. 监控与可观测性

- [x] 9.1 接入统一监控（Prometheus + Grafana），配置 GPU 显存利用率、KV Cache 命中率仪表板
- [x] 9.2 配置请求链路追踪（OpenTelemetry），覆盖意图识别 → 检索 → LLM 全链路
- [x] 9.3 配置告警规则：P99 > 3s、缓存命中率 < 40%、否定反馈率 > 5%、图谱抽取质量低于阈值
- [x] 9.4 实现流水线运行状态看板：各 Stage 耗时、成功率、失败原因分类

## 10. 集成测试与上线

- [x] 10.1 端到端集成测试：三类意图各 50 条用例，验证完整链路正确性
- [x] 10.2 多租户隔离测试：验证跨租户数据不可见，图谱查询无越界
- [x] 10.3 故障注入测试：模拟 LLM 实例故障、Redis 不可用、Milvus 超时，验证降级链路
- [x] 10.4 性能压测：10k QPS 峰值压测，验证各层延迟和错误率达标
- [x] 10.5 灰度上线：10% 流量切入，观察 L1-L4 指标 48 小时
- [x] 10.6 全量上线：逐步放量至 100%，保留快速回滚能力
