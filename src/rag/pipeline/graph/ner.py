from __future__ import annotations

import re

from raglog import get_logger
from models import Chunk, Entity

log = get_logger("ner")


class EntityExtractor:
    """spaCy NER + domain dictionary for product names / technical terms (task 3.6).

    The domain dictionary takes priority: exact + alias matches are high precision.
    spaCy supplies recall for entities not yet in the dictionary (ORG/PRODUCT labels).
    """

    def __init__(self, domain_terms: dict[str, str], spacy_model: str = "zh_core_web_sm") -> None:
        # domain_terms: canonical_name -> entity_type
        self._domain_terms = domain_terms
        self._patterns = {
            term: re.compile(re.escape(term), re.IGNORECASE) for term in domain_terms
        }
        try:
            import spacy

            self._nlp = spacy.load(spacy_model)
        except Exception as exc:
            log.warning("spacy_unavailable", error=str(exc))
            self._nlp = None

    def extract(self, chunks: list[Chunk]) -> dict[str, Entity]:
        """Returns entity name -> Entity, aggregating doc_ids across chunks."""
        entities: dict[str, Entity] = {}

        def _add(name: str, etype: str, doc_id: str) -> None:
            ent = entities.get(name)
            if ent is None:
                ent = Entity(name=name, entity_type=etype)
                entities[name] = ent
            ent.doc_ids.add(doc_id)

        for chunk in chunks:
            for term, etype in self._domain_terms.items():
                if self._patterns[term].search(chunk.text):
                    _add(term, etype, chunk.doc_id)
            if self._nlp is not None:
                for span in self._nlp(chunk.text).ents:
                    if span.label_ in {"ORG", "PRODUCT", "WORK_OF_ART"}:
                        name = span.text.strip()
                        if name and name not in entities:
                            _add(name, span.label_, chunk.doc_id)

        log.info("entities_extracted", count=len(entities))
        return entities
