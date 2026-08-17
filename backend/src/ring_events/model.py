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

# How much per-epoch evidence counts against the transition prior when decoding
# a night. A forest averages many leaf distributions, so its probabilities come
# out flat rather than as calibrated likelihoods — at 1.0 the prior overwhelms
# them and every night collapses toward the commonest stage.
#
# Chosen by sweeping leave-one-night-out over ten nights: 1.0 scored 0.50
# balanced, 4.0 scored 0.71, 12.0 scored 0.70. It is a broad plateau (3-8 all
# land within a point), not a knife edge, but it was picked on the same
# cross-validation reported elsewhere, so treat that number as mildly
# optimistic.
#
# Raised to 8.0 alongside the class-weight change below; the two were swept
# together, and 7.0 scores the same within noise.
DEFAULT_EMISSION_WEIGHT = 8.0

# How hard to correct for rare stages. 1.0 makes every class count equally,
# which stops the model answering "light" everywhere but overshoots the other
# way: it predicts rare stages more often than they occur. 0.0 leaves the
# natural frequencies alone. Anywhere between trades recall against
# calibration.
#
# At 1.0 the model reported REM about 6 minutes a night too high and light 28
# too low — invisible in per-epoch accuracy, which counts errors in both
# directions equally, but plain against the cloud's own nightly totals.
#
# 0.85 was picked from a 30-cell sweep because REM's lean is flat there, not
# because one cell scored well: across emission weights 5, 6, 7, 8 and 10 it
# reads +1, -2, -1, -1, +2. At 0.75 the same metric swings from -10 to -2
# between two adjacent cells, which is a knife edge and was rejected. The cost
# is 0.002 accuracy and 0.009 balanced accuracy.
DEFAULT_CLASS_WEIGHT_POWER = 0.85

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
    # Respiratory *rate* is deliberately absent. It is an accurate metric —
    # 0.39 breaths/min against Oura's own figure — but as a feature it cost
    # 0.05 balanced accuracy, measured leave-one-night-out. It is often
    # missing (a bucket needs several clean breath cycles), and with only a
    # handful of features sampled per split, a noisy one crowds out useful
    # ones. Irregularity, which does not need the cycle length, already
    # carries the part that separates REM.
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


def learn_transitions(
    sequences: List[List[str]], smoothing: float = 1.0
) -> Tuple[List[List[float]], List[float]]:
    """Stage-to-stage probabilities and a starting distribution.

    Sleep is strongly sequential — three quarters of epochs continue the
    previous stage, and REM never runs straight into deep. Classifying each
    epoch alone throws that away.

    Smoothed, so a transition unseen in a handful of nights is treated as rare
    rather than impossible.
    """
    size = len(STAGES)
    index_of = {stage: i for i, stage in enumerate(STAGES)}
    counts = [[smoothing] * size for _ in range(size)]
    starts = [smoothing] * size

    for labels in sequences:
        if not labels:
            continue
        starts[index_of[labels[0]]] += 1
        for a, b in zip(labels, labels[1:]):
            counts[index_of[a]][index_of[b]] += 1

    transitions = [[c / sum(row) for c in row] for row in counts]
    initial = [c / sum(starts) for c in starts]
    return transitions, initial


@dataclass
class Forest:
    """Bagged shallow trees, with per-feature medians for missing values."""

    trees: List[Node] = field(default_factory=list)
    medians: List[float] = field(default_factory=list)
    features: List[str] = field(default_factory=lambda: list(FEATURES))
    stages: List[str] = field(default_factory=lambda: list(STAGES))
    # Sequence structure. Absent on a model fitted before this existed, in
    # which case decoding falls back to per-epoch argmax.
    transitions: Optional[List[List[float]]] = None
    initial: Optional[List[float]] = None
    emission_weight: float = DEFAULT_EMISSION_WEIGHT

    def to_json(self) -> Dict[str, Any]:
        return {
            "version": 2,
            "features": self.features,
            "stages": self.stages,
            "medians": self.medians,
            "transitions": self.transitions,
            "initial": self.initial,
            "emission_weight": self.emission_weight,
            "trees": [tree.to_json() for tree in self.trees],
        }

    @staticmethod
    def from_json(blob: Dict[str, Any]) -> "Forest":
        return Forest(
            trees=[Node.from_json(t) for t in blob["trees"]],
            medians=blob["medians"],
            features=blob["features"],
            stages=blob["stages"],
            transitions=blob.get("transitions"),
            initial=blob.get("initial"),
            emission_weight=blob.get("emission_weight", DEFAULT_EMISSION_WEIGHT),
        )

    def decode(
        self,
        sequence: List[Dict[str, Optional[float]]],
        emission_weight: Optional[float] = None,
    ) -> List[Tuple[str, float]]:
        """The most likely *sequence* of stages, not the most likely stage at
        each epoch independently.

        Viterbi over the forest's per-epoch probabilities. Those are used
        directly as emission likelihoods: the fit weights classes equally, so
        its effective prior is uniform and posterior is proportional to
        likelihood.

        Returns (stage, confidence) per epoch, where confidence stays the
        forest's own vote share — the decode changes which stage is chosen, not
        how sure the evidence was.
        """
        probabilities = [self.predict_proba(f) for f in sequence]
        if not probabilities:
            return []
        if not self.transitions or not self.initial:
            return [
                (self.stages[p.index(max(p))], round(max(p), 2))
                for p in probabilities
            ]

        size = len(self.stages)
        floor = 1e-9  # a zero-probability stage must not poison the whole path
        weight = self.emission_weight if emission_weight is None else emission_weight

        def log(x: float) -> float:
            return math.log(max(x, floor))

        def emit(step: int, stage: int) -> float:
            return weight * log(probabilities[step][stage])

        score = [log(self.initial[s]) + emit(0, s) for s in range(size)]
        back: List[List[int]] = []
        for step in range(1, len(probabilities)):
            previous, score = score, [0.0] * size
            choice = [0] * size
            for current in range(size):
                best, best_from = None, 0
                for prior in range(size):
                    value = previous[prior] + log(self.transitions[prior][current])
                    if best is None or value > best:
                        best, best_from = value, prior
                score[current] = best + emit(step, current)
                choice[current] = best_from
            back.append(choice)

        last = max(range(size), key=lambda s: score[s])
        path = [last]
        for choice in reversed(back):
            last = choice[last]
            path.append(last)
        path.reverse()

        return [
            (self.stages[s], round(probabilities[i][s], 2))
            for i, s in enumerate(path)
        ]

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
    sequences: Optional[List[List[str]]] = None,
    trees: int = 60,
    emission_weight: float = DEFAULT_EMISSION_WEIGHT,
    class_weight_power: float = DEFAULT_CLASS_WEIGHT_POWER,
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
    weight_for = [(total / (len(STAGES) * c)) ** class_weight_power for c in counts]
    weights = [weight_for[label] for label in encoded]

    per_split = max(2, int(math.sqrt(len(FEATURES))))
    forest = Forest(medians=medians, emission_weight=emission_weight)
    if sequences:
        forest.transitions, forest.initial = learn_transitions(sequences)
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
