from __future__ import annotations

from config import get_settings
from intent.classifier import IntentClassifier
from intent.entity_recognizer import EntityRecognizer
from intent.rules import classify_rules
from intent.types import EntityMatch, Intent, IntentResult
from raglog import get_logger

log = get_logger("intent_service")

# Rule confidence at/above this short-circuits the model layer.
_RULE_CONFIDENCE_THRESHOLD = 0.85


class IntentService:
    """Two-stage intent recognition (task 4.6) exposing a structured interface (task 4.7).

    Stage 1 (rules): near-deterministic lexical cues -> high-confidence direct output (<1ms).
    Stage 2 (MiniLM): only invoked when rules don't fire, keeping the common path cheap.
    Entity recognition runs in parallel-in-spirit (cheap dict lookup) and feeds routing.
    """

    def __init__(
        self,
        classifier: IntentClassifier | None = None,
        entity_recognizer: EntityRecognizer | None = None,
    ) -> None:
        self._classifier = classifier
        self._entities = entity_recognizer or EntityRecognizer()
        self._threshold = _RULE_CONFIDENCE_THRESHOLD

    def _lazy_classifier(self) -> IntentClassifier:
        if self._classifier is None:
            self._classifier = IntentClassifier(model_dir="models/intent")
        return self._classifier

    def recognize(self, tenant_id: str, query: str) -> IntentResult:
        rule = classify_rules(query)
        entities = self._entities.recognize(tenant_id, query)

        if rule.intent is not None and rule.confidence >= self._threshold:
            intent, confidence, source = rule.intent, rule.confidence, "rule"
        else:
            intent, confidence = self._lazy_classifier().predict(query)
            source = "model"

        return IntentResult(
            intent=intent,
            confidence=confidence,
            entities=entities,
            routing_hint=self._routing_hint(intent, entities, rule.time_sensitive),
            source=source,
            time_sensitive=rule.time_sensitive,
        )

    @staticmethod
    def _routing_hint(intent: Intent, entities: list[EntityMatch], time_sensitive: bool) -> str:
        """Compact directive for the retrieval layer so it needs no re-parsing (task 4.7)."""
        parts: list[str] = []
        if intent is Intent.PRECISE:
            targeted = [e.collection_id for e in entities if e.collection_id]
            parts.append(f"targeted:{','.join(targeted)}" if targeted else "global")
        elif intent is Intent.COMPARE:
            parts.append(f"multipath:{len(entities)}")
        else:  # RELATION
            parts.append("graph_traverse")
        if time_sensitive:
            parts.append("no_cache")
        return "|".join(parts)
