# 企业级 RAG 系统

一个面向多租户的企业知识库检索增强生成（RAG）系统，覆盖从**离线索引构建**到**在线查询服务**的完整链路，并内置意图识别、混合检索、知识图谱、语义缓存、分级 LLM 服务、可观测性与评估框架。

> **关于本项目**：这是一个个人 vibe coding 项目，采用 **SDD（Spec-Driven Development，规范驱动开发）** 方式构建——先写规范（spec），再由规范驱动实现。整个项目从 0 到全流程打通并上线，**仅用了三天**。

---

## 目录

- [核心特性](#核心特性)
- [详细文档（Wiki）](#详细文档wiki)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [环境准备](#环境准备)
- [快速开始](#快速开始)
- [使用指南](#使用指南)
  - [1. 启动基础设施](#1-启动基础设施)
  - [2. 训练意图分类器](#2-训练意图分类器)
  - [3. 上传文档并构建索引](#3-上传文档并构建索引)
  - [4. 运行查询](#4-运行查询)
  - [5. 评估与压测](#5-评估与压测)
- [配置说明](#配置说明)
- [常见问题](#常见问题)
- [后续优化 Roadmap / TODO](#后续优化-roadmap--todo)

---

## 核心特性

- **两阶段意图识别**：规则层（正则，<1ms，命中即短路）+ MiniLM 嵌入 + 逻辑回归分类器，三分类（精确问答 / 多产品对比 / 关系解释）。
- **意图路由的混合检索**：稠密向量（Milvus）+ 稀疏 BM25（Elasticsearch）→ RRF 融合 → Cross-Encoder 重排；关系类查询额外走 Neo4j 知识图谱多跳检索。
- **两级语义缓存**：L1 内存 LRU + L2 Redis 向量相似检索（HNSW），并维护 `doc_id → cache_key` 反向索引以支持精确失效。
- **分级 LLM 服务与降级链**：7B / 14B 双资源池 + 一致性哈希租户亲和 + 前缀 KV 缓存复用；四级降级（L1 熔断摘除 / L2 降档 / L3 返回检索片段 / L4 返回近似缓存）。
- **Agentic RAG 自纠正循环（可选开启）**：对指定 `(租户, 意图)` 组合启用；在线用 RAGAs 校验答案的 Faithfulness（≥0.90）与 Answer Relevance（≥0.85），低分则通过 **HyDE** 改写查询、重新检索重排、再生成，并在独立宽松超时（默认 20s）内循环。始终返回历史最高分答案（best-so-far），未达标时标记 `low_confidence`，绝不劣于单轮结果。
- **影子索引 + 原子切换**：离线全量重建走 `__shadow` 集合，校验通过后原子切换 `__active` 别名，实现零停机更新与快速回滚。
- **多租户隔离**：按租户维度隔离 Milvus 集合、ES 索引、图谱版本与缓存命名空间。
- **可观测性与评估**：Prometheus 指标 + OpenTelemetry 链路追踪；四级评估框架（意图 / 检索 / RAGAs / 业务）与发布门禁。离线评估分 **CI / Nightly** 两级：CI  tier（<2min，无 LLM）含关键得分点覆盖率（embedding 近似）+ answer_similarity；Nightly tier 追加上下文精确度 CP@K（LLM judge）、NLI 关键得分点、Agentic 循环效率分析。

---

## 详细文档（Wiki）

项目在 [`docs/wiki/`](./docs/wiki/Home.md) 下维护了完整的模块级技术文档，覆盖端到端架构、各子系统设计与接口、配置参考及入门指南。以下为各页面索引：

| 文档 | 内容 |
|------|------|
| [Home](./docs/wiki/Home.md) | 项目总览、技术栈速览、仓库结构 |
| [Architecture](./docs/wiki/Architecture.md) | 在线查询链路、Agentic 自纠正循环、离线索引流水线、多租户隔离、设计决策 |
| [Getting Started](./docs/wiki/Getting-Started.md) | 安装、Mock 模式运行、测试、离线评估、真实后端配置 |
| [Intent Recognition](./docs/wiki/Module-Intent.md) | 两阶段意图识别（规则 + MiniLM）、实体识别、路由提示 |
| [Hybrid Retrieval](./docs/wiki/Module-Retrieval.md) | 意图路由、RRF 融合、Cross-Encoder 重排、图谱多跳 |
| [LLM Serving](./docs/wiki/Module-Serving.md) | 分级调度、资源池、降级链 L1–L4、前缀 KV 缓存 |
| [Semantic Cache](./docs/wiki/Module-Cache.md) | L1/L2 两级语义缓存、相似度阈值、精确失效 |
| [Offline Index Pipeline](./docs/wiki/Module-Pipeline.md) | 状态机、影子索引、原子切换、知识图谱子流水线 |
| [Query Facade](./docs/wiki/Module-Query.md) | 在线编排、Agentic 循环（HyDE + RAGAs 门禁）、接线、CLI |
| [Infrastructure Clients](./docs/wiki/Module-Clients.md) | Milvus / ES / Neo4j / Redis / Postgres / S3 客户端封装 |
| [Evaluation](./docs/wiki/Module-Evaluation.md) | 四级评估、CI/Nightly 分层、关键得分点、CP@K、Agentic 效率 |
| [Observability](./docs/wiki/Module-Observability.md) | Prometheus 指标、OpenTelemetry 追踪、告警规则 |
| [Deployment & Rollout](./docs/wiki/Module-Deploy.md) | 金丝雀发布、健康门禁、自动回滚 |
| [Domain Model & Config](./docs/wiki/Reference-Core.md) | 领域模型、配置参考（`RAG_*` 环境变量）、命名约定、结构化日志 |

---

## 系统架构

### 在线查询链路（`query/service.py`）

```
用户查询
   │
   ▼
[1] 向量化 (bge-m3, 1024维)  ──────┐ 复用同一 embedding
   │                               │
   ▼                               ▼
[2] 意图识别 ────────────► [3] 缓存查找 (可 --bypass-cache 跳过)
   规则层 → MiniLM分类器          │ 命中则直接返回
   + 实体识别                     │ 未命中 ▼
                                 [4] 意图路由检索
                                    ├ Intent-1 精确：单集合 混合检索
                                    ├ Intent-2 对比：多产品并发 混合检索
                                    └ Intent-3 关系：图谱多跳 + 向量补充
                                          │
                                          ▼
                                 [5] 分级生成 (7B/14B + 降级链 L1~L4)
                                          │
                                          ▼
                                 [6] 异步写缓存 → 返回 Answer + Trace
```

> **可选的 Agentic 分支**：缓存未命中后，若 `(租户, 意图)` 命中 Agentic 白名单，则 `[4][5]` 由 `AgenticController` 接管，进入自纠正循环（见下）；否则走上图默认单轮链路，零额外开销。

### Agentic RAG 自纠正循环（`query/agentic.py`）

对指定 `(租户, 意图)` 组合开启（静态 env 配置）。非白名单请求完全走原单轮链路，无额外延迟与依赖。

```
是否命中 (租户, 意图) 白名单？
        │ 否 → 默认单轮链路（零开销）
        │ 是 → 独立宽松超时 (RAG_AGENTIC_DEADLINE_S, 默认20s) + 最大迭代 (RAG_AGENTIC_MAX_ITERS, 默认2)
        ▼
  ┌───────────────── 循环 ─────────────────┐
  │ 迭代0: 检索(RRF+重排) → 生成 → RAGAs打分 │
  │            │                   │        │
  │    ┌───────┘                   │        │
  │    │                     未通过且预算充足 │
  │    │                           ▼        │
  │    │      HyDE: 7B池生成假设文档         │
  │    │        → 嵌入覆盖稠密臂             │
  │    │      (稀疏/BM25臂仍用原查询)        │
  │    │        → 重新检索 ─────────────────┤
  │    ▼                                    │
  │  通过 → 立即返回（不再迭代）              │
  │  未通过 → 记录当前候选，继续循环          │
  │  每轮按 rank = faithfulness +            │
  │    answer_relevance 更新 best-so-far     │
  └────────────────────┬────────────────────┘
                       ▼
   返回最高分答案；未达标则 meta.low_confidence=true
   trace 记录迭代次数、每轮 faithfulness/answer_relevance 及是否经 HyDE 改写
```

关键设计：
- **在线质量门禁**：复用离线 `RagasEvaluator`，仅用 **Faithfulness（≥0.90）+ Answer Relevance（≥0.85）** 两个无参考指标；Context Utilization 需 ground truth，保持仅离线。每轮候选必须**同时**通过两项阈值才视为合格并立即返回。
- **HyDE 改写**：LLM 生成"假设性答案段落"，其嵌入覆盖**稠密臂**查询向量以缩小 query-document 语义鸿沟；**稀疏/BM25 臂始终使用原始查询词**，避免在幻觉文本上做词面匹配。HyDE 生成走 **7B/SMALL 池**，不抢占答案生成的大模型资源。
- **独立检索路径**：`AgenticRetriever` 直接调用稠密/稀疏检索器并支持嵌入覆盖，**不改动共享的 `RetrievalRouter`**（保护 SLA 关键路径）。默认 recall_k=20，rerank 后取 final_k=5。
- **资源池隔离**：RAGAs 判定与 HyDE 生成走 **7B/SMALL 池**，不抢占答案生成的 14B/LARGE 池。
- **best-so-far 保证**：每轮按 `rank = faithfulness + answer_relevance` 综合排序，始终保留历史最高分候选。循环绝不劣于单轮结果；耗尽预算仍未达标时返回最优候选并标记 `low_confidence`。
- **优雅回退**：若 RAGAs 后端不可用或循环内异常，自动回退到单轮链路，不使请求失败。
- **逐轮可观测性**：`QueryTrace.agentic_scores` 记录每轮的 `iteration`、`faithfulness`、`answer_relevance`、`rewritten`（是否经 HyDE 改写）及 `passed`；`Answer.meta` 包含 `agentic: true`、`low_confidence`、`iterations` 等字段，便于下游监控与离线分析。
- **延迟权衡**：一次"失败→重试"约需 ~10 次 LLM 调用（2 次生成 + 2 次 RAGAs 拆解校验 + 1 次 HyDE），因此严格的 2s/5s/8s 意图级 SLA 只对非白名单流量生效，Agentic 请求使用独立宽松超时。

启用示例（对租户 `t1` 的精确问答意图开启）：

```bash
export RAG_AGENTIC_ENABLED_TENANTS=t1
export RAG_AGENTIC_ENABLED_INTENTS=Intent-1
export RAG_AGENTIC_DEADLINE_S=20
export RAG_AGENTIC_MAX_ITERS=2
.venv/Scripts/python.exe -m query "订单中心如何配置限流策略" --tenant t1 --verbose
```

### 离线索引链路（`pipeline/orchestrator.py`）

```
状态机：PENDING → PROCESSING → VALIDATING → READY → SWITCHING → DONE
                            └── 失败 ──► FAILED → ROLLED_BACK

S3拉取文档 → 变更检测(内容哈希) → 分块+向量化
   → 三索引并行构建(影子): Milvus向量 / ES BM25 / Neo4j图谱
   → 校验(数量对账 + 热查询命中率)
   → 原子切换别名 docs_{tenant}__active
   → 缓存精确失效 + 元数据落库
```

命名约定（`naming.py`）：
- 租户基名：`docs_{tenant_id}`
- 活跃别名（检索目标）：`docs_{tenant_id}__active`
- 影子集合：`docs_{tenant_id}__shadow_{run_id}`

---

## 技术栈

| 类别 | 组件 |
|------|------|
| 语言 | Python 3.11 |
| 向量库 | Milvus 2.4（HNSW，IP 度量） |
| 全文检索 | Elasticsearch 9.x（BM25） |
| 图数据库 | Neo4j 5.x（+ APOC） |
| 缓存 | Redis Stack（RediSearch 向量检索） |
| 元数据库 | PostgreSQL 16 |
| 对象存储 | MinIO / S3（原始文档） |
| 嵌入模型 | BAAI/bge-m3（1024 维） |
| 重排模型 | BAAI/bge-reranker-v2-m3 |
| 意图模型 | paraphrase-multilingual-MiniLM-L12-v2 + LogisticRegression |
| LLM 服务 | vLLM（OpenAI 兼容接口，7B/14B 分级） |
| 可观测性 | Prometheus + OpenTelemetry |

---

## 项目结构

> 包根目录为 `src/rag`。所有 CLI 均从该目录下以 `python -m <module>` 方式运行。

```
rag/
├── README.md                    # 本文件
├── data/                        # 训练/评估数据集
│   └── eval/                    # golden_set / intent_eval / retrieval_eval
├── tests/                       # 集成/隔离/故障注入/性能/发布 测试
├── openspec/                    # 能力规格说明（specs）与变更提案归档
└── src/rag/                     # ★ 包根（运行目录）
    ├── .venv/                   # 虚拟环境 (Python 3.11.9)
    ├── requirements.txt         # 依赖清单
    ├── docker-compose.yml       # 基础设施编排
    ├── config.py                # 全局配置 (env 前缀 RAG_)
    ├── models.py / naming.py / raglog.py   # 领域模型 / 命名 / 结构化日志
    ├── intent/                  # 两阶段意图识别 + 实体识别 + 训练/评测工具
    ├── query/                   # 在线查询facade + 接线 + CLI (__main__.py)
    ├── retrieval/               # 稠密/稀疏/RRF融合/重排/意图路由
    ├── serving/                 # 分级调度/资源池/负载均衡/熔断/前缀缓存/压测
    ├── pipeline/                # 离线索引流水线 (含 graph/ 子包) + 调度器
    ├── cache/                   # 两级语义缓存
    ├── clients/                 # Milvus/ES/Neo4j/Redis/Postgres/S3 客户端封装
    ├── observability/           # 指标/追踪/告警/看板
    ├── evaluation/              # 四级评估框架 + 离线评估 + 发布门禁 + 关键得分点/上下文精确度/Agentic效率
    ├── deploy/                  # 金丝雀→灰度→全量 发布控制
    ├── models/                  # 本地模型 (MiniLM + 训练好的意图分类头)
    └── docs/wiki/               # 详细模块文档（15 篇）
```

---

## 环境准备

### 前置要求

- Python 3.11
- Docker 与 Docker Compose（用于基础设施）
- 至少 8GB 可用内存（Milvus + ES + Neo4j 等）

### 安装依赖

```bash
cd src/rag
python -m venv .venv                      # 若尚未创建
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/macOS
```

> **注意**：所有命令示例均假设当前目录为 `src/rag`。Windows 下直接调用 `.venv/Scripts/python.exe`，Linux/macOS 下先 `source .venv/bin/activate` 再用 `python`。

---

## 快速开始

无需任何基础设施，用 **mock 模式** 即可跑通完整查询链路（嵌入、检索、生成均为内置假实现）：

```bash
cd src/rag
.venv/Scripts/python.exe -m query "订单中心如何配置限流策略"
```

加 `--verbose` 可观测检索片段和发送给 LLM 的 prompt：

```bash
.venv/Scripts/python.exe -m query "订单中心如何配置限流策略" --verbose
```

---

## 使用指南

### 1. 启动基础设施

生产模式（`--service production`）依赖真实后端。用 Docker Compose 一键拉起：

```bash
cd src/rag
docker compose up -d
```

包含服务与端口：

| 服务 | 端口 | 说明 |
|------|------|------|
| MinIO | 9000 (API) / 9001 (控制台) | 对象存储，账号 `minioadmin/minioadmin123` |
| Milvus | 19530 (SDK) / 9091 (HTTP) | 向量库 |
| Elasticsearch | 9200 / 9300 | 全文检索 |
| Neo4j | 7474 (HTTP) / 7687 (Bolt) | 图数据库，账号 `neo4j/your_password123` |
| Redis | 6379 | 语义缓存，密码 `your_redis_password` |
| PostgreSQL | 5432 | 元数据，账号 `postgres/your_pg_password`，库 `mydb` |

### 2. 训练意图分类器

在线查询的意图识别模型层需要先训练（规则层无需训练）。

```bash
# (可选) 生成模板化训练数据，默认 500 条、输出到 data/intent_train.jsonl
.venv/Scripts/python.exe -m intent.training_data --count 500 --out data/intent_train.jsonl

# 训练并评估，模型头保存到 models/intent/head.joblib
.venv/Scripts/python.exe -m intent.classifier \
    --train intent/data/intent_train.jsonl \
    --model-dir models/intent
```

参数：
- `--train`：训练集 JSONL 路径
- `--eval`：验证集路径（省略则复用训练集）
- `--model-dir`：模型输出目录（默认 `models/intent`）

> 首次运行会加载本地 MiniLM 编码器（`models/paraphrase-multilingual-MiniLM-L12-v2`）。若目录不存在则回退到 HuggingFace 下载。

意图延迟基准测试：

```bash
.venv/Scripts/python.exe -m intent.benchmark --mode rule    # 规则层
.venv/Scripts/python.exe -m intent.benchmark --mode full    # 完整两阶段
```

### 3. 上传文档并构建索引

生产查询前，必须先把文档灌入 Milvus/ES/Neo4j。索引流水线会创建 `docs_{tenant}__active` 别名——**查询报 `collection not found` 通常就是因为该流水线未成功执行**。

**步骤 1：上传原始文档到 S3/MinIO**

文档需放在 `rag-raw-docs` 桶的 `{tenant_id}/` 前缀下，支持 `.pdf .docx .doc .md .markdown .txt`。

```bash
# 方式 A：MinIO Client (mc)
mc alias set local http://localhost:9000 minioadmin minioadmin123
mc mb local/rag-raw-docs
mc cp --recursive ./docs/ local/rag-raw-docs/t1/

# 方式 B：复用项目 boto3 配置上传
.venv/Scripts/python.exe -c "
import boto3
from config import get_settings
s = get_settings()
c = boto3.client('s3', endpoint_url=s.s3_endpoint,
                 aws_access_key_id=s.s3_access_key,
                 aws_secret_access_key=s.s3_secret_key)
try: c.create_bucket(Bucket=s.s3_raw_bucket)
except Exception: pass
c.upload_file('mydoc.md', s.s3_raw_bucket, 't1/mydoc.md')
print('uploaded')
"
```

验证文档可被读取：

```bash
.venv/Scripts/python.exe -c "from clients.s3_client import S3Client; print(S3Client().list_documents('t1'))"
```

**步骤 2：运行索引流水线**

```bash
# 单租户手动重建
.venv/Scripts/python.exe -m pipeline.scheduler manual --tenant-id t1 --run-id run001

# 或：扫描所有租户前缀，批量重建
.venv/Scripts/python.exe -m pipeline.scheduler scheduled --run-id daily001
```

流水线依次执行：拉取解析文档 → 变更检测 → 分块+向量化 → 三索引并行构建（向量/BM25/图谱）→ 校验 → 原子切换别名。看到 `pipeline_done` / `state: DONE` 即成功。

> 中文实体/关系抽取依赖 spaCy 中文模型，可选安装：`.venv/Scripts/python.exe -m spacy download zh_core_web_sm`。未安装时实体抽取为空，但不阻断流水线。

### 4. 运行查询

```bash
# mock 模式（无需基础设施）
.venv/Scripts/python.exe -m query "你的查询"

# 生产模式（需已启动基础设施并完成索引构建）
.venv/Scripts/python.exe -m query "俄中国际学校存在哪些问题" --service production --verbose
```

参数：

| 参数 | 说明 |
|------|------|
| `text` | 查询文本（必填，位置参数） |
| `--tenant` | 租户 id（默认 `t1`） |
| `--service` | `mock`（默认）或 `production` |
| `-v, --verbose` | 额外打印检索片段与发送给 LLM 的完整 prompt |
| `--bypass-cache` | 跳过语义缓存，强制走完整检索+生成路径 |

输出包含答案文本，以及可观测的 trace：意图/来源/资源档位/降级级别、request_id、各阶段耗时（hops）、命中的文档 id。

若请求命中 Agentic 白名单，输出额外包含：

| 字段 | 说明 |
|------|------|
| `meta.agentic` | `true`，标识本次走了自纠正循环 |
| `meta.low_confidence` | `true` 表示所有迭代均未通过质量门禁（答案仍为历史最优） |
| `meta.iterations` | 实际迭代次数 |
| `trace.agentic_scores` | 每轮的 `faithfulness`、`answer_relevance`、`rewritten`、`passed` |

### 5. 评估与压测

```bash
# 离线评估 —— CI tier（快速，无 LLM 调用，含关键得分点覆盖率）
.venv/Scripts/python.exe -m evaluation.run_offline --data-dir data/eval --service mock --tier ci

# 离线评估 —— Nightly tier（追加 Context Precision、NLI 得分点、Agentic 效率）
.venv/Scripts/python.exe -m evaluation.run_offline --data-dir data/eval --service mock --tier nightly

# 评估流水线（daily 日常 / gate 发布门禁）
.venv/Scripts/python.exe -m evaluation.pipeline --mode daily --data-dir data/eval

# 服务层压测
.venv/Scripts/python.exe -m serving.loadtest --qps 5000 --duration 10 --small 40 --large 16
```

#### 离线评估增强指标

| 指标 | 所属 Tier | 说明 |
|------|-----------|------|
| **关键得分点覆盖率** (Key-Point Coverage) | CI / Nightly | 将参考答案预分解为原子声明（key_points），用 MiniLM 余弦相似度（τ=0.65）逐点匹配生成答案；Nightly 可切换 NLI 模式获取更高精度。门限 ≥ 0.80。 |
| **Answer Similarity** | CI / Nightly | 生成答案与参考答案的嵌入余弦相似度，作为 RAGAs ground_truth 的补充信号。 |
| **Context Precision@K** (CP@K) | Nightly | 对每个检索片段由 LLM judge 判定相关性，计算 `(1/K) × Σ(relevance_i × (1/i))`，按意图分桶。用于诊断重排器薄弱点。 |
| **重排训练标签导出** | Nightly | 将 `(query, chunk, relevance, reranker_score)` 导出为 JSONL，自动标记硬负例（score ≥ 0.7 且 relevance = 0），供 cross-encoder 微调。 |
| **Agentic 循环效率** | Nightly | 聚合 first_pass_rate、loop_trigger_rate、improvement_delta、wasted_loop_rate、cost_effectiveness，按 (tenant, intent) 给出 enable / skip / tune 建议。 |

运行测试套件（从仓库根目录，`src` 加入 PYTHONPATH）：

```bash
cd D:/projects-python/rag
PYTHONPATH=src .venv/bin/python -m pytest tests/
```

---

## 配置说明

所有配置在 `src/rag/config.py`，通过环境变量（前缀 `RAG_`）或 `.env` 文件覆盖。关键项：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `RAG_MILVUS_HOST` / `RAG_MILVUS_PORT` | `localhost` / `19530` | Milvus 地址 |
| `RAG_ES_HOSTS` | `http://localhost:9200` | Elasticsearch 地址（逗号分隔） |
| `RAG_NEO4J_URI` / `RAG_NEO4J_PASSWORD` | `bolt://localhost:7687` / `your_password123` | Neo4j |
| `RAG_REDIS_URL` | `redis://:your_redis_password@localhost:6379/0` | Redis |
| `RAG_PG_DSN` | `postgresql://postgres:your_pg_password@localhost:5432/mydb` | PostgreSQL |
| `RAG_S3_ENDPOINT` | `http://localhost:9000` | MinIO/S3 端点 |
| `RAG_S3_RAW_BUCKET` | `rag-raw-docs` | 原始文档桶 |
| `RAG_EMBEDDING_MODEL` / `RAG_EMBEDDING_DIM` | `BAAI/bge-m3` / `1024` | 嵌入模型与维度（**须与 Milvus schema 一致**） |
| `RAG_CHUNK_TOKENS` / `RAG_CHUNK_OVERLAP_TOKENS` | `512` / `50` | 分块参数 |
| `RAG_VLLM_SMALL_ENDPOINTS` / `RAG_VLLM_LARGE_ENDPOINTS` | `https://api.openai.com` | 7B/14B 资源池端点（逗号分隔） |
| `RAG_LLM_API_KEY` | `EMPTY` | LLM API Key |
| `RAG_OTLP_ENDPOINT` | `""` | OTLP 采集器（空则追踪为 no-op） |
| `RAG_KG_CONFIDENCE_THRESHOLD` | `0.85` | 关系自动入库阈值，低于则进人工审核队列 |
| `RAG_AGENTIC_ENABLED_TENANTS` | `""` | Agentic 自纠正循环启用的租户白名单（逗号分隔，空=全部关闭） |
| `RAG_AGENTIC_ENABLED_INTENTS` | `""` | Agentic 启用的意图白名单（逗号分隔，取值 `Intent-1\|2\|3`，空=全部关闭） |
| `RAG_AGENTIC_DEADLINE_S` | `20.0` | Agentic 循环的墙钟总预算（秒），独立于各意图严格 SLA |
| `RAG_AGENTIC_MAX_ITERS` | `2` | Agentic 循环的最大迭代次数（含首轮） |

> vLLM 端点默认指向 `api.openai.com` 且无有效 Key，属占位配置。未接入真实 LLM 时，生产查询会触发 **L3 降级**，直接返回检索片段而不调用 LLM（此时 `--verbose` 的 prompt 显示"未调用 LLM"）。要启用真实生成，需将上述端点指向可用的 vLLM/OpenAI 兼容服务并配置 `RAG_LLM_API_KEY`。

---

## 常见问题

**Q: 生产查询报 `collection not found[collection=docs_t1__active]`？**
A: 该别名由索引流水线创建。需先上传文档到 S3 的 `t1/` 前缀，再运行 `python -m pipeline.scheduler manual --tenant-id t1 --run-id <id>`。若 S3 中无可解析文档，流水线会因变更集为空而短路，别名不会创建。

**Q: 意图分类报 `classifier not trained/loaded`？**
A: 需先运行 `python -m intent.classifier` 训练，模型头会保存到 `models/intent/head.joblib`。

**Q: Windows 终端输出中文乱码或 `UnicodeEncodeError`？**
A: query CLI 已内置 UTF-8 stdout 重配置。其他脚本可设 `PYTHONUTF8=1 PYTHONIOENCODING=utf-8`。

**Q: Elasticsearch 报 `BadRequestError(400)`？**
A: 客户端与服务器大版本需匹配。本项目使用 ES 9.x，客户端 `elasticsearch>=8.13`。若升级 ES 数据卷跨大版本（如 8.15→9.0）会拒绝启动，需先逐级升级或清空数据卷重建。

**Q: 各模块的详细设计文档在哪里？**
A: 见上方 [详细文档（Wiki）](#详细文档wiki) 一节，或直接浏览 [`docs/wiki/`](./docs/wiki/Home.md)，包含架构、各模块、入门指南等 15 篇文档。

---

## 后续优化 Roadmap / TODO

以下为规划中的迭代方向，按主题分组，欢迎共建。已勾选（`[x]`）项为本仓库已落地实现，详见上文 [Agentic RAG 自纠正循环](#agentic-rag-自纠正循环-queryagenticpy) 一节。

### 文档解析与预处理
- [ ] **PDF 解析优化**：引入 OCR（如 PaddleOCR / Tesseract）与视觉大模型（如 Qwen-VL、GOT-OCR），提取扫描件、表格、公式、图表等结构化与非结构化信息。
- [ ] **版面理解**：识别标题层级、多栏排版、页眉页脚，保留文档结构以提升切分与召回质量。
- [ ] **多模态入库**：对图片/图表生成描述文本并单独向量化，支持图文混合检索。

### 查询理解与改写
- [ ] **Query 改写**：对用户查询做同义扩展、拼写纠错、指代消解与口语化归一，提升召回。
- [ ] **多查询生成（Multi-Query）**：由一个查询派生多个子查询并行检索后融合，覆盖不同表述。
- [x] **HyDE（Hypothetical Document Embeddings）**：先让 LLM 预先生成假设性答案，再用答案的嵌入去检索，缓解 query-document 语义鸿沟。**（已实现，用于 Agentic 循环的改写轮：仅覆盖稠密臂向量，稀疏臂保留原始 query 词）**
- [ ] **查询分解（Decomposition）**：将复杂多跳问题拆成子问题，逐步检索并聚合。

### 检索与重排
- [ ] **父子/分层检索（Parent-Child / Small-to-Big）**：小块用于精确匹配，命中后回溯父块提供完整上下文。
- [ ] **上下文压缩（Contextual Compression）**：重排后对片段做抽取式压缩，仅保留与问题相关的句子，降低噪声与 token 成本。
- [ ] **元数据过滤**：结合租户、时间、文档类型等结构化过滤，缩小检索空间。
- [ ] **检索质量自评（Self-RAG / CRAG）**：对召回结果打分，低质则触发查询改写或联网/兜底检索。

### Agentic RAG
- [x] **Agentic RAG（基础自纠正循环）**：已实现 retrieve → generate → RAGAs 门禁 → HyDE 改写 → 重检索的闭环，按 `(租户, 意图)` 白名单可选开启，受墙钟预算 + 最大迭代数约束，best-so-far 返回并标记 `low_confidence`。
- [ ] **按需检索决策**：进一步让 Agent 决定是否检索、检索什么、是否多轮补充，支持工具调用与多数据源路由。
- [ ] **多步推理与反思**：结合 ReAct / Reflexion，让模型在生成中自我批判并补检证据。
- [ ] **路由 Agent**：根据意图与问题类型动态选择检索策略（向量 / BM25 / 图谱 / SQL / Web）。

### 知识图谱与生成
- [ ] **GraphRAG 增强**：社区摘要、全局问答，提升跨文档主题级问题的回答能力。
- [ ] **引用与可溯源**：生成答案时逐句标注来源片段，输出可点击引用。
- [x] **答案自检与幻觉检测**：基于 RAGAs 的 faithfulness 在线校验，低分触发降级或重生成。**（已实现：Agentic 循环在线跑 Faithfulness ≥ 0.90 且 Answer Relevance ≥ 0.85 门禁，不达标触发 HyDE 改写重生成）**

### 评估与运维
- [x] **关键得分点覆盖率（Key-Point Coverage）**：黄金集预分解原子声明，CI 用 embedding 近似（τ=0.65），Nightly 可切 NLI/LLM 精确模式；门限 ≥ 0.80，已接入发布门禁。
- [x] **Context Precision@K + 重排训练数据飞轮**：LLM judge 逐片段标注相关性，按意图分桶输出 CP@K；自动导出带硬负例标记的 JSONL 供 cross-encoder 微调。
- [x] **Agentic 循环效率报告**：离线聚合 first_pass_rate / improvement_delta / wasted_loop_rate / cost_effectiveness，按 (tenant, intent) 输出 enable/skip/tune 建议，指导生产白名单配置。
- [x] **CI / Nightly 两级评估分层**：CI tier < 2min 无 LLM 调用（embedding 得分点 + answer_similarity）；Nightly tier 追加 LLM judge 指标（CP@K、NLI、Agentic 效率）。
- [ ] **在线反馈闭环**：收集用户点赞/点踩与人工标注，回流到评估集与再训练。
- [ ] **自动化回归门禁**：将四级评估接入 CI，指标劣化时阻断发布。
- [ ] **成本与延迟优化**：缓存命中率调优、批处理、投机解码（speculative decoding）等。

---

## 许可证

内部项目。
