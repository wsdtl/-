"""读取当前位置的路边修士，不负责战斗或资产结算。"""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import random
from typing import Any

from game.content import GameContent
from game.features.didian import LocationFeature


@dataclass(frozen=True)
class NpcProfile:
    npc_id: str
    title: str
    stance: str
    description: str
    interactive: bool
    weapon: str
    techniques: tuple[str, ...]
    minimum_level: int
    maximum_level: int

    @property
    def level_text(self) -> str:
        if self.minimum_level == self.maximum_level:
            return f"Lv{self.minimum_level}"
        return f"Lv{self.minimum_level}-{self.maximum_level}"


@dataclass(frozen=True)
class CultivatorInstance:
    npc_id: str
    name: str
    level: int
    attributes: dict[str, float]
    weapon_attack: float
    techniques: tuple[dict[str, Any], ...]
    spirit_stones: int
    inventory: dict[str, int]
    auto_medicine: bool
    medicine_threshold: float


class NpcFeature:
    def __init__(self, content: GameContent, location: LocationFeature) -> None:
        self.content = content
        self.location = location

    def nearby(self, user_id: str) -> tuple[NpcProfile, ...]:
        current = self.location.current(user_id)
        return tuple(self._profile(npc_id) for npc_id in current.npcs)

    def nearby_profile(self, user_id: str, npc_name: str) -> NpcProfile | None:
        name = " ".join(str(npc_name or "").split())
        return next((npc for npc in self.nearby(user_id) if npc.npc_id == name), None)

    def talk(self, user_id: str, npc_name: str, *, seed: int | None = None) -> tuple[NpcProfile, str] | None:
        profile = self.nearby_profile(user_id, npc_name)
        if profile is None or not profile.interactive:
            return None
        dialogue = tuple(
            str(value)
            for value in self.content.npc_definitions[profile.npc_id]["身份"]["话语"]
        )
        rng = random.Random(seed) if seed is not None else random.SystemRandom()
        return profile, rng.choice(dialogue)

    def spawn(self, npc_id: str, *, seed: int | None = None) -> CultivatorInstance:
        """按修士配置生成一次独立实例，供后续切磋、事件或剧情流程使用。"""

        definition: dict[str, Any] = self.content.npc_definitions[str(npc_id)]
        rng = random.Random(seed) if seed is not None else random.SystemRandom()
        level = _roll_range(rng, definition["等级"])
        attributes = self.content.attributes_at_level(
            definition["属性"],
            self.content.player["人物"]["每级成长"],
            level,
        )
        _apply_variation(rng, attributes, definition["实力波动"])
        spirit_stones, inventory = _roll_inventory(rng, definition["纳戒"])
        strategy = definition["战斗策略"]
        return CultivatorInstance(
            npc_id=str(npc_id),
            name=str(npc_id),
            level=level,
            attributes=attributes,
            weapon_attack=float(definition["本命武器"]["攻击"]),
            techniques=tuple(
                self.content.configured_battle_techniques(
                    definition["功法"],
                    instance_prefix=f"npc:{npc_id}:{rng.getrandbits(63)}",
                )
            ),
            spirit_stones=spirit_stones,
            inventory=inventory,
            auto_medicine=rng.random() < float(strategy["用药概率"]),
            medicine_threshold=float(strategy["用药阈值"]),
        )

    def _profile(self, npc_id: str) -> NpcProfile:
        definition: dict[str, Any] = self.content.npc_definitions[npc_id]
        identity = definition["身份"]
        minimum_level, maximum_level = definition["等级"]
        return NpcProfile(
            npc_id=npc_id,
            title=str(identity["称号"]),
            stance=str(identity["立场"]),
            description=str(definition["说明"]),
            interactive=bool(identity["可交互"]),
            weapon=str(definition["本命武器"]["名称"]),
            techniques=tuple(str(value["功法"]) for value in definition["功法"]),
            minimum_level=int(minimum_level),
            maximum_level=int(maximum_level),
        )


def _apply_variation(
    rng: random.Random,
    attributes: dict[str, float],
    definition: dict[str, Any],
) -> None:
    minimum, maximum = (int(value) for value in definition["倍率"])
    for key in definition["属性"]:
        name = str(key)
        attributes[name] = round(attributes[name] * rng.randint(minimum, maximum) / 100, 4)


def _roll_inventory(
    rng: random.Random,
    definition: dict[str, Any],
) -> tuple[int, dict[str, int]]:
    items: Counter[str] = Counter()
    for carried in definition["物品"]:
        if rng.random() <= float(carried["概率"]):
            items[str(carried["物品"])] += _roll_range(rng, carried["数量"])
    return _roll_range(rng, definition["灵石"]), dict(items)


def _roll_range(rng: random.Random, value: list[int]) -> int:
    return rng.randint(int(value[0]), int(value[1]))


__all__ = ["CultivatorInstance", "NpcFeature", "NpcProfile"]
