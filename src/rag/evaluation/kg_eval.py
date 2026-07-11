from __future__ import annotations

from dataclasses import dataclass

from evaluation.types import EvalReport
from raglog import get_logger

log = get_logger("kg_eval")

# Spec: entity Precision > 0.90 / Recall > 0.85; relation extraction accuracy tracked.
_ENTITY_PRECISION_MIN = 0.90
_ENTITY_RECALL_MIN = 0.85
_RELATION_ACCURACY_MIN = 0.85


@dataclass
class KGAnnotation:
    """Gold annotation for one document: expected entities and relation triples."""

    doc_id: str
    entities: set[str]
    relations: set[tuple[str, str, str]]  # (source, relation, target)


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    return prec, rec, f1


def evaluate_kg(
    annotations: list[KGAnnotation],
    predicted_entities: dict[str, set[str]],
    predicted_relations: dict[str, set[tuple[str, str, str]]],
) -> EvalReport:
    """Task 8.9: entity Precision/Recall and relation-triple accuracy on annotated docs."""
    ent_tp = ent_fp = ent_fn = 0
    rel_tp = rel_fp = rel_fn = 0
    for ann in annotations:
        pe = predicted_entities.get(ann.doc_id, set())
        ent_tp += len(ann.entities & pe)
        ent_fp += len(pe - ann.entities)
        ent_fn += len(ann.entities - pe)

        pr = predicted_relations.get(ann.doc_id, set())
        rel_tp += len(ann.relations & pr)
        rel_fp += len(pr - ann.relations)
        rel_fn += len(ann.relations - pr)

    e_prec, e_rec, e_f1 = _prf(ent_tp, ent_fp, ent_fn)
    r_prec, r_rec, r_f1 = _prf(rel_tp, rel_fp, rel_fn)

    report = EvalReport(
        name="knowledge_graph",
        metrics={
            "entity_precision": e_prec,
            "entity_recall": e_rec,
            "entity_f1": e_f1,
            "relation_precision": r_prec,
            "relation_recall": r_rec,
            "relation_accuracy": r_f1,
        },
    )
    if e_prec < _ENTITY_PRECISION_MIN:
        report.failures.append(f"entity_precision {e_prec:.4f} < {_ENTITY_PRECISION_MIN}")
    if e_rec < _ENTITY_RECALL_MIN:
        report.failures.append(f"entity_recall {e_rec:.4f} < {_ENTITY_RECALL_MIN}")
    if r_f1 < _RELATION_ACCURACY_MIN:
        report.failures.append(f"relation_accuracy {r_f1:.4f} < {_RELATION_ACCURACY_MIN}")
    report.passed = not report.failures
    log.info("kg_eval_done", entity_precision=round(e_prec, 4), entity_recall=round(e_rec, 4), passed=report.passed)
    return report
