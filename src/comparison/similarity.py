"""
Step 5 similarity screen: S_AA, S_BB, S_AB via cosine similarity.

Uses observation embeddings when present; otherwise a deterministic
bag-of-words hashing embedder over ``answer`` text (offline-capable).

Similarity is triage — never the sole ship decision.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Iterable

from src.comparison.models import RunObservation, SimilarityResult
from src.comparison.pairwise import mean, percentile


_TOKEN = re.compile(r"[a-z0-9]+", re.I)


def hash_embed(text: str, *, dim: int = 64) -> list[float]:
    """Lightweight deterministic bag-of-words hash embedding (no external model)."""
    vec = [0.0] * dim
    tokens = _TOKEN.findall((text or "").lower())
    if not tokens:
        return vec
    for tok in tokens:
        h = hash(tok) % dim
        vec[h] += 1.0
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; returns 0.0 if either vector is empty/zero."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def _case_embeddings(
    observations: Iterable[RunObservation],
    *,
    arm: str,
) -> dict[str, list[list[float]]]:
    """test_case_id → list of embedding vectors (one per rep with answer/embedding)."""
    by_case: dict[str, list[list[float]]] = defaultdict(list)
    for obs in observations:
        if obs.candidate != arm:
            continue
        if obs.embedding:
            by_case[obs.test_case_id].append([float(x) for x in obs.embedding])
        elif obs.answer:
            by_case[obs.test_case_id].append(hash_embed(obs.answer))
    return by_case


def _within_arm_similarities(by_case: dict[str, list[list[float]]]) -> list[float]:
    """Mean pairwise cosine across reps within each case (self-similarity)."""
    sims: list[float] = []
    for _cid, vecs in by_case.items():
        if len(vecs) < 2:
            continue
        pair_sims: list[float] = []
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                pair_sims.append(cosine(vecs[i], vecs[j]))
        if pair_sims:
            m = mean(pair_sims)
            if m is not None:
                sims.append(m)
    return sims


def _cross_arm_similarities(
    a_by_case: dict[str, list[list[float]]],
    b_by_case: dict[str, list[list[float]]],
) -> tuple[list[float], list[str]]:
    """Per-case mean S_AB and list of case ids in the same order."""
    sims: list[float] = []
    case_ids: list[str] = []
    for cid in sorted(set(a_by_case) & set(b_by_case)):
        a_vecs = a_by_case[cid]
        b_vecs = b_by_case[cid]
        if not a_vecs or not b_vecs:
            continue
        # Mean embedding per arm then cosine, plus all cross pairs averaged
        cross: list[float] = []
        for va in a_vecs:
            for vb in b_vecs:
                cross.append(cosine(va, vb))
        m = mean(cross)
        if m is None:
            continue
        sims.append(m)
        case_ids.append(cid)
    return sims, case_ids


def compute_similarity_screen(
    observations: list[RunObservation],
    *,
    consistency_tolerance: float = 0.05,
) -> SimilarityResult | None:
    """
    Compute S_AA, S_BB, S_AB; flag cases below 5th percentile of S_AA.

    Returns None when insufficient answer/embedding data.
    """
    a_by = _case_embeddings(observations, arm="a")
    b_by = _case_embeddings(observations, arm="b")
    s_aa = _within_arm_similarities(a_by)
    s_bb = _within_arm_similarities(b_by)
    s_ab, ab_cases = _cross_arm_similarities(a_by, b_by)

    if not s_aa and not s_ab:
        return None

    t_sim = percentile(sorted(s_aa), 5.0) if s_aa else None
    divergent: list[str] = []
    if t_sim is not None:
        for cid, sim in zip(ab_cases, s_ab, strict=True):
            if sim < t_sim:
                divergent.append(cid)

    mean_aa = mean(s_aa)
    mean_bb = mean(s_bb)
    mean_ab = mean(s_ab)

    inside_band = True
    if mean_aa is not None and mean_bb is not None and mean_ab is not None:
        lo = min(mean_aa, mean_bb)
        hi = max(mean_aa, mean_bb)
        # Allow small slack below the lower floor
        inside_band = mean_ab >= lo - 0.02

    consistency_ok = True
    consistency_note = ""
    if mean_aa is not None and mean_bb is not None:
        gap = mean_aa - mean_bb
        if gap > consistency_tolerance:
            consistency_ok = False
            consistency_note = (
                f"CONSISTENCY FLAG: B self-similarity is materially below A "
                f"(S_AA−S_BB={gap:.3f} > {consistency_tolerance})."
            )
        else:
            consistency_note = "B is not materially less self-consistent than A."

    method = "embedding" if any(o.embedding for o in observations) else "hash_bow_answer"
    return SimilarityResult(
        s_aa_mean=mean_aa,
        s_aa_std=_std(s_aa),
        s_bb_mean=mean_bb,
        s_bb_std=_std(s_bb),
        s_ab_mean=mean_ab,
        s_ab_std=_std(s_ab),
        t_sim=t_sim,
        divergent_case_ids=divergent,
        inside_band=inside_band,
        consistency_ok=consistency_ok,
        consistency_note=consistency_note,
        n_cases=len(ab_cases),
        method=method,
        note=(
            f"{len(divergent)} of {len(ab_cases)} inputs below T_sim → SME REVIEW REQUIRED"
            if divergent
            else "No divergent cases below T_sim."
        ),
    )


def _std(values: list[float]) -> float | None:
    if len(values) < 2:
        return 0.0 if values else None
    m = sum(values) / len(values)
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)
