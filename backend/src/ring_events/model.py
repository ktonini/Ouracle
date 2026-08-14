"""A small random forest for sleep staging, in pure Python.

Hand-tuned thresholds turned out to be worse than answering "light" for every
epoch — they were fitted to a single night and did not survive contact with
six. This learns the thresholds instead.

Deliberately dependency-free. The server container carries no numpy or
scikit-learn, and at this size (a few hundred epochs, a dozen features) a
compact forest costs little to train and nothing to ship: the fitted model
serialises to JSON and is evaluated by `predict`, so inference needs no
libraries at all.

Kept small on purpose — shallow trees, few features per split. With six nights
of labels, a large model would memorise them.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

STAGES = ["deep", "light", "rem", "awake"]

# Raw per-epoch signals, as they arrive from the ring.
RAW_FEATURES = [
    "heart_rate",
    "movement",
    "movement_peak",
    "temperature",
    "hrv",
    "sdnn_rmssd",
    "pnn50",
    "breath_irregularity",
]

# Everything the model actually sees. The night-relative terms matter more
# than the raw ones: resting heart rate differs between people and between
# nights, so "3 bpm above this night's floor" generalises where "64 bpm"
# cannot.
FEATURES = RAW_FEATURES + [
    "progress",          # position through the night, 0…1
    "hr_from_floor",     # bpm above this night's 10th percentile
    "hr_z",             # heart rate in this night's own spread
    "movement_ratio",    # movement against this night's median
    "hr_delta",          # change from the previous epoch
    "hr_trend",          # local slope across ±2 epochs
    "movement_recent",   # movement over the surrounding epochs
]


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(int(len(ordered) * fraction), len(ordered) - 1)]


def featurise_night(rows: List[Dict[str, Any]]) -> List[Dict[str, Optional[float]]]:
    """Per-epoch feature dicts for one night, in time order.

    `rows` are the paired rows from `training.build_dataset` — one per epoch,
    sorted by timestamp.
    """
    rates = [r["heart_rate"] for r in rows if r.get("heart_rate") is not None]
    moves = [r["movement"] for r in rows if r.get("movement") is not None]
    if not rates:
        return []

    floor = _percentile(rates, 0.1)
    middle = median(rates)
    spread = (
        sum((r - middle) ** 2 for r in rates) / len(rates)
    ) ** 0.5 or 1.0
    quiet = median(moves) if moves else 0.0

    out: List[Dict[str, Optional[float]]] = []
    span = max(len(rows) - 1, 1)
    for index, row in enumerate(rows):
        rate = row.get("heart_rate")
        movement = row.get("movement")

        previous = rows[index - 1].get("heart_rate") if index else None
        window = [
            r.get("heart_rate")
            for r in rows[max(0, index - 2) : index + 3]
            if r.get("heart_rate") is not None
        ]
        moves_window = [
            r.get("movement")
            for r in rows[max(0, index - 2) : index + 3]
            if r.get("movement") is not None
        ]

        features: Dict[str, Optional[float]] = {
            name: row.get(name) for name in RAW_FEATURES
        }
        features["progress"] = index / span
        features["hr_from_floor"] = None if rate is None else rate - floor
        features["hr_z"] = None if rate is None else (rate - middle) / spread
        features["movement_ratio"] = (
            None if movement is None else movement / (quiet or 1e-6)
        )
        features["hr_delta"] = (
            None if rate is None or previous is None else rate - previous
        )
        features["hr_trend"] = (
            (window[-1] - window[0]) / len(window) if len(window) > 1 else None
        )
        features["movement_recent"] = (
            sum(moves_window) / len(moves_window) if moves_window else None
        )
        out.append(features)
    return out


@dataclass
class Node:
    """A split, or a leaf holding class counts."""

    feature: Optional[int] = None
    threshold: float = 0.0
    left: Optional["Node"] = None
    right: Optional["Node"] = None
    counts: Optional[List[float]] = None

    def to_json(self) -> Dict[str, Any]:
        if self.counts is not None:
            return {"counts": self.counts}
        return {
            "f": self.feature,
            "t": self.threshold,
            "l": self.left.to_json(),  # type: ignore[union-attr]
            "r": self.right.to_json(),  # type: ignore[union-attr]
        }

    @staticmethod
    def from_json(blob: Dict[str, Any]) -> "Node":
        if "counts" in blob:
            return Node(counts=blob["counts"])
        return Node(
            feature=blob["f"],
            threshold=blob["t"],
            left=Node.from_json(blob["l"]),
            right=Node.from_json(blob["r"]),
        )


def _gini(counts: List[float]) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    return 1.0 - sum((c / total) ** 2 for c in counts)


def _class_counts(labels: List[int], weights: List[float]) -> List[float]:
    counts = [0.0] * len(STAGES)
    for label, weight in zip(labels, weights):
        counts[label] += weight
    return counts


def _grow(
    rows: List[List[float]],
    labels: List[int],
    weights: List[float],
    candidates: List[int],
    depth: int,
    max_depth: int,
    min_leaf: int,
    rng: random.Random,
) -> Node:
    counts = _class_counts(labels, weights)
    if depth >= max_depth or len(labels) < 2 * min_leaf or _gini(counts) == 0.0:
        return Node(counts=counts)

    best: Optional[Tuple[float, int, float]] = None
    parent = _gini(counts) * sum(counts)

    for feature in candidates:
        values = sorted({row[feature] for row in rows})
        if len(values) < 2:
            continue
        # Midpoints between observed values; a handful is plenty at this size.
        cuts = [(a + b) / 2 for a, b in zip(values, values[1:])]
        if len(cuts) > 24:
            step = len(cuts) / 24
            cuts = [cuts[int(i * step)] for i in range(24)]

        for cut in cuts:
            left_labels, left_weights, right_labels, right_weights = [], [], [], []
            for row, label, weight in zip(rows, labels, weights):
                if row[feature] <= cut:
                    left_labels.append(label)
                    left_weights.append(weight)
                else:
                    right_labels.append(label)
                    right_weights.append(weight)
            if len(left_labels) < min_leaf or len(right_labels) < min_leaf:
                continue
            left_counts = _class_counts(left_labels, left_weights)
            right_counts = _class_counts(right_labels, right_weights)
            cost = _gini(left_counts) * sum(left_counts) + _gini(right_counts) * sum(
                right_counts
            )
            if best is None or cost < best[0]:
                best = (cost, feature, cut)

    if best is None or best[0] >= parent:
        return Node(counts=counts)

    _, feature, cut = best
    left_rows, left_labels, left_weights = [], [], []
    right_rows, right_labels, right_weights = [], [], []
    for row, label, weight in zip(rows, labels, weights):
        if row[feature] <= cut:
            left_rows.append(row)
            left_labels.append(label)
            left_weights.append(weight)
        else:
            right_rows.append(row)
            right_labels.append(label)
            right_weights.append(weight)

    return Node(
        feature=feature,
        threshold=cut,
        left=_grow(left_rows, left_labels, left_weights, candidates, depth + 1,
                   max_depth, min_leaf, rng),
        right=_grow(right_rows, right_labels, right_weights, candidates, depth + 1,
                    max_depth, min_leaf, rng),
    )


@dataclass
class Forest:
    """Bagged shallow trees, with per-feature medians for missing values."""

    trees: List[Node] = field(default_factory=list)
    medians: List[float] = field(default_factory=list)
    features: List[str] = field(default_factory=lambda: list(FEATURES))
    stages: List[str] = field(default_factory=lambda: list(STAGES))

    def to_json(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "features": self.features,
            "stages": self.stages,
            "medians": self.medians,
            "trees": [tree.to_json() for tree in self.trees],
        }

    @staticmethod
    def from_json(blob: Dict[str, Any]) -> "Forest":
        return Forest(
            trees=[Node.from_json(t) for t in blob["trees"]],
            medians=blob["medians"],
            features=blob["features"],
            stages=blob["stages"],
        )

    def _row(self, features: Dict[str, Optional[float]]) -> List[float]:
        return [
            (
                features.get(name)
                if features.get(name) is not None
                else self.medians[index]
            )
            for index, name in enumerate(self.features)
        ]

    def predict_proba(self, features: Dict[str, Optional[float]]) -> List[float]:
        row = self._row(features)
        totals = [0.0] * len(self.stages)
        for tree in self.trees:
            node = tree
            while node.counts is None:
                node = node.left if row[node.feature] <= node.threshold else node.right  # type: ignore[assignment,index]
            total = sum(node.counts) or 1.0
            for index, count in enumerate(node.counts):
                totals[index] += count / total
        scale = sum(totals) or 1.0
        return [t / scale for t in totals]

    def predict(self, features: Dict[str, Optional[float]]) -> str:
        proba = self.predict_proba(features)
        return self.stages[proba.index(max(proba))]


def fit(
    samples: List[Dict[str, Optional[float]]],
    labels: List[str],
    trees: int = 60,
    max_depth: int = 5,
    min_leaf: int = 8,
    seed: int = 20260814,
) -> Forest:
    """Fit a forest. Classes are weighted so rare stages still count.

    REM and wake are a small minority of epochs, and an unweighted fit answers
    "light" almost everywhere — which is precisely the failure we are trying
    to beat.
    """
    rng = random.Random(seed)
    index_of = {stage: i for i, stage in enumerate(STAGES)}

    medians: List[float] = []
    for name in FEATURES:
        present = [s[name] for s in samples if s.get(name) is not None]
        medians.append(median(present) if present else 0.0)

    rows = [
        [
            (s.get(name) if s.get(name) is not None else medians[i])
            for i, name in enumerate(FEATURES)
        ]
        for s in samples
    ]
    encoded = [index_of[label] for label in labels]

    counts = [encoded.count(i) or 1 for i in range(len(STAGES))]
    total = len(encoded)
    weight_for = [total / (len(STAGES) * c) for c in counts]
    weights = [weight_for[label] for label in encoded]

    per_split = max(2, int(math.sqrt(len(FEATURES))))
    forest = Forest(medians=medians)
    for _ in range(trees):
        picks = [rng.randrange(len(rows)) for _ in range(len(rows))]  # bootstrap
        candidates = rng.sample(range(len(FEATURES)), per_split)
        forest.trees.append(
            _grow(
                [rows[i] for i in picks],
                [encoded[i] for i in picks],
                [weights[i] for i in picks],
                candidates,
                0,
                max_depth,
                min_leaf,
                rng,
            )
        )
    return forest
