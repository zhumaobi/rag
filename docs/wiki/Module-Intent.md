# Intent Recognition (`intent/`)

[← Home](./Home.md) · [Architecture](./Architecture.md)

Classifies each query into one of three intents and resolves the entities used for routing. Designed for a P99 under ~15ms so it never dominates online latency.

## Intents

Defined in `intent/types.py`:

| Enum | Value | Meaning | Downstream routing |
|------|-------|---------|--------------------|
| `Intent.PRECISE` | `"Intent-1"` | Precise fact lookup | Targeted hybrid retrieval → 7B LLM |
| `Intent.COMPARE` | `"Intent-2"` | Compare multiple products | Parallel per-product retrieval → 14B LLM |
| `Intent.RELATION` | `"Intent-3"` | Relationship / concept | Neo4j graph traversal → 14B LLM |

## Two-stage recognition

`IntentService.recognize(tenant_id, query)` — `intent/service.py:38`.

```
query
  │
  ├─ Stage 1: classify_rules(query)      (rules.py) — lexical cues, ~<1ms
  │     confidence ≥ 0.85 ? ──► use rule intent (source="rule")
  │     else ▼
  ├─ Stage 2: IntentClassifier.predict() (classifier.py) — MiniLM 3-class (source="model")
  │
  └─ EntityRecognizer.recognize()        (entity_recognizer.py) — always runs
        │
        ▼
   IntentResult(intent, confidence, entities, routing_hint, source, time_sensitive)
```

The rule confidence threshold that short-circuits the model is `_RULE_CONFIDENCE_THRESHOLD = 0.85` (`intent/service.py:13`). The MiniLM classifier is lazily loaded from `models/intent` (`_lazy_classifier`, `intent/service.py:33`), so the rule-only path needs no model.

## Rule layer — `intent/rules.py`

`classify_rules(query)` matches regex cue lists:
- **Compare cues:** `对比`, `比较`, `区别`, `差异`, `vs`, `versus`, `与…相比`, …
- **Relation cues:** `关系`, `关联`, `是什么`, `概念`, `依赖`, `属于`, `替代`, …
- **Time-sensitive cues:** `最新`, `当前版本`, `目前`, `latest`, `current`, … — not an intent, but a flag.

Rules on a hit emit confidence `_HIGH = 0.95`. **Comparison wins over relation** when both match (the more specific routing signal). No match returns `intent=None, confidence=0.0`, deferring to the model.

`time_sensitive=True` propagates to the cache layer and forces a full RAG pass (bypasses cache).

## Routing hint

`IntentService._routing_hint()` (`intent/service.py:57`) builds a compact directive so the retrieval layer needs no re-parsing:
- PRECISE → `targeted:{collection_ids}` or `global`
- COMPARE → `multipath:{n}`
- RELATION → `graph_traverse`
- appends `no_cache` when time-sensitive.

## Files

| File | Purpose |
|------|---------|
| `intent/types.py` | `Intent` enum, `EntityMatch`, `IntentResult(.to_dict())` |
| `intent/rules.py` | `classify_rules()`, `RuleResult`, regex cue lists |
| `intent/service.py` | `IntentService` — two-stage orchestration |
| `intent/classifier.py` | MiniLM 3-class fine-tuned classifier |
| `intent/entity_recognizer.py` | Redis-backed entity dictionary lookup → `collection_id` |
| `intent/entity_dict.py` | Entity dictionary source (product names + aliases) |
| `intent/training_data.py` | Template synthesizer; `main()` writes `data/intent_train.jsonl` |
| `intent/benchmark.py` | Latency benchmark; `--mode rule\|full` (P99 target < 15ms) |

## Utilities

- **Generate training data:** `python -m intent.training_data --out data/intent_train.jsonl --count 500` — 3 balanced classes from 12 products × 12 terms and per-intent templates.
- **Benchmark latency:** `python -m intent.benchmark --mode rule` (rule layer, 20k iters) or `--mode full` (needs trained MiniLM).
