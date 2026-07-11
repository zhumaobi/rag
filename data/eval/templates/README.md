# 离线评估样本模板 (Purpose-B templates)

这些是**可参考、可扩展的样本模板**，中英文混合，用于手工编写新的评估样本。
它们**不是**用来直接跑绿 `run_offline`（mock）的 —— `ground_truth_doc_ids`
里的 `REPLACE_*` 是占位符，需要替换成真实语料库里的 doc_id 后才有意义。

> 可直接运行的 mock 种子集在上一级目录 `data/eval/*.jsonl`，请勿与本目录混淆。

## 文件与 Schema

加载器：`src/rag/evaluation/datasets.py`（JSONL，一行一个 JSON 对象，UTF-8）。

| 文件 | 字段 | 说明 |
|------|------|------|
| `intent_eval.jsonl` | `query`, `label` | 意图分类样本 |
| `retrieval_eval.jsonl` | `query`, `intent`, `ground_truth_doc_ids[]` | 检索召回样本 |
| `golden_set.jsonl` | `query`, `intent`, `reference_answer`, `ground_truth_doc_ids[]?` | 端到端黄金样本 |

意图取值固定为：`Intent-1`(PRECISE) / `Intent-2`(COMPARE) / `Intent-3`(RELATION)。

## 关键约束：label 要和规则层实际预测一致

意图规则层（`src/rag/intent/rules.py`）在 mock 与生产下**行为一致且确定**，
编写样本时 query 的措辞必须触发对应意图，否则 label 与系统预测不符会拉低指标：

- **Intent-2 (COMPARE)** 需含比较线索：`对比 / 比较 / 区别 / 差异 / 哪个更好 / vs / versus`
- **Intent-3 (RELATION)** 需含关系线索：`是什么 / 什么是 / 关系 / 关联 / 依赖 / 属于 / 替代 / 概念`
- **Intent-1 (PRECISE)** 必须**避免**上面两类线索，否则会被规则层误判为 2/3，
  从而落到 MiniLM 模型层（生产需 `models/intent/head.joblib`）
- 同时出现比较与关系线索时，**COMPARE 优先**（例：「7B 和 14B 的区别是什么？」→ Intent-2）
- 时效线索（`最新 / 当前版本 / 目前 / latest / current`）不改变意图，但会触发缓存旁路

## 阈值（样本达标参考）

- 意图：Accuracy ≥ 0.92，每类 F1 ≥ 0.90（`intent_eval.py`）
- 检索：Intent-1 MRR≥0.80 / Recall@5≥0.88；Intent-2 Recall@5≥0.85；Intent-3 Recall@5≥0.82（`retrieval_eval.py`）
- 生成：faithfulness≥0.90 / answer_relevance≥0.85 / context_utilization≥0.60（`ragas_eval.py`）

## 如何扩展成正式样本集

1. 复制本目录里的行作为模板，按上面的措辞约束编写新 query。
2. 把每条的 `REPLACE_*` 占位符替换为真实语料库中的 doc_id
   （可 `grep REPLACE_` 确认没有漏改）。
3. 将完成的行合并进 `data/eval/*.jsonl`，或用 `--data-dir` 指向你自己的目录：
   `python -m evaluation.run_offline --data-dir <your_dir>`
