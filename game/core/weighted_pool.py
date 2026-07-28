"""统一的整数稀有权重抽取。"""

from __future__ import annotations

from math import log
from typing import Any, Sequence, TypeVar


T = TypeVar("T")


def rarity_weighted_choice(
    rng: Any,
    values: Sequence[T],
    weights: Sequence[int],
) -> T:
    """按 1 / 权重抽取；权重越高，对象越稀有。"""

    candidates = tuple(values)
    rarity_weights = tuple(weights)
    if not candidates or len(candidates) != len(rarity_weights):
        raise ValueError("候选对象和权重必须数量一致且不能为空")
    if any(
        isinstance(weight, bool) or not isinstance(weight, int) or weight < 1
        for weight in rarity_weights
    ):
        raise ValueError("权重必须是正整数")

    # 指数竞赛可直接使用整数稀有权重，并保持抽中率与 1 / 权重 成正比。
    scores = tuple(
        -log(max(float(rng.random()), 1e-300)) * weight
        for weight in rarity_weights
    )
    return candidates[min(range(len(candidates)), key=scores.__getitem__)]
