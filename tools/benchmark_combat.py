"""固定规模战斗基准：15 名玩家与 15 名道侣对战同规模队伍。"""

# ruff: noqa: I001

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.combat.models import RuntimeCombatantSnapshot
from game.core.data import JsonDataService
from tools.combat_support import isolated_combat_service


LISTENER_EVENTS = (
    "战斗开始",
    "行动开始",
    "行动决策前",
    "普通攻击前",
    "命中后",
    "造成伤害前",
    "造成伤害后",
    "受到伤害后",
    "行动结束",
    "死亡后",
    "战斗结束",
    "暴击后",
)


def build_team(
    prefix: str, pair_count: int, listeners: int = 0
) -> tuple[RuntimeCombatantSnapshot, ...]:
    values: list[RuntimeCombatantSnapshot] = []
    techniques = _listener_techniques(listeners)
    for index in range(pair_count):
        values.append(
            RuntimeCombatantSnapshot(
                id=f"{prefix}-玩家-{index + 1:02d}",
                name=f"{prefix}玩家{index + 1:02d}",
                combatant_type="修士",
                techniques=techniques,
                attributes={
                    "血气上限": 240.0,
                    "精神上限": 120.0,
                    "攻击": 42.0,
                    "防御": 18.0,
                    "速度": 100.0,
                    "命中率": 100.0,
                },
            )
        )
        values.append(
            RuntimeCombatantSnapshot(
                id=f"{prefix}-道侣-{index + 1:02d}",
                name=f"{prefix}道侣{index + 1:02d}",
                combatant_type="道侣",
                techniques=techniques,
                attributes={
                    "血气上限": 210.0,
                    "精神上限": 160.0,
                    "攻击": 34.0,
                    "防御": 16.0,
                    "速度": 105.0,
                    "命中率": 100.0,
                },
            )
        )
    return tuple(values)


def _listener_techniques(count: int) -> tuple[dict[str, object], ...]:
    if count <= 0:
        return ()
    listeners = []
    for index in range(count):
        listeners.append(
            {
                "能力": "监听事件",
                "事件": LISTENER_EVENTS[index % len(LISTENER_EVENTS)],
                "观察角色": "来源",
                "阵营关系": "自身",
                "效果": [
                    {
                        "能力": "记录战斗事实",
                        "名称": f"基准监听{index + 1}",
                        "值": 1,
                        "方式": "覆盖",
                        "保留数量": 1,
                    }
                ],
            }
        )
    return (
        {
            "编号": "benchmark-passives",
            "名称": "基准被动",
            "出生序号": 1,
            "能力": [
                {
                    "能力": "被动技能",
                    "名称": "基准监听组",
                    "结算顺序": 1,
                    "效果": listeners,
                }
            ],
        },
    )


def run(
    rounds: int,
    warmup: int,
    action_limit: int,
    listeners: int,
    left_users: int,
    right_users: int,
) -> None:
    data = JsonDataService(ROOT / "data")
    data.initialize()
    left = build_team("甲方", left_users, listeners)
    right = build_team("乙方", right_users, listeners)
    with isolated_combat_service(data) as combat:
        for seed in range(warmup):
            combat._simulate_runtime_teams(
                left=left,
                right=right,
                medicine_definitions={},
                seed=seed,
                action_limit=action_limit,
            )

        durations: list[float] = []
        actions: list[int] = []
        events: list[int] = []
        for seed in range(rounds):
            started = time.perf_counter()
            outcome = combat._simulate_runtime_teams(
                left=left,
                right=right,
                medicine_definitions={},
                seed=seed,
                action_limit=action_limit,
            )
            durations.append((time.perf_counter() - started) * 1000)
            actions.append(outcome.actions)
            events.append(len(outcome.events))

    ordered = sorted(durations)
    p95 = ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))]
    print(
        f"参战规模: {left_users}玩家+{left_users}道侣 vs "
        f"{right_users}玩家+{right_users}道侣（共{len(left) + len(right)}名）"
    )
    print(
        f"监听规模: 每名 {listeners} 个，共 {listeners * (len(left) + len(right))} 个"
    )
    print(f"动作上限: {action_limit}")
    print(f"样本数: {rounds}（预热 {warmup}）")
    print(
        f"耗时毫秒: min={min(durations):.3f}, "
        f"median={statistics.median(durations):.3f}, "
        f"p95={p95:.3f}, max={max(durations):.3f}"
    )
    print(
        f"战斗动作: median={statistics.median(actions):.0f}, "
        f"事件: median={statistics.median(events):.0f}"
    )
    print(f"折算吞吐: {1000 / statistics.median(durations):.2f} 场/秒")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--actions", type=int, default=300)
    parser.add_argument("--listeners", type=int, default=0)
    parser.add_argument("--left-users", type=int, default=15)
    parser.add_argument("--right-users", type=int, default=15)
    args = parser.parse_args()
    if (
        args.rounds <= 0
        or args.warmup < 0
        or args.actions <= 0
        or args.listeners < 0
        or args.left_users <= 0
        or args.right_users <= 0
    ):
        parser.error(
            "rounds、actions、left-users、right-users 必须为正数，"
            "warmup、listeners 不能为负数"
        )
    run(
        args.rounds,
        args.warmup,
        args.actions,
        args.listeners,
        args.left_users,
        args.right_users,
    )
