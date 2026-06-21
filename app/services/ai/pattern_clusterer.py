"""Pattern clusterer for template harvesting v2 — US-PEND-031.

Clusters similar template candidates across courses using DBSCAN.
Auto-promotes high-frequency patterns (5+ courses).
Depends on TemplateHarvester from US-PEND-027.
"""
from __future__ import annotations

import logging
from typing import List, Dict

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)


class PatternClusterer:
    """Clusters similar template candidates across multiple courses."""

    def cluster(self, candidates: List[Dict], min_courses: int = 3) -> List[Dict]:
        if len(candidates) < min_courses:
            return []

        vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4))
        texts = [c["signature"].get("text_signature", "") for c in candidates]
        if not any(texts):
            return []

        tfidf = vectorizer.fit_transform(texts)
        cosine_dist = 1 - cosine_similarity(tfidf)

        clustering = DBSCAN(eps=0.3, min_samples=2, metric="precomputed")
        labels = clustering.fit_predict(cosine_dist)

        clusters = {}
        for i, label in enumerate(labels):
            if label == -1:
                continue
            clusters.setdefault(int(label), []).append(candidates[i])

        result = []
        for label, members in clusters.items():
            unique_courses = len(set(m.get("course_id", "unknown") for m in members))
            if unique_courses >= min_courses:
                result.append({
                    "cluster_id": label,
                    "member_count": len(members),
                    "course_count": unique_courses,
                    "representative_signature": members[0]["signature"],
                    "auto_promote": unique_courses >= 5,
                })
        return result
