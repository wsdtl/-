"""由宗门 JSON 驱动的灵藏与万珍殿共享账本。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from game.core.asset import AssetService, AssetStateError, InventoryAdjustment
from game.core.character import (
    CharacterCultivationError,
    CharacterService,
    CharacterStateError,
)
from game.core.data import JsonDataError, JsonDataService
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    SharedConstraintError,
    SharedEntityMutation,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)
from game.core.sect import SectService

from .contracts import (
    SectAssetConflictError,
    SectAssetEntry,
    SectAssetError,
    SectAssetStatus,
    SectAssetTransfer,
    SectAssetVault,
    SectMaterialCost,
    SectProductGain,
    SectProductionAssetPlan,
    SectResourceGainPlan,
)

LINGCANG_TYPE = "宗门灵藏"
WANZHEN_TYPE = "宗门万珍殿"


class SectAssetService:
    """保存宗门公共资源，不拥有成员关系或个人资产。"""

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        sect: SectService,
        asset: AssetService,
        character: CharacterService,
    ) -> None:
        self._data = data
        self._database = database
        self._sect = sect
        self._asset = asset
        self._character = character
        self._initialized = False
        self._materials: tuple[str, ...] = ()
        self._products: tuple[str, ...] = ()

    def initialize(self) -> SectAssetStatus:
        if self._initialized:
            raise RuntimeError("宗门公共资产核心已经初始化")
        rules = self._data.dataset("宗门规则")
        lingcang = _mapping(rules.get("灵藏"), "宗门/灵藏.json")
        wanzhen = _mapping(rules.get("万珍殿"), "宗门/万珍殿.json")
        self._materials = _texts(
            _mapping(lingcang.get("基础材料"), "灵藏.基础材料").get("类别"),
            "灵藏.基础材料.类别",
        )
        self._products = _texts(wanzhen.get("成品类别"), "万珍殿.成品类别")
        if self._materials != ("灵植", "灵矿", "兽宝"):
            raise JsonDataError("灵藏基础材料必须是灵植、灵矿和兽宝")
        if self._products != ("丹药", "真意", "气机", "器律", "阵法"):
            raise JsonDataError("万珍殿成品类别与正式资产分类不一致")
        self._initialized = True
        return self.status()

    def status(self) -> SectAssetStatus:
        return SectAssetStatus(self._initialized, self._materials, self._products)

    async def lingcang(self, user_id: str) -> SectAssetVault:
        member = await self._member(user_id)
        return await self._vault(LINGCANG_TYPE, member.sect_id, "灵藏")

    async def wanzhen(self, user_id: str) -> SectAssetVault:
        member = await self._member(user_id)
        return await self._vault(WANZHEN_TYPE, member.sect_id, "万珍殿")

    async def donate_material(
        self,
        user_id: str,
        request_id: str,
        category: str,
        content_id: str,
        grade_id: str,
        quantity: int,
    ) -> SectAssetTransfer:
        member = await self._member(user_id)
        normalized_category = _required_category(category, self._materials)
        normalized_quantity = _positive_int(quantity, "捐献数量")
        record = self._data.entity_record("物品", content_id)
        if record.number_category != normalized_category:
            raise SectAssetError("该物品不属于指定基础材料类别")
        grade = self._asset.grade(grade_id)
        try:
            personal = await self._asset.plan_inventory_changes(
                user_id,
                (
                    InventoryAdjustment(
                        content_id, grade.grade_id, -normalized_quantity
                    ),
                ),
            )
        except AssetStateError as exc:
            raise SectAssetError(str(exc)) from exc
        mutation, entry = await self._change_entry(
            LINGCANG_TYPE,
            member.sect_id,
            "灵藏",
            category=normalized_category,
            content_id=content_id,
            grade_id=grade.grade_id,
            quantity_delta=normalized_quantity,
        )
        receipt = await self._commit(
            user_id,
            request_id,
            "捐入灵藏",
            personal.operations + (mutation,),
            {
                "宗门编号": member.sect_id,
                "条目": entry.entry_key,
                "数量": normalized_quantity,
            },
        )
        return SectAssetTransfer("灵藏", "捐入", entry, 0, receipt.replayed)

    async def donate_stones(
        self, user_id: str, request_id: str, quantity: int
    ) -> SectAssetTransfer:
        member = await self._member(user_id)
        normalized = _positive_int(quantity, "灵石数量")
        try:
            personal = await self._character.plan_spirit_stone_change(
                user_id, delta=-normalized
            )
        except (CharacterCultivationError, CharacterStateError) as exc:
            raise SectAssetError(str(exc)) from exc
        mutation, after = await self._change_stones(member.sect_id, normalized)
        receipt = await self._commit(
            user_id,
            request_id,
            "捐入灵藏灵石",
            (personal.operation, mutation),
            {"宗门编号": member.sect_id, "灵石": normalized},
        )
        return SectAssetTransfer("灵藏", "捐入", None, after, receipt.replayed)

    async def donate_product(
        self,
        user_id: str,
        request_id: str,
        category: str,
        content_id: str,
        grade_or_key: str = "",
        quantity: int = 1,
    ) -> SectAssetTransfer:
        member = await self._member(user_id)
        normalized_category = _required_category(category, self._products)
        normalized_quantity = _positive_int(quantity, "捐献数量")
        try:
            (
                operation,
                actual_id,
                grade_id,
                materials,
                instance_key,
            ) = await self._product_take(
                user_id,
                normalized_category,
                content_id,
                grade_or_key,
                normalized_quantity,
            )
        except (AssetStateError, CharacterCultivationError, CharacterStateError) as exc:
            raise SectAssetError(str(exc)) from exc
        mutation, entry = await self._change_entry(
            WANZHEN_TYPE,
            member.sect_id,
            "万珍殿",
            category=normalized_category,
            content_id=actual_id,
            grade_id=grade_id,
            quantity_delta=normalized_quantity,
            materials=materials,
            instance_key=instance_key,
        )
        receipt = await self._commit(
            user_id,
            request_id,
            "捐入万珍殿",
            (operation, mutation),
            {
                "宗门编号": member.sect_id,
                "条目": entry.entry_key,
                "数量": normalized_quantity,
            },
        )
        return SectAssetTransfer("万珍殿", "捐入", entry, 0, receipt.replayed)

    async def grant_product(
        self,
        user_id: str,
        request_id: str,
        target_user_id: str,
        entry_key: str,
        quantity: int = 1,
    ) -> SectAssetTransfer:
        actor = await self._member(user_id)
        if not self._sect.is_officer(actor.role):
            raise SectAssetError("只有宗主或长老可以发放万珍殿物资")
        target = await self._member(target_user_id)
        if target.sect_id != actor.sect_id:
            raise SectAssetError("只能向本宗成员发放物资")
        normalized_quantity = _positive_int(quantity, "发放数量")
        record = await self._database.get_shared_entity(WANZHEN_TYPE, actor.sect_id)
        if record is None:
            raise SectAssetError("万珍殿中没有可发放物资")
        value = dict(_mapping(record.value, "万珍殿"))
        entries = dict(_mapping(value.get("条目", {}), "万珍殿.条目"))
        raw = entries.get(entry_key)
        if not isinstance(raw, Mapping):
            raise SectAssetError("万珍殿中没有该条目")
        entry = self._entry(entry_key, raw)
        if entry.quantity < normalized_quantity:
            raise SectAssetError("万珍殿中的数量不足")
        if entry.grade_id == "05" and normalized_quantity != 1:
            raise SectAssetError("圣品阵法必须按独立实例发放")
        try:
            personal = await self._product_give(
                target_user_id, entry, normalized_quantity
            )
        except (AssetStateError, CharacterCultivationError, CharacterStateError) as exc:
            raise SectAssetError(str(exc)) from exc
        after = entry.quantity - normalized_quantity
        if after:
            updated = dict(raw)
            updated["数量"] = after
            entries[entry_key] = updated
        else:
            entries.pop(entry_key)
        value["条目"] = entries
        mutation = SharedEntityMutation(
            WANZHEN_TYPE, actor.sect_id, value, record.version
        )
        receipt = await self._commit(
            user_id,
            request_id,
            "发放万珍殿",
            (mutation, personal),
            {
                "宗门编号": actor.sect_id,
                "目标": target_user_id,
                "条目": entry_key,
                "数量": normalized_quantity,
            },
        )
        return SectAssetTransfer("万珍殿", "发放", entry, 0, receipt.replayed)

    async def plan_production(
        self,
        sect_id: str,
        spirit_stones: int,
        *,
        materials: tuple[SectMaterialCost, ...] = (),
        product: SectProductGain | None = None,
    ) -> SectProductionAssetPlan:
        """规划一次宗门生产的公共资产变化，由调用方与个人资产一起提交。"""

        self._require_initialized()
        normalized_sect_id = str(sect_id or "").strip()
        if not normalized_sect_id:
            raise SectAssetError("宗门编号不能为空")
        cost = _positive_int(spirit_stones, "宗门灵石消耗")
        record = await self._database.get_shared_entity(LINGCANG_TYPE, normalized_sect_id)
        value = (
            dict(record.value)
            if record is not None
            else {"名称": f"灵藏-{normalized_sect_id}", "宗门编号": normalized_sect_id, "灵石": 0, "条目": {}}
        )
        before_stones = int(value.get("灵石") or 0)
        if before_stones < cost:
            raise SectAssetError(f"宗门灵石不足：现有{before_stones}，需要{cost}")
        entries = dict(_mapping(value.get("条目", {}), "灵藏.条目"))
        totals: dict[tuple[str, str, str], int] = {}
        for material in materials:
            if material.category not in self._materials:
                raise SectAssetError("宗门炼制使用了非基础材料")
            quantity = _positive_int(material.quantity, "宗门材料数量")
            key = (material.category, material.content_id, material.grade_id)
            totals[key] = totals.get(key, 0) + quantity
        for (category, content_id, grade_id), quantity in totals.items():
            entry_key = f"{category}:{content_id}:{grade_id}"
            raw = entries.get(entry_key)
            if not isinstance(raw, Mapping):
                raise SectAssetError("灵藏中缺少炼制材料")
            current = self._entry(entry_key, raw)
            if current.quantity < quantity:
                raise SectAssetError(
                    f"灵藏中的{current.grade_name}{current.name}不足：现有{current.quantity}，需要{quantity}"
                )
            after = current.quantity - quantity
            if after:
                updated = dict(raw)
                updated["数量"] = after
                entries[entry_key] = updated
            else:
                entries.pop(entry_key)
        value["灵石"] = before_stones - cost
        value["条目"] = entries
        operations: list[SharedEntityMutation] = [
            SharedEntityMutation(
                LINGCANG_TYPE,
                normalized_sect_id,
                value,
                record.version if record is not None else 0,
            )
        ]
        product_entry = None
        if product is not None:
            if product.category not in self._products:
                raise SectAssetError("宗门炼制产出了万珍殿不支持的类别")
            mutation, product_entry = await self._change_entry(
                WANZHEN_TYPE,
                normalized_sect_id,
                "万珍殿",
                category=product.category,
                content_id=product.content_id,
                grade_id=product.grade_id,
                quantity_delta=_positive_int(product.quantity, "宗门产出数量"),
                materials=product.materials,
                instance_key=product.instance_key,
            )
            operations.append(mutation)
        return SectProductionAssetPlan(
            tuple(operations),
            before_stones,
            before_stones - cost,
            product_entry,
        )

    async def plan_resource_gain(
        self,
        sect_id: str,
        spirit_stones: int,
        materials: tuple[SectMaterialCost, ...] = (),
    ) -> SectResourceGainPlan:
        """规划灵脉、灵田等宗门资源设施的公共资源增量。"""

        self._require_initialized()
        normalized_sect_id = str(sect_id or "").strip()
        if not normalized_sect_id:
            raise SectAssetError("宗门编号不能为空")
        if isinstance(spirit_stones, bool) or not isinstance(spirit_stones, int) or spirit_stones < 0:
            raise SectAssetError("灵石增量必须是非负整数")
        record = await self._database.get_shared_entity(LINGCANG_TYPE, normalized_sect_id)
        value = (
            dict(record.value)
            if record is not None
            else {
                "名称": f"灵藏-{normalized_sect_id}",
                "宗门编号": normalized_sect_id,
                "灵石": 0,
                "条目": {},
            }
        )
        before_stones = int(value.get("灵石") or 0)
        entries = dict(_mapping(value.get("条目", {}), "灵藏.条目"))
        totals: dict[tuple[str, str, str], int] = {}
        for material in materials:
            if material.category not in self._materials:
                raise SectAssetError("资源生产使用了未登记的基础材料类别")
            if (
                isinstance(material.quantity, bool)
                or not isinstance(material.quantity, int)
                or material.quantity < 1
            ):
                raise SectAssetError("资源生产数量必须是正整数")
            self._asset.grade(material.grade_id)
            key = (material.category, material.content_id, material.grade_id)
            totals[key] = totals.get(key, 0) + material.quantity
        generated_entries: list[SectAssetEntry] = []
        for (category, content_id, grade_id), quantity in sorted(totals.items()):
            entry_key = f"{category}:{content_id}:{grade_id}"
            raw = entries.get(entry_key)
            before = int(raw.get("数量") or 0) if isinstance(raw, Mapping) else 0
            after = before + quantity
            entry_value = {
                "类别": category,
                "编号": content_id,
                "名称": _entity_name(self._data, category, content_id),
                "品级": grade_id,
                "数量": after,
                "实际投入": dict(raw.get("实际投入", {})) if isinstance(raw, Mapping) else {},
            }
            entries[entry_key] = entry_value
            grade = self._asset.grade(grade_id)
            generated_entries.append(
                SectAssetEntry(
                    entry_key,
                    category,
                    content_id,
                    str(entry_value["名称"]),
                    grade_id,
                    grade.name,
                    quantity,
                )
            )
        value["灵石"] = before_stones + spirit_stones
        value["条目"] = entries
        mutation = SharedEntityMutation(
            LINGCANG_TYPE,
            normalized_sect_id,
            value,
            record.version if record is not None else 0,
        )
        return SectResourceGainPlan(
            (mutation,),
            before_stones,
            before_stones + spirit_stones,
            tuple(generated_entries),
        )

    async def has_assets(self, sect_id: str) -> bool:
        for entity_type in (LINGCANG_TYPE, WANZHEN_TYPE):
            record = await self._database.get_shared_entity(entity_type, sect_id)
            if record is None:
                continue
            value = _mapping(record.value, entity_type)
            if int(value.get("灵石") or 0) > 0 or bool(value.get("条目")):
                return True
        return False

    async def _product_take(
        self,
        user_id: str,
        category: str,
        content_id: str,
        grade_or_key: str,
        quantity: int,
    ) -> tuple[StateMutation, str, str, tuple[tuple[str, int], ...], str]:
        if category == "丹药":
            record = self._data.entity_record("物品", content_id)
            if record.number_category != "丹药":
                raise SectAssetError("该物品不是丹药")
            grade = self._asset.grade(grade_or_key)
            plan = await self._asset.plan_inventory_changes(
                user_id, (InventoryAdjustment(content_id, grade.grade_id, -quantity),)
            )
            return plan.operations[0], content_id, grade.grade_id, (), ""
        if category in {"真意", "气机"}:
            grade = self._asset.grade(grade_or_key)
            plan = await self._asset.plan_cultivation_reserve_change(
                user_id,
                category=category,
                content_id=content_id,
                grade_id=grade.grade_id,
                quantity_delta=-quantity,
            )
            return plan.operation, content_id, grade.grade_id, (), ""
        if category == "器律":
            stack = await self._asset.law_reserve_stack(user_id, content_id)
            if stack.quantity < quantity:
                raise SectAssetError("器藏中的器律数量不足")
            after = stack.quantity - quantity
            return (
                StateMutation(
                    user_id,
                    "law_reserve",
                    stack.law_id,
                    {"编号": stack.law_id, "数量": after} if after else None,
                    stack.version,
                ),
                stack.law_id,
                "",
                (),
                "",
            )
        if category == "阵法":
            if quantity != 1:
                raise SectAssetError("阵法每次只能捐入一座")
            stack = await self._asset.formation_reserve_stack(user_id, grade_or_key)
            if content_id and stack.formation_id != content_id:
                raise SectAssetError("阵藏条目与指定阵法不一致")
            plan = await self._asset.plan_formation_reserve_consumption(
                user_id, stack.state_key
            )
            materials = tuple((key, int(value)) for key, value in stack.materials)
            return (
                plan.operation,
                stack.formation_id,
                stack.grade_id,
                materials,
                stack.state_key if stack.grade_id == "05" else "",
            )
        raise SectAssetError("万珍殿不支持该成品类别")

    async def _product_give(
        self, user_id: str, entry: SectAssetEntry, quantity: int
    ) -> StateMutation:
        if entry.category == "丹药":
            plan = await self._asset.plan_inventory_changes(
                user_id,
                (InventoryAdjustment(entry.content_id, entry.grade_id, quantity),),
            )
            return plan.operations[0]
        if entry.category in {"真意", "气机"}:
            plan = await self._asset.plan_cultivation_reserve_change(
                user_id,
                category=entry.category,
                content_id=entry.content_id,
                grade_id=entry.grade_id,
                quantity_delta=quantity,
            )
            return plan.operation
        if entry.category == "器律":
            plan = await self._asset.plan_law_reserve_acquisition(
                user_id, entry.content_id, quantity
            )
            return plan.operation
        if entry.category == "阵法":
            if quantity != 1:
                raise SectAssetError("阵法每次只能发放一座")
            plan = await self._asset.plan_formation_reserve_acquisition(
                user_id,
                entry.content_id,
                entry.grade_id,
                materials={key: str(value) for key, value in entry.materials}
                if entry.grade_id == "05"
                else None,
            )
            return plan.operation
        raise SectAssetError("万珍殿条目类别无效")

    async def _change_entry(
        self,
        entity_type: str,
        sect_id: str,
        name: str,
        *,
        category: str,
        content_id: str,
        grade_id: str,
        quantity_delta: int,
        materials: tuple[tuple[str, int], ...] = (),
        instance_key: str = "",
    ) -> tuple[SharedEntityMutation, SectAssetEntry]:
        record = await self._database.get_shared_entity(entity_type, sect_id)
        value = (
            dict(record.value)
            if record is not None
            else {
                "名称": f"{name}-{sect_id}",
                "宗门编号": sect_id,
                "灵石": 0,
                "条目": {},
            }
        )
        entries = dict(_mapping(value.get("条目", {}), f"{name}.条目"))
        grade = self._asset.grade(grade_id) if grade_id else None
        sacred = category == "阵法" and grade_id == "05"
        if sacred and not str(instance_key or "").strip():
            raise SectAssetError("圣品阵法产出必须具有独立实例编号")
        key = (
            f"{category}:{content_id}:{grade_id}:{instance_key}"
            if sacred
            else f"{category}:{content_id}:{grade_id or '-'}"
        )
        before_raw = entries.get(key)
        before = (
            int(before_raw.get("数量") or 0) if isinstance(before_raw, Mapping) else 0
        )
        after = before + quantity_delta
        entry_value = {
            "类别": category,
            "编号": content_id,
            "名称": _entity_name(self._data, category, content_id),
            "品级": grade_id,
            "数量": after,
            "实际投入": dict(materials),
        }
        entries[key] = entry_value
        value["条目"] = entries
        entry = SectAssetEntry(
            key,
            category,
            content_id,
            str(entry_value["名称"]),
            grade_id,
            grade.name if grade is not None else "",
            after,
            materials,
        )
        return (
            SharedEntityMutation(
                entity_type, sect_id, value, record.version if record is not None else 0
            ),
            entry,
        )

    async def _change_stones(
        self, sect_id: str, delta: int
    ) -> tuple[SharedEntityMutation, int]:
        record = await self._database.get_shared_entity(LINGCANG_TYPE, sect_id)
        value = (
            dict(record.value)
            if record is not None
            else {"名称": f"灵藏-{sect_id}", "宗门编号": sect_id, "灵石": 0, "条目": {}}
        )
        after = int(value.get("灵石") or 0) + delta
        value["灵石"] = after
        return (
            SharedEntityMutation(
                LINGCANG_TYPE,
                sect_id,
                value,
                record.version if record is not None else 0,
            ),
            after,
        )

    async def _vault(self, entity_type: str, sect_id: str, name: str) -> SectAssetVault:
        record = await self._database.get_shared_entity(entity_type, sect_id)
        if record is None:
            return SectAssetVault(sect_id, name, 0, ())
        value = _mapping(record.value, name)
        entries = _mapping(value.get("条目", {}), f"{name}.条目")
        return SectAssetVault(
            sect_id,
            name,
            int(value.get("灵石") or 0),
            tuple(
                sorted(
                    (self._entry(key, raw) for key, raw in entries.items()),
                    key=lambda item: (
                        item.category,
                        item.grade_id,
                        item.content_id,
                        item.entry_key,
                    ),
                )
            ),
        )

    def _entry(self, key: str, raw: object) -> SectAssetEntry:
        value = _mapping(raw, f"宗门资产.{key}")
        grade_id = str(value.get("品级") or "")
        grade_name = self._asset.grade(grade_id).name if grade_id else ""
        materials = tuple(
            (name, int(amount))
            for name, amount in _mapping(value.get("实际投入", {}), "实际投入").items()
        )
        return SectAssetEntry(
            key,
            str(value.get("类别") or ""),
            str(value.get("编号") or ""),
            str(value.get("名称") or ""),
            grade_id,
            grade_name,
            int(value.get("数量") or 0),
            materials,
        )

    async def _member(self, user_id: str):
        self._require_initialized()
        member = await self._sect.membership(user_id)
        if member is None:
            raise SectAssetError("尚未加入宗门")
        return member

    async def _commit(self, user_id, request_id, business_type, operations, payload):
        try:
            return await self._database.commit(
                TransactionCommand(
                    user_id, request_id, business_type, tuple(operations), payload
                )
            )
        except IdempotencyConflictError as exc:
            raise SectAssetConflictError("请求编号已经用于其他操作") from exc
        except (StateConflictError, SharedConstraintError) as exc:
            raise SectAssetConflictError("宗门或个人资产刚刚发生变化，请重试") from exc
        except (AssetStateError, CharacterCultivationError, CharacterStateError) as exc:
            raise SectAssetError(str(exc)) from exc

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("宗门公共资产核心尚未初始化")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _texts(value: object, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise JsonDataError(f"{label}必须是非空字符串数组")
    return tuple(value)


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SectAssetError(f"{label}必须是正整数")
    return value


def _required_category(value: str, allowed: tuple[str, ...]) -> str:
    normalized = str(value or "").strip()
    if normalized not in allowed:
        raise SectAssetError(f"不支持的类别：{normalized or '<空>'}")
    return normalized


def _entity_name(data: JsonDataService, category: str, content_id: str) -> str:
    section = "物品" if category in {"丹药", "灵植", "灵矿", "兽宝"} else category
    value = data.entity(section, content_id)
    name = str(value.get("名称") or "").strip()
    if not name:
        raise SectAssetError(f"{category}缺少名称：{content_id}")
    return name


__all__ = ["LINGCANG_TYPE", "WANZHEN_TYPE", "SectAssetService"]
