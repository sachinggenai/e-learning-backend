# US-PEND-027: Template Harvesting from AI-Generated Content — CODE-VERIFIED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Feature) |
| **Priority** | 🟢 MEDIUM |
| **Batch** | 7 — Long-Term / Deferred |
| **Depends On** | None |
| **Estimated Effort** | 3-4 days |
| **Target Files** | New: `app/services/ai/template_harvester.py`, `app/models/ai_template_candidate.py`. Modify: `app/services/ai/course_assembler.py` |

---

## User Story

**As a** template librarian,
**I want** novel page patterns discovered in AI-generated content to be captured as candidate templates,
**So that** the template library grows organically from AI usage and I can curate the best patterns.

---

## Current State (Code Verified 2026-06-21)

- ✅ Template registry is static (seeded at startup via `seed_component_types.py`)
- ✅ AI can use existing templates but cannot propose new ones
- ❌ `test -f app/services/ai/template_harvester.py` → NOT FOUND
- ❌ INDEX.md: `US-BKND-AI-037` → ❌ TODO

---

## 🔧 Open-Source Tooling

| Tool | Version | Purpose | Why Selected |
|------|---------|---------|-------------|
| **scikit-learn** | 1.5.x | TF-IDF vectorization + cosine similarity | Industry standard; `TfidfVectorizer` converts structural signatures to vectors for comparison |
| **sentence-transformers** | 3.x | Optional semantic dedup | Already selected for US-PEND-020; only needed if content-based similarity is added later |

### Add to `requirements.txt`:
```
scikit-learn>=1.5.0
```

---

## ⚠️ VERIFIED: Actual AI Page Structure

The `course_assembler.py:87` and `course_generator.py:244-250` reveal the ACTUAL structure of AI-generated pages:

```python
# course_assembler.py:87
components_data = page_spec.get("components", [])

# course_generator.py:244-250
components.append({
    "component_type": "text-content",   # ← KEY FIELD for type identification
    "order_index": 0,
    "data": {
        "content": "<h2>Title</h2>\n...",
    },
})

# Known component_type values from course_generator.py:
# "text-content", "accordion", "quiz", "video-embed", "image-gallery"
```

**This means `_extract_signature()` must look for `"components"` (not `"blocks"`).** The fallback `data.get("blocks", data.get("components", []))` is correct ordering — it checks both, with `components` as the fallback. But the doc's example in the validation section uses `'blocks'` which would miss real AI-generated pages. The example has been corrected below.

---

## Enriched Implementation

### Detection Algorithm Design

```
AI-generated page content
    │  course_assembler.py output: { title, template_type, components: [...] }
    ▼
Stage 1: Structural Extraction
    Extract from components[]: component_types, field_count, nesting_depth
    │
    ▼
Stage 2: Novelty Detection  
    TF-IDF vectorize text signatures → cosine similarity matrix
    If max_similarity < THRESHOLD → NOVEL candidate
    │
    ▼
Template Candidate (stored in ai_template_candidates table, status=pending)
```

### Parameter Justification

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `NOVELTY_THRESHOLD` | 0.7 | Standard cosine similarity threshold for text: <0.7 = substantially different documents. Based on TF-IDF literature (Manning et al., 2008). Tunable via constructor. |
| `MIN_PAGE_COMPLEXITY` | 3 | Fewer than 3 components = trivial page (e.g., single text block). Not worth harvesting as a template. |
| `TF-IDF ngram_range` | (2, 4) | Character-level bigrams through quadgrams capture both short component type names ("quiz") and longer field names ("content"). |
| `TF-IDF max_features` | 500 | Limits vector dimensionality. 500 features covers ~50 template types × ~10 fields each. |

### File: `app/services/ai/template_harvester.py`

