"""查看角色流程编排。"""

from __future__ import annotations

from game.core.character import (
    CharacterNotFoundError,
    CharacterService,
    CharacterStateError,
)
from game.core.player_state import PlayerStateService
from game.core.world import LocationQuery, WorldService

from .contracts import (
    CharacterOverviewError,
    CharacterOverviewMissingError,
    CharacterOverviewResult,
)


class CharacterOverviewFeature:
    """组合角色资产、位置与当前玩家状态。"""

    def __init__(
        self,
        character: CharacterService,
        player_state: PlayerStateService,
        world: WorldService,
    ) -> None:
        self._character = character
        self._player_state = player_state
        self._world = world
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("查看角色玩法微服务已经初始化")
        if not self._character.status().initialized:
            raise RuntimeError("角色核心微服务必须先于查看角色玩法启动")
        if not self._player_state.status().initialized:
            raise RuntimeError("玩家状态微服务必须先于查看角色玩法启动")
        if not self._world.status().initialized:
            raise RuntimeError("世界地点微服务必须先于查看角色玩法启动")
        self._initialized = True

    async def inspect(self, user_id: str) -> CharacterOverviewResult:
        if not self._initialized:
            raise RuntimeError("查看角色玩法微服务尚未初始化")
        try:
            character = await self._character.profile(user_id)
        except CharacterNotFoundError as exc:
            raise CharacterOverviewMissingError(str(exc)) from exc
        except CharacterStateError as exc:
            raise CharacterOverviewError(str(exc)) from exc
        state = await self._player_state.current(user_id)
        if state is None:
            raise CharacterOverviewError("人物缺少玩家状态")
        location = self._world.locate(LocationQuery(xy=character.xy))
        return CharacterOverviewResult(
            character=character,
            location_name=location.location_name,
            region=location.region,
            terrain=location.terrain,
            altitude=location.altitude,
            states=tuple(
                (state_type, slot.name)
                for state_type, slot in state.states.items()
            ),
        )


__all__ = ["CharacterOverviewFeature"]
