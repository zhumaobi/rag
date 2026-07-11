# 企业级 RAG 系统

一个面向多租户的企业知识库检索增强生成（RAG）系统，覆盖从**离线索引构建**到**在线查询服务**的完整链路，并内置意图识别、混合检索、知识图谱、语义缓存、分级 LLM 服务、可观测性与评估框架。

---

## 目录

- [核心特性](#核心特性)
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

---

## 核心特性

- **两阶段意图识别**：规则层（正则，<1ms，命中即短路）+ MiniLM 嵌入 + 逻辑回归分类器，三分类（精确问答 / 多产品对比 / 关系解释）。
- **意图路由的混合检索**：稠密向量（Milvus）+ 稀疏 BM25（Elasticsearch）→ RRF 融合 → Cross-Encoder 重排；关系类查询额外走 Neo4j 知识图谱多跳检索。
- **两级语义缓存**：L1 内存 LRU + L2 Redis 向量相似检索（HNSW），并维护 `doc_id → cache_key` 反向索引以支持精确失效。
- **分级 LLM 服务与降级链**：7B / 14B 双资源池 + 一致性哈希租户亲和 + 前缀 KV 缓存复用；四级降级（L1 熔断摘除 / L2 降档 / L3 返回检索片段 / L4 返回近似缓存）。
- **影子索引 + 原子切换**：离线全量重建走 `__shadow` 集合，校验通过后原子切换 `__active` 别名，实现零停机更新与快速回滚。
- **多租户隔离**：按租户维度隔离 Milvus 集合、ES 索引、图谱版本与缓存命名空间。
- **可观测性与评估**：Prometheus 指标 + OpenTelemetry 链路追踪；四级评估框架（意图 / 检索 / RAGAs / 业务）与发布门禁。

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
    ├── evaluation/              # 四级评估框架 + 离线评估 + 发布门禁
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

### 5. 评估与压测

```bash
# 离线评估（对比 mock/production）
.venv/Scripts/python.exe -m evaluation.run_offline --data-dir data/eval --service mock

# 评估流水线（daily 日常 / gate 发布门禁）
.venv/Scripts/python.exe -m evaluation.pipeline --mode daily --data-dir data/eval

# 服务层压测
.venv/Scripts/python.exe -m serving.loadtest --qps 5000 --duration 10 --small 40 --large 16
```

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
A: 见 `src/rag/docs/wiki/`，包含架构、各模块、入门指南等 15 篇文档。

---

## 许可证

内部项目。