```python
"""Template pattern harvester — detects novel patterns in AI-generated content."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

NOVELTY_THRESHOLD = 0.7   # < 0.7 = novel pattern (Manning et al., 2008)
MIN_PAGE_COMPLEXITY = 3    # Minimum component count for template candidacy
KNOWN_COMPONENT_TYPES = {
    "text-content", "accordion", "quiz", "video-embed",
    "image-gallery", "table", "flashcard", "scenario",
}

class TemplateHarvester:
    """Detects novel template patterns in AI-generated course content.

    Usage:
        harvester = TemplateHarvester()
        candidates = await harvester.analyze(generated_pages, existing_templates)
        for candidate in candidates:
            await repo.save_candidate(candidate)
    """

    def __init__(self, similarity_threshold: float = NOVELTY_THRESHOLD):
        self.threshold = similarity_threshold
        self._vectorizer = TfidfVectorizer(
            analyzer='char_wb',      # Character-level word-boundary n-grams
            ngram_range=(2, 4),       # Bigrams through quadgrams
            max_features=500,          # Dimensionality limit
        )

    async def analyze(
        self,
        generated_pages: List[Dict[str, Any]],
        existing_templates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
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
                    "content_sample": self._truncate_content(page.get("content", {})),
                    "extracted_at": datetime.utcnow().isoformat(),
                })
                existing_sigs.append(sig)

        return self._deduplicate(candidates)

    def _extract_signature(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract structural signature from AI-generated page content.

        AI pages use 'components' (course_assembler.py:87, course_generator.py:244).
        We check 'components' first, then 'blocks' as fallback for manually-authored pages.
        """
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {}

        # AI-generated pages use "components", manual pages may use "blocks"
        components = data.get("components", data.get("blocks", []))
        comp_types = []
        field_names = []
        total_nesting = 0

        for comp in (components or []):
            ct = comp.get("component_type", comp.get("type", "unknown"))
            comp_types.append(ct)
            # Collect field names, excluding metadata keys
            for key in comp.keys():
                if key not in ("order_index", "component_type"):
                    field_names.append(key)
            # Check for nested children
            children = comp.get("children", comp.get("items", []))
            total_nesting += len(children)

        return {
            "component_count": len(components or []),
            "component_types": sorted(set(comp_types)),
            "has_unknown_types": bool(set(comp_types) - KNOWN_COMPONENT_TYPES),
            "unique_field_count": len(set(field_names)),
            "field_names": sorted(set(field_names))[:20],
            "max_nesting_depth": total_nesting,
            "text_signature": " ".join(sorted(set(comp_types + field_names))),
        }

    def _check_novelty(
        self, sig: Dict[str, Any], existing_sigs: List[Dict[str, Any]]
    ) -> Tuple[bool, float]:
        if not existing_sigs:
            return True, 0.0
        all_texts = [s.get("text_signature", "") for s in existing_sigs]
        all_texts.append(sig.get("text_signature", ""))
        try:
            tfidf_matrix = self._vectorizer.fit_transform(all_texts)
            similarities = cosine_similarity(tfidf_matrix[-1:], tfidf_matrix[:-1])
            max_sim = float(similarities.max()) if similarities.size > 0 else 0.0
        except Exception:
            max_sim = 0.0
        return max_sim < self.threshold, max_sim

    def _deduplicate(self, candidates: List[Dict]) -> List[Dict]:
        seen = set()
        unique = []
        for c in candidates:
            if c["signature_hash"] not in seen:
                seen.add(c["signature_hash"])
                unique.append(c)
        return unique

    @staticmethod
    def _truncate_content(content: Dict, max_chars: int = 500) -> str:
        text = json.dumps(content, default=str)
        return text[:max_chars] + "..." if len(text) > max_chars else text
```

### File: `app/models/ai_template_candidate.py`

```python
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db.config import Base

class AITemplateCandidate(Base):
    __tablename__ = "ai_template_candidates"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    signature_hash: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    extracted_from_page: Mapped[str] = mapped_column(String(256))
    template_type: Mapped[str] = mapped_column(String(64), index=True)
    signature: Mapped[dict] = mapped_column(JSON)
    similarity_to_existing: Mapped[float] = mapped_column(Float, default=0.0)
    content_sample: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    occurrence_count: Mapped[int] = mapped_column(default=1)
    course_count: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Novel AI-generated page patterns detected and stored as candidates | After course generation → `SELECT COUNT(*) FROM ai_template_candidates` |
| AC-2 | Admin can list, review, approve, or reject candidates | `GET /api/v1/admin/templates/candidates?status=pending` |
| AC-3 | Harvesting doesn't slow down course generation | Fire-and-forget: `asyncio.create_task(harvester.analyze(...))` |
| AC-4 | Candidates deduplicated by signature hash | No two candidates with same `signature_hash` |

---

## Validation

```bash
pip install scikit-learn>=1.5.0

PYTHONPATH=. alembic revision --autogenerate -m "add_template_candidates"
PYTHONPATH=. alembic upgrade head

# Test with REAL AI page structure (components, not blocks)
PYTHONPATH=. python -c "
from app.services.ai.template_harvester import TemplateHarvester
h = TemplateHarvester()
sig = h._extract_signature({
    'components': [
        {'component_type': 'text-content', 'data': {'content': 'Intro text'}},
        {'component_type': 'quiz', 'data': {'questions': 5}},
        {'component_type': 'accordion', 'data': {'title': 'FAQ'}},
    ]
})
print(f'component_count: {sig[\"component_count\"]}')  # Expected: 3
print(f'component_types: {sig[\"component_types\"]}')   # Expected: ['accordion', 'quiz', 'text-content']
print(f'text_signature: {sig[\"text_signature\"]}')
assert sig['component_count'] == 3
assert sig['has_unknown_types'] == False
print('OK: Signature extracted correctly from AI page structure')
"
```
