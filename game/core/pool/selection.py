"""资源池使用的纯逆权重抽取算法。"""

from __future__ import annotations

from math import log
import random
from collections.abc import Sequence
from typing import TypeVar


T = TypeVar("T")


def inverse_weighted_sample(
    rng: random.Random,
    values: Sequence[T],
    weights: Sequence[int],
    *,
    count: int,
    replace: bool,
) -> tuple[T, ...]:
    """按 1 / 权重抽取；权重越高，抽中概率越低。"""

    candidates = list(values)
    candidate_weights = list(weights)
    amount = int(count)
    if amount < 1:
        raise ValueError("抽取数量必须是正整数")
    if not candidates or len(candidates) != len(candidate_weights):
        raise ValueError("候选对象和权重必须数量一致且不能为空")
    if any(
        isinstance(weight, bool) or not isinstance(weight, int) or weight < 1
        for weight in candidate_weights
    ):
        raise ValueError("权重必须是正整数")
    if not replace and amount > len(candidates):
        raise ValueError(
            f"展开去重抽取数量 {amount} 超过候选数量 {len(candidates)}"
        )

    result: list[T] = []
    for _ in range(amount):
        index = _inverse_weighted_index(rng, candidate_weights)
        result.append(candidates[index])
        if not replace:
            candidates.pop(index)
            candidate_weights.pop(index)
    return tuple(result)


def _inverse_weighted_index(rng: random.Random, weights: Sequence[int]) -> int:
    priorities = tuple(
        -log(max(float(rng.random()), 1e-300)) * weight
        for weight in weights
    )
    return min(range(len(priorities)), key=priorities.__getitem__)


__all__ = ["inverse_weighted_sample"]
