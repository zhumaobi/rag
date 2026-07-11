from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from config import get_settings
from intent.types import Intent
from raglog import get_logger

log = get_logger("classifier")

_LABELS = [Intent.PRECISE.value, Intent.COMPARE.value, Intent.RELATION.value]
_LABEL2ID = {lbl: i for i, lbl in enumerate(_LABELS)}
_ID2LABEL = {i: lbl for lbl, i in _LABEL2ID.items()}

_MINILM = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_LOCAL_MINILM = Path(__file__).resolve().parents[1] / "models" / "paraphrase-multilingual-MiniLM-L12-v2"


class IntentClassifier:
    """MiniLM-embedding + logistic-regression 3-class classifier (task 4.5).

    A frozen MiniLM encoder produces sentence embeddings; a lightweight linear head is
    trained on top. This keeps inference at ~5-10ms (single forward pass + matmul) which
    is essential for the < 15ms end-to-end budget, versus fine-tuning the full model.
    """

    def __init__(self, model_dir: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        encoder_src = str(_LOCAL_MINILM) if _LOCAL_MINILM.exists() else _MINILM
        self._encoder = SentenceTransformer(encoder_src)
        self._clf = None
        if model_dir and Path(model_dir).exists():
            self.load(model_dir)

    def _encode(self, texts: list[str]) -> np.ndarray:
        return self._encoder.encode(texts, normalize_embeddings=True, convert_to_numpy=True)

    def train(self, samples: list[dict]) -> None:
        from sklearn.linear_model import LogisticRegression

        X = self._encode([s["text"] for s in samples])
        y = np.array([_LABEL2ID[s["label"]] for s in samples])
        self._clf = LogisticRegression(max_iter=1000, C=4.0)
        self._clf.fit(X, y)
        log.info("classifier_trained", samples=len(samples))

    def predict(self, query: str) -> tuple[Intent, float]:
        if self._clf is None:
            raise RuntimeError("classifier not trained/loaded")
        vec = self._encode([query])
        probs = self._clf.predict_proba(vec)[0]
        idx = int(np.argmax(probs))
        return Intent(_ID2LABEL[idx]), float(probs[idx])

    def evaluate(self, samples: list[dict]) -> dict:
        """Returns overall accuracy and per-class F1 (spec: Accuracy>=92%, F1>=0.90)."""
        from sklearn.metrics import accuracy_score, f1_score

        X = self._encode([s["text"] for s in samples])
        y_true = np.array([_LABEL2ID[s["label"]] for s in samples])
        y_pred = self._clf.predict(X)
        acc = float(accuracy_score(y_true, y_pred))
        per_class = f1_score(y_true, y_pred, average=None, labels=list(range(len(_LABELS))))
        report = {
            "accuracy": acc,
            "f1_per_class": {_ID2LABEL[i]: float(per_class[i]) for i in range(len(_LABELS))},
            "macro_f1": float(f1_score(y_true, y_pred, average="macro")),
        }
        log.info("classifier_evaluated", **report)
        return report

    def save(self, model_dir: str) -> None:
        import joblib

        Path(model_dir).mkdir(parents=True, exist_ok=True)
        joblib.dump(self._clf, Path(model_dir) / "head.joblib")

    def load(self, model_dir: str) -> None:
        import joblib

        self._clf = joblib.load(Path(model_dir) / "head.joblib")


def _read_jsonl(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def train_and_eval(train_path: str, eval_path: str, model_dir: str) -> dict:
    clf = IntentClassifier()
    clf.train(_read_jsonl(train_path))
    report = clf.evaluate(_read_jsonl(eval_path))
    clf.save(model_dir)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the intent classifier logistic-regression head")
    parser.add_argument("--train", default="data/intent_train.jsonl")
    parser.add_argument("--eval", default=None, help="Eval set; defaults to the training set when omitted")
    parser.add_argument("--model-dir", default="models/intent")
    args = parser.parse_args()

    eval_path = args.eval or args.train
    report = train_and_eval(args.train, eval_path, args.model_dir)
    print(f"saved model to {args.model_dir}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
