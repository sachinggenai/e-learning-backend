# US-PEND-031: Template Definition Harvesting from AI Proposals — FULLY ENRICHED

| Field | Value |
|-------|-------|
| **Type** | 🆕 New Task (Feature) |
| **Priority** | ⚪ LOW |
| **Batch** | 7 — Long-Term / Deferred |
| **Depends On** | US-PEND-027 (template harvester) |
| **Estimated Effort** | 3-4 days |
| **Target Files** | Depends on US-PEND-027 output |

---

## User Story

**As a** template librarian,
**I want** to automatically detect when AI is consistently generating novel structural patterns that could become reusable templates,
**So that** the template library evolves based on what AI and users find useful.

---

## Intent of Work

This is the next maturity level after US-PEND-027 (basic template harvesting). While PEND-027 captures individual novel patterns, this story adds intelligence:
- **Pattern clustering:** Group similar AI-generated structures across multiple courses
- **Adoption scoring:** Patterns used in 3+ courses with high user acceptance → auto-promote
- **Admin dashboard:** Pattern frequency, adoption trends

---

## 🔧 Open-Source Tooling

| Tool | Version | Purpose | Why Selected |
|------|---------|---------|-------------|
| **scikit-learn** | 1.5.x | DBSCAN clustering | Already selected for US-PEND-027; `DBSCAN` clusters similar signatures without pre-specifying number of clusters |
| **sentence-transformers** | 3.x | Embedding signatures for clustering | Already selected for US-PEND-020; reuse existing model |

---

## Enriched Implementation

### Key Addition: Pattern Clustering Service

```python
# app/services/ai/pattern_clusterer.py

from sklearn.cluster import DBSCAN
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

class PatternClusterer:
    """Clusters similar template candidates across courses.

    Uses DBSCAN with cosine distance to group similar structural patterns.
    """

    def cluster(
        self, candidates: list[dict], min_courses: int = 3
    ) -> list[dict]:
        """Group candidates into clusters. Returns clusters with 3+ courses."""
        if len(candidates) < min_courses:
            return []

        # Build signature embedding matrix via TF-IDF of text signatures
        from sklearn.feature_extraction.text import TfidfVectorizer
        vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4))
        texts = [c["signature"].get("text_signature", "") for c in candidates]
        tfidf_matrix = vectorizer.fit_transform(texts)

        # Compute cosine distance matrix
        cosine_dist = 1 - cosine_similarity(tfidf_matrix)

        # Cluster with DBSCAN
        clustering = DBSCAN(eps=0.3, min_samples=2, metric="precomputed")
        labels = clustering.fit_predict(cosine_dist)

        # Group by cluster label, count unique courses
        clusters = {}
        for i, label in enumerate(labels):
            if label == -1:  # Noise
                continue
            clusters.setdefault(int(label), []).append(candidates[i])

        # Filter: only clusters appearing in 3+ courses
        result = []
        for label, members in clusters.items():
            unique_courses = len(set(m.get("course_id", "unknown") for m in members))
            if unique_courses >= min_courses:
                result.append({
                    "cluster_id": label,
                    "member_count": len(members),
                    "course_count": unique_courses,
                    "representative_signature": members[0]["signature"],
                    "members": members,
                    "auto_promote": unique_courses >= 5,  # 5+ courses → auto-approve
                })
        return result
```

### Integration with PEND-027

Extend `TemplateHarvester.analyze()` to call `PatternClusterer` after harvesting:

```python
# After harvesting individual candidates:
clusterer = PatternClusterer()
clusters = clusterer.cluster(all_candidates, min_courses=3)

# Auto-promote high-frequency patterns
for cluster in clusters:
    if cluster["auto_promote"]:
        await self._auto_promote_to_template(cluster)
```

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Recurring patterns across courses are clustered and counted | After 3+ courses use same pattern → cluster created |
| AC-2 | High-frequency patterns (5+ courses) flagged for auto-promotion | `auto_promote=True` in cluster result |
| AC-3 | Pattern metrics queryable via admin API | `GET /api/v1/admin/templates/clusters` |

---

## Validation

```bash
# Uses same deps as PEND-027 (scikit-learn already installed)
PYTHONPATH=. python -c "
from app.services.ai.pattern_clusterer import PatternClusterer
# Test with sample data
clusterer = PatternClusterer()
test_data = [
    {'signature': {'text_signature': 'text quiz assessment'}, 'course_id': 'C1'},
    {'signature': {'text_signature': 'text quiz assessment'}, 'course_id': 'C2'},
    {'signature': {'text_signature': 'text quiz assessment'}, 'course_id': 'C3'},
    {'signature': {'text_signature': 'video text quiz'}, 'course_id': 'C1'},
]
clusters = clusterer.cluster(test_data, min_courses=3)
print(f'Clusters: {len(clusters)}')
# Expected: 1 cluster (text quiz assessment pattern in 3+ courses)
"
```
