# llm-serving Specification

## Purpose

分级模型池（7B/14B）按意图路由、同租户亲和路由复用 KV Cache、排队超时降级、弹性伸缩，并满足端到端延迟 SLA。

## Requirements

### Requirement: 分级模型池路由
系统 SHALL 维护独立的 7B 模型池（处理 Intent-1）和 14B 模型池（处理 Intent-2/3），根据意图识别结果路由，两个池资源独立，互不影响。

#### Scenario: Intent-1 路由到 7B 池
- **WHEN** 请求意图为 Intent-1
- **THEN** 系统 SHALL 将请求路由到 7B 模型池，不经过 14B 池

#### Scenario: 14B 池满载时降级
- **WHEN** 14B 池队列深度超过阈值或等待时间 > 5s
- **THEN** 系统 SHALL 将 Intent-2/3 请求临时降级路由到 7B 池，回答中不标注降级

### Requirement: 同租户请求亲和路由
系统 SHALL 通过一致性哈希（hash(tenant_id) % N）将同一租户的请求优先路由到同一 vLLM 实例，最大化 Prefix KV Cache 命中率。

#### Scenario: 同租户复用 KV Cache
- **WHEN** 同一租户的连续请求到达
- **THEN** 系统 SHALL 路由到同一实例，System Prompt 和租户指令前缀（约 300 tokens）的 KV Cache 命中率 SHALL ≥ 80%

#### Scenario: 亲和实例故障时重路由
- **WHEN** 目标实例不健康
- **THEN** 系统 SHALL 路由到 pending_tokens 最少的健康实例，不等待故障实例恢复

### Requirement: 请求排队超时降级
系统 SHALL 对不同意图设置差异化的排队超时阈值，超时后执行对应的降级策略，保证服务可用性。

#### Scenario: Intent-1 排队超时降级
- **WHEN** Intent-1 请求在 7B 池排队超过 2s
- **THEN** 系统 SHALL 降级返回 Top-3 检索结果，不等待 LLM 生成

#### Scenario: Intent-3 排队超时降级
- **WHEN** Intent-3 请求排队超过 8s
- **THEN** 系统 SHALL 跳过图谱部分，降级为纯向量检索结果送入 LLM

### Requirement: 弹性伸缩
系统 SHALL 支持预测性扩容（基于历史 QPS 规律提前 30min 预热）和响应式扩容（GPU 显存利用率 > 85% 持续 60s 触发），缩容前执行优雅排水。

#### Scenario: 峰值前预热扩容
- **WHEN** 距历史峰值时间 30 分钟
- **THEN** 系统 SHALL 预启动额外实例，模型加载完成后加入负载均衡池

#### Scenario: 缩容优雅排水
- **WHEN** GPU 利用率 < 30% 持续 10 分钟，触发缩容
- **THEN** 系统 SHALL 停止向目标实例发送新请求，等待进行中请求全部完成后再下线实例

### Requirement: 延迟 SLA
系统 SHALL 在正常负载下满足：P50 < 800ms，P95 < 2s，P99 < 3s（端到端，含检索和 LLM 生成）。

#### Scenario: 持续监控延迟分位
- **WHEN** 系统运行时
- **THEN** 监控系统 SHALL 持续采集 P50/P95/P99 延迟，P99 > 3s 持续 30s 时触发告警
