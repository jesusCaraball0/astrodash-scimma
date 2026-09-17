"""Accuracy, ROC-AUC, and macro precision/recall on canonical classes."""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from astrodash.infrastructure.ml.leaderboard.taxonomy import CANONICAL_CLASSES


def _empty_scores() -> dict[str, Optional[float]]:
    return {
        "accuracy": None,
        "roc": None,
        "precision": None,
        "recall": None,
        "n_scored": 0,
    }


def score_predictions(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    y_proba: Optional[Iterable[Sequence[float]]] = None,
) -> dict[str, Optional[float]]:
    """Return accuracy (percent), ROC, and macro precision/recall.

    Precision and recall are unweighted means over the five canonical classes
    (``zero_division=0``). ROC is macro one-vs-rest AUC when class scores exist
    and at least two ground-truth classes are present.
    """
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have the same length")
    if not y_true:
        return _empty_scores()

    labels = list(CANONICAL_CLASSES)
    accuracy = float(accuracy_score(y_true, y_pred))
    precision = float(
        precision_score(
            y_true, y_pred, average="macro", labels=labels, zero_division=0
        )
    )
    recall = float(
        recall_score(
            y_true, y_pred, average="macro", labels=labels, zero_division=0
        )
    )
    roc: Optional[float] = None
    if y_proba is not None and len(set(y_true)) >= 2:
        proba = np.asarray(list(y_proba), dtype=float)
        if proba.ndim == 2 and proba.shape == (len(y_true), len(labels)):
            y_idx = np.array([labels.index(y) for y in y_true], dtype=int)
            try:
                roc_value = float(
                    roc_auc_score(
                        y_idx,
                        proba,
                        multi_class="ovr",
                        average="macro",
                        labels=list(range(len(labels))),
                    )
                )
            except ValueError:
                roc = None
            else:
                roc = roc_value if np.isfinite(roc_value) else None

    return {
        "accuracy": round(accuracy * 100.0, 1),
        "roc": roc,
        "precision": precision,
        "recall": recall,
        "n_scored": len(y_true),
    }
