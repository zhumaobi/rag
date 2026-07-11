from __future__ import annotations

import argparse
import json
from pathlib import Path

from intent.types import Intent

# Template-based synthesis of labeled 3-class samples (task 4.4). Templates capture the
# linguistic shape of each intent; slot fills provide surface variety. This bootstraps a
# ~500-sample set for fine-tuning; real labeled logs should be layered in over time.

_PRODUCTS = [
    "订单中心", "支付网关", "风控引擎", "对账系统", "消息队列", "配置中心",
    "网关服务", "用户中心", "库存服务", "推荐引擎", "日志平台", "监控告警",
]
_TERMS = [
    "幂等键", "限流策略", "熔断阈值", "分片规则", "重试机制", "灰度发布",
    "读写分离", "最终一致性", "分布式锁", "冷启动", "水位线", "背压",
]

# Intent-1: precise single-product / single-term Q&A.
_PRECISE_TEMPLATES = [
    "{p}如何配置{t}",
    "{p}的{t}默认值是多少",
    "怎么在{p}里开启{t}",
    "{p}报错该怎么排查",
    "{t}的实现原理是什么样的步骤",
    "{p}支持哪些{t}参数",
    "如何调用{p}的接口",
    "{p}的{t}上限是多少",
]
# Intent-2: multi-product comparison.
_COMPARE_TEMPLATES = [
    "{p1}和{p2}有什么区别",
    "{p1}对比{p2}哪个更适合高并发",
    "{p1} vs {p2} 性能怎么样",
    "在{t}方面{p1}和{p2}的差异",
    "选{p1}还是{p2}更好",
    "{p1}与{p2}相比优缺点",
]
# Intent-3: concept / relationship clarification.
_RELATION_TEMPLATES = [
    "{p1}和{p2}之间是什么关系",
    "{p}依赖哪些下游服务",
    "{t}这个概念是什么意思",
    "{p1}能否替代{p2}",
    "{p}属于哪个业务域",
    "{p1}是如何和{p2}集成的",
    "解释一下{t}和{t2}的关联",
]


def _cycle(seq, i):
    return seq[i % len(seq)]


def generate(target: int = 500) -> list[dict]:
    samples: list[dict] = []
    i = 0
    # Even split across three classes.
    per_class = target // 3
    for n in range(per_class):
        p = _cycle(_PRODUCTS, n)
        t = _cycle(_TERMS, n + 1)
        tmpl = _cycle(_PRECISE_TEMPLATES, n)
        samples.append({"text": tmpl.format(p=p, t=t), "label": Intent.PRECISE.value})
    for n in range(per_class):
        p1, p2 = _cycle(_PRODUCTS, n), _cycle(_PRODUCTS, n + 3)
        t = _cycle(_TERMS, n)
        tmpl = _cycle(_COMPARE_TEMPLATES, n)
        samples.append({"text": tmpl.format(p1=p1, p2=p2, t=t), "label": Intent.COMPARE.value})
    for n in range(target - 2 * per_class):
        p1, p2 = _cycle(_PRODUCTS, n + 1), _cycle(_PRODUCTS, n + 5)
        t, t2 = _cycle(_TERMS, n), _cycle(_TERMS, n + 4)
        tmpl = _cycle(_RELATION_TEMPLATES, n)
        samples.append({"text": tmpl.format(p=p1, p1=p1, p2=p2, t=t, t2=t2), "label": Intent.RELATION.value})
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate intent classifier training data")
    parser.add_argument("--out", default="data/intent_train.jsonl")
    parser.add_argument("--count", type=int, default=500)
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    samples = generate(args.count)
    with out.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"wrote {len(samples)} samples to {out}")


if __name__ == "__main__":
    main()
