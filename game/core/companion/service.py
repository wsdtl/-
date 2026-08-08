"""解释世界道侣身份与地点归属的静态核心服务。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService

from .contracts import CompanionStatus, LocalCultivator


class CompanionService:
    """提供本地修士基础摘要，不创建玩家个人道侣实例。"""

    def __init__(self, data: JsonDataService) -> None:
        self._data = data
        self._initialized = False
        self._by_location: Mapping[str, tuple[LocalCultivator, ...]] = MappingProxyType(
            {}
        )

    def initialize(self) -> CompanionStatus:
        if self._initialized:
            raise RuntimeError("世界道侣核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于世界道侣服务启动")
        realms = tuple(
            (
                realm_id,
                _text(value.get("名称"), f"境界 {realm_id}.名称"),
                _positive_int(value.get("等级下限"), f"境界 {realm_id}.等级下限"),
                _positive_int(value.get("等级上限"), f"境界 {realm_id}.等级上限"),
            )
            for realm_id, value in self._data.entities("境界").items()
        )
        by_location: dict[str, list[LocalCultivator]] = {}
        for companion_id, value in self._data.entities("道侣").items():
            record = self._data.entity_record("道侣", companion_id)
            location_name = _text(
                record.directory_owner, f"道侣 {companion_id}.归属地点"
            )
            level = _positive_int(value.get("等级"), f"道侣 {companion_id}.等级")
            realm_matches = tuple(
                (realm_id, realm_name)
                for realm_id, realm_name, minimum, maximum in realms
                if minimum <= level <= maximum
            )
            if len(realm_matches) != 1:
                raise JsonDataError(
                    f"道侣 {companion_id} 的等级 {level} 无法唯一归属境界"
                )
            identity = _mapping(value.get("身份"), f"道侣 {companion_id}.身份")
            realm_id, realm_name = realm_matches[0]
            by_location.setdefault(location_name, []).append(
                LocalCultivator(
                    companion_id=companion_id,
                    name=_text(value.get("名称"), f"道侣 {companion_id}.名称"),
                    gender=_text(value.get("性别"), f"道侣 {companion_id}.性别"),
                    title=_text(identity.get("称号"), f"道侣 {companion_id}.身份.称号"),
                    description=_text(value.get("说明"), f"道侣 {companion_id}.说明"),
                    realm_id=realm_id,
                    realm_name=realm_name,
                    level=level,
                    interactable=_bool(
                        identity.get("可交互"), f"道侣 {companion_id}.身份.可交互"
                    ),
                )
            )
        self._by_location = MappingProxyType(
            {
                location: tuple(
                    sorted(values, key=lambda item: (item.name, item.companion_id))
                )
                for location, values in by_location.items()
            }
        )
        self._initialized = True
        return self.status()

    def status(self) -> CompanionStatus:
        return CompanionStatus(
            initialized=self._initialized,
            companion_count=sum(len(values) for values in self._by_location.values()),
            location_count=len(self._by_location),
        )

    def local_cultivators(self, location_name: str) -> tuple[LocalCultivator, ...]:
        if not self._initialized:
            raise RuntimeError("世界道侣核心微服务尚未初始化")
        normalized = str(location_name or "").strip()
        if not normalized:
            return ()
        return self._by_location.get(normalized, ())


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JsonDataError(f"{label}必须是非空字符串")
    return value.strip()


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JsonDataError(f"{label}必须是正整数")
    return value


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise JsonDataError(f"{label}必须是布尔值")
    return value


__all__ = ["CompanionService"]
