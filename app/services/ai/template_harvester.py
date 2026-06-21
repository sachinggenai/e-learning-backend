"""Template pattern harvester — US-PEND-027.

Detects novel patterns in AI-generated course content by extracting
structural signatures from component_type arrays and comparing them
against existing templates via TF-IDF cosine similarity.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

NOVELTY_THRESHOLD = 0.7
MIN_PAGE_COMPLEXITY = 3
KNOWN_COMPONENT_TYPES = {
    "text-content", "accordion", "quiz", "video-embed",
    "image-gallery", "table", "flashcard", "scenario",
}


class TemplateHarvester:
    """Detects novel template patterns in AI-generated content."""

    def __init__(self, similarity_threshold: float = NOVELTY_THRESHOLD):
        self.threshold = similarity_threshold
        self._vectorizer = TfidfVectorizer(
            analyzer='char_wb', ngram_range=(2, 4), max_features=500,
        )

    async def analyze(
        self, generated_pages: List[Dict], existing_templates: List[Dict],
    ) -> List[Dict]:
        candidates = []
        existing_sigs = [self._extract_signature(t) for t in existing_templates]
        for page in generated_pages:
            sig = self._extract_signature(page.get("content", page))
            if sig["component_count"] < MIN_PAGE_COMPLEXITY:
                continue
            is_novel, max_sim = self._check_novelty(sig, existing_sigs)
            if is_novel:
                candidates.append({
                    "signature_hash": hashlib.sha256(
                        json.dumps(sig, sort_keys=True).encode()
                    ).hexdigest()[:16],
                    "extracted_from_page": page.get("title", "Untitled"),
                    "template_type": page.get("template_type", "unknown"),
                    "signature": sig,
                    "similarity_to_existing": max_sim,
                    "extracted_at": datetime.utcnow().isoformat(),
                })
                existing_sigs.append(sig)
        return self._deduplicate(candidates)

    def _extract_signature(self, data: Dict) -> Dict:
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {}
        components = data.get("components", data.get("blocks", []))
        comp_types = []
        field_names = []
        nesting = 0
        for comp in (components or []):
            ct = comp.get("component_type", comp.get("type", "unknown"))
            comp_types.append(ct)
            for key in comp.keys():
                if key not in ("order_index", "component_type"):
                    field_names.append(key)
            children = comp.get("children", comp.get("items", []))
            nesting += len(children)
        return {
            "component_count": len(components or []),
            "component_types": sorted(set(comp_types)),
            "has_unknown_types": bool(set(comp_types) - KNOWN_COMPONENT_TYPES),
            "unique_field_count": len(set(field_names)),
            "field_names": sorted(set(field_names))[:20],
            "max_nesting_depth": nesting,
            "text_signature": " ".join(sorted(set(comp_types + field_names))),
        }

    def _check_novelty(self, sig, existing_sigs) -> Tuple[bool, float]:
        if not existing_sigs:
            return True, 0.0
        texts = [s.get("text_signature", "") for s in existing_sigs]
        texts.append(sig.get("text_signature", ""))
        try:
            tfidf = self._vectorizer.fit_transform(texts)
            sims = cosine_similarity(tfidf[-1:], tfidf[:-1])
            max_sim = float(sims.max()) if sims.size > 0 else 0.0
        except Exception:
            max_sim = 0.0
        return max_sim < self.threshold, max_sim

    def _deduplicate(self, candidates):
        seen = set()
        unique = []
        for c in candidates:
            if c["signature_hash"] not in seen:
                seen.add(c["signature_hash"])
                unique.append(c)
        return unique
