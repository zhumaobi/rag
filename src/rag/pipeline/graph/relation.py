from __future__ import annotations

import json

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings
from raglog import get_logger
from models import Chunk, Entity, Relation, RelationType

log = get_logger("relation")

_RELATION_LABELS = [rt.value for rt in RelationType]

_SYSTEM_PROMPT = (
    "你是知识图谱关系抽取器。给定一段文本和候选实体列表，抽取实体之间的关系。"
    f"关系类型仅限：{', '.join(_RELATION_LABELS)}。"
    "只抽取文本明确支持的关系，禁止推断。"
    "输出 JSON 数组，每项形如 "
    '{"source":"实体A","target":"实体B","relation":"依赖","confidence":0.0-1.0}。'
    "confidence 表示文本对该关系的支持强度。无关系时输出 []。"
)


class RelationExtractor:
    """Batch-calls the private LLM to extract 5 predefined relation types with confidence."""

    def __init__(self) -> None:
        s = get_settings()
        self._base_url = s.llm_base_url
        self._model = s.llm_model
        self._api_key = s.llm_api_key
        self._client = httpx.Client(timeout=60.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def _call(self, text: str, candidate_names: list[str]) -> list[dict]:
        payload = {
            "model": self._model,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"候选实体：{candidate_names}\n\n文本：\n{text}",
                },
            ],
        }
        resp = self._client.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return _parse_relations(content)

    def extract(self, chunks: list[Chunk], entities: dict[str, Entity]) -> list[Relation]:
        names = set(entities)
        relations: list[Relation] = []
        for chunk in chunks:
            present = [n for n in names if n in chunk.text]
            if len(present) < 2:
                continue
            try:
                raw = self._call(chunk.text, present)
            except Exception as exc:
                log.warning("relation_call_failed", chunk_id=chunk.chunk_id, error=str(exc))
                continue
            for item in raw:
                rel = _to_relation(item, chunk.doc_id, present)
                if rel is not None:
                    relations.append(rel)
        log.info("relations_extracted", count=len(relations))
        return relations


def _parse_relations(content: str) -> list[dict]:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```", 2)[1].removeprefix("json").strip()
    try:
        data = json.loads(content)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _to_relation(item: dict, doc_id: str, valid_names: list[str]) -> Relation | None:
    try:
        rel_type = RelationType(item["relation"])
    except (KeyError, ValueError):
        return None
    src, dst = item.get("source"), item.get("target")
    if src not in valid_names or dst not in valid_names or src == dst:
        return None
    conf = float(item.get("confidence", 0.0))
    return Relation(source=src, target=dst, relation_type=rel_type, confidence=conf, doc_id=doc_id)
