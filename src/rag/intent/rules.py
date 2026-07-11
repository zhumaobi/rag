from __future__ import annotations

import re

from intent.types import Intent

# High-signal lexical cues per intent. Rule-layer hits are near-deterministic, so a
# match yields high confidence and short-circuits the model layer (< 1ms).
_COMPARE_PATTERNS = [
    r"对比", r"比较", r"区别", r"差异", r"哪个更?好", r"哪个更", r"孰优孰劣",
    r"\bvs\b", r"\bversus\b", r"和.{1,20}的?不同", r"与.{1,20}相比",
]
_RELATION_PATTERNS = [
    r"关系", r"关联", r"是什么", r"什么是", r"概念", r"依赖", r"属于",
    r"如何(?:关联|连接|集成)", r"之间.{0,6}联系", r"能否替代", r"替代",
]
# Time-sensitive cues are not an intent but a flag the cache layer must honor.
_TIME_SENSITIVE_PATTERNS = [r"最新", r"当前版本", r"最近", r"目前", r"现在", r"今年", r"latest", r"current"]

_COMPARE_RE = [re.compile(p, re.IGNORECASE) for p in _COMPARE_PATTERNS]
_RELATION_RE = [re.compile(p, re.IGNORECASE) for p in _RELATION_PATTERNS]
_TIME_RE = [re.compile(p, re.IGNORECASE) for p in _TIME_SENSITIVE_PATTERNS]

# Confidence emitted on a rule hit; below the router's 0.85 threshold defers to the model.
_HIGH = 0.95


class RuleResult:
    __slots__ = ("intent", "confidence", "time_sensitive")

    def __init__(self, intent: Intent | None, confidence: float, time_sensitive: bool) -> None:
        self.intent = intent
        self.confidence = confidence
        self.time_sensitive = time_sensitive


def _any_match(regexes, text: str) -> bool:
    return any(r.search(text) for r in regexes)


def classify_rules(query: str) -> RuleResult:
    """Rule layer (task 4.1). Comparison cues win over relation cues when both appear,
    because an explicit comparison request is the more specific routing signal.

    Returns intent=None with low confidence when no rule fires, signaling the caller
    to fall through to the MiniLM model layer.
    """
    time_sensitive = _any_match(_TIME_RE, query)

    is_compare = _any_match(_COMPARE_RE, query)
    is_relation = _any_match(_RELATION_RE, query)

    if is_compare:
        return RuleResult(Intent.COMPARE, _HIGH, time_sensitive)
    if is_relation:
        return RuleResult(Intent.RELATION, _HIGH, time_sensitive)
    return RuleResult(None, 0.0, time_sensitive)
