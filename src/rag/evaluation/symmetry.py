from __future__ import annotations

import re
from dataclasses import dataclass

from raglog import get_logger

log = get_logger("symmetry_check")

# Comparison dimensions we expect a balanced Intent-2 answer to cover per product.
_DIMENSION_KEYWORDS = {
    "性能": ["性能", "吞吐", "延迟", "qps", "响应"],
    "成本": ["成本", "价格", "费用", "开销"],
    "可用性": ["可用", "稳定", "容错", "高可用"],
    "易用性": ["易用", "上手", "配置", "使用"],
    "扩展性": ["扩展", "伸缩", "横向", "scale"],
    "适用场景": ["场景", "适用", "适合", "推荐用于"],
}


@dataclass
class SymmetryResult:
    symmetric: bool
    per_product_dimensions: dict[str, set[str]]
    missing: dict[str, set[str]]  # product -> dimensions covered for others but not this one


def _dimensions_in(text: str) -> set[str]:
    lowered = text.lower()
    found = set()
    for dim, kws in _DIMENSION_KEYWORDS.items():
        if any(kw.lower() in lowered for kw in kws):
            found.add(dim)
    return found


def _split_product_sections(answer: str, products: list[str]) -> dict[str, str]:
    """Best-effort attribution of answer text to each product by nearest heading/mention.

    Each product's section is the text from its first mention to the next product's
    mention. Products never mentioned get an empty section (fully asymmetric).
    """
    positions = []
    for p in products:
        m = re.search(re.escape(p), answer)
        positions.append((m.start() if m else -1, p))
    positions.sort()
    sections: dict[str, str] = {p: "" for p in products}
    for i, (start, p) in enumerate(positions):
        if start < 0:
            continue
        end = positions[i + 1][0] if i + 1 < len(positions) and positions[i + 1][0] >= 0 else len(answer)
        sections[p] = answer[start:end]
    return sections


def check_symmetry(answer: str, products: list[str]) -> SymmetryResult:
    """Task 8.5: verify an Intent-2 comparison covers the same dimensions for each product.

    A comparison that discusses performance+cost for product A but only performance for
    product B is asymmetric and flagged as a quality issue.
    """
    sections = _split_product_sections(answer, products)
    per_product = {p: _dimensions_in(text) for p, text in sections.items()}

    union = set().union(*per_product.values()) if per_product else set()
    missing = {p: union - dims for p, dims in per_product.items() if union - dims}
    symmetric = not missing

    result = SymmetryResult(symmetric=symmetric, per_product_dimensions=per_product, missing=missing)
    if not symmetric:
        log.warning("intent2_asymmetric", products=products, missing={k: sorted(v) for k, v in missing.items()})
    return result
