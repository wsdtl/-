"""统一的整数逆权重抽取。"""

from __future__ import annotations

from math import log
from typing import Any, Sequence, TypeVar


T = TypeVar("T")


def inverse_weighted_choice(
    rng: Any,
    values: Sequence[T],
    weights: Sequence[int],
) -> T:
    """按 1 / 权重抽取；权重越高，抽中概率越低。"""

    candidates = tuple(values)
    inverse_weights = tuple(weights)
    if not candidates or len(candidates) != len(inverse_weights):
        raise ValueError("候选对象和权重必须数量一致且不能为空")
    if any(
        isinstance(weight, bool) or not isinstance(weight, int) or weight < 1
        for weight in inverse_weights
    ):
        raise ValueError("权重必须是正整数")

    # 指数竞赛可直接使用整数稀有权重，并保持抽中率与 1 / 权重 成正比。
    scores = tuple(
        -log(max(float(rng.random()), 1e-300)) * weight
        for weight in inverse_weights
    )
    return candidates[min(range(len(candidates)), key=scores.__getitem__)]
