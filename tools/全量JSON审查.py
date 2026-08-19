"""对正式 JSON 做全域、可重复、不中途停止的维护审查。"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.data import JsonDataService, materialize
from game.core.pool import PoolService
from tools.combat_support import isolated_combat_service

OBSOLETE_KEYS = frozenset(
    {
        "版本",
        "所属方向",
        "使用记录",
        "覆盖记录",
        "评分",
        "战斗策略",
        "体力上限",
        "蓄势",
        "构筑位",
    }
)
SLOT_KEYS = frozenset({"功法", "真意", "气机"})
GENDERS = frozenset({"男", "女"})
WEAPON_KEYS = frozenset({"名称", "等级", "经验", "器律"})
ENEMY_WEAPON_KEYS = frozenset({"名称", "攻击"})
SOUTHERN_REGIONS = frozenset(
    {"青岚州", "玄河州", "镜湖州", "丹霞州", "云京州", "天衡州"}
)
NORTHERN_REGIONS = frozenset({"朔风荒原", "寒渊林海", "烬脊群山", "天裂禁地"})
DEFENSE_REGION = "镇岳防线"


class DuplicateKeyError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class Finding:
    domain: str
    path: str
    message: str


class Audit:
    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.documents: dict[Path, Any] = {}
        self.data: JsonDataService | None = None

    def add(self, domain: str, path: str | Path, message: str) -> None:
        relative = _relative(path)
        finding = Finding(domain, relative, message)
        if finding not in self.findings:
            self.findings.append(finding)

    def run(self) -> None:
        self._parse_documents()
        if not self.documents:
            return
        self._initialize_services()
        self._audit_common_contracts()
        if self.data is None:
            return
        self._audit_numbered_entities()
        self._audit_definitions()
        self._audit_roles()
        self._audit_items()
        self._audit_alchemy()
        self._audit_forging()
        self._audit_build_content()
        self._audit_formations()
        self._audit_world()
        self._audit_presentations()

    def _parse_documents(self) -> None:
        for path in sorted(DATA.rglob("*.json")):
            try:
                value = json.loads(
                    path.read_text(encoding="utf-8"),
                    object_pairs_hook=_reject_duplicate_keys,
                )
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                DuplicateKeyError,
            ) as exc:
                self.add("解析", path, str(exc))
                continue
            self.documents[path.resolve()] = value

    def _initialize_services(self) -> None:
        try:
            data = JsonDataService(DATA)
            data.initialize()
            self.data = data
        except Exception as exc:  # noqa: BLE001 - 审查必须收集而不是中止
            self.add("读取服务", "data", f"JSON 数据微服务初始化失败：{exc}")
            return
        registered = {Path(value).as_posix() for value in data.document_paths()}
        actual = {path.relative_to(DATA).as_posix() for path in self.documents}
        for value in sorted(actual - registered):
            self.add("读取规则", DATA / value, "正式 JSON 未被读取规则登记")
        for value in sorted(registered - actual):
            self.add("读取规则", DATA / value, "读取规则登记了不存在的 JSON")
        try:
            PoolService(data).initialize()
        except Exception as exc:  # noqa: BLE001
            self.add("资源池", "data", f"资源池微服务初始化失败：{exc}")
        try:
            with isolated_combat_service(data):
                pass
        except Exception as exc:  # noqa: BLE001
            self.add("战斗", "data", f"战斗核心微服务初始化失败：{exc}")

    def _audit_common_contracts(self) -> None:
        content_names: dict[str, list[Path]] = defaultdict(list)
        for path, value in self.documents.items():
            relative = path.relative_to(DATA)
            if relative.parts[0] == "内容":
                content_names[path.stem.casefold()].append(path)
            self._walk_common(path, value, ())
            if isinstance(value, dict) and len(value) == 1:
                key = next(iter(value))
                if str(key).strip().casefold() == path.stem.casefold():
                    self.add("结构", path, "根节点重复包装了文件名表达的分类")
        for paths in content_names.values():
            if len(paths) > 1:
                joined = "、".join(_relative(path) for path in paths)
                self.add("文件身份", paths[0], f"内容文件名不唯一：{joined}")

    def _walk_common(self, path: Path, value: Any, trail: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = str(raw_key)
                current = (*trail, key)
                if key in OBSOLETE_KEYS:
                    self.add("旧字段", path, f"发现废弃字段：{'.'.join(current)}")
                if key in {"宝石", "附魔"}:
                    self.add(
                        "旧命名",
                        path,
                        f"发现已由气机/真意取代的字段：{'.'.join(current)}",
                    )
                self._walk_common(path, child, current)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._walk_common(path, child, (*trail, f"[{index}]"))
        elif isinstance(value, float) and _has_machine_float_tail(value):
            self.add(
                "数值",
                path,
                f"发现未经规整的浮点数：{'.'.join(trail)} = {value!r}",
            )

    def _audit_numbered_entities(self) -> None:
        assert self.data is not None
        seen_ids: dict[str, tuple[str, str]] = {}
        for section in (
            "机制",
            "战场环境",
            "功法",
            "真意",
            "气机",
            "物品",
            "丹方",
            "器律",
            "阵法",
            "境界",
            "道侣",
        ):
            names: dict[str, list[str]] = defaultdict(list)
            for identity, raw in self.data.entities(section).items():
                value = materialize(raw)
                path = self.data.entity_record(section, identity).source_file
                previous = seen_ids.get(identity)
                if previous is not None:
                    self.add(
                        "编号",
                        path,
                        f"六位编号跨类别重复：{identity} 同时属于 {previous[0]} 与 {section}",
                    )
                else:
                    seen_ids[identity] = (section, path)
                name = str(value.get("名称") or "").strip()
                if not name:
                    self.add("实体", path, f"{section} {identity} 缺少名称")
                else:
                    names[name].append(identity)
            for name, identities in names.items():
                if len(identities) > 1:
                    self.add(
                        "实体",
                        self.data.entity_record(section, identities[0]).source_file,
                        f"{section}名称重复：{name} -> {'、'.join(identities)}",
                    )

    def _audit_definitions(self) -> None:
        genders = self._json("定义/角色/性别.json")
        if genders != {"取值": ["男", "女"]}:
            self.add(
                "角色定义",
                "定义/角色/性别.json",
                "修士性别定义必须且只能按男、女有序登记",
            )
        attributes = self._json("定义/战斗/属性.json")
        if isinstance(attributes, dict):
            for name, definition in attributes.items():
                if not isinstance(definition, dict):
                    self.add(
                        "战斗定义", "定义/战斗/属性.json", f"属性定义必须是对象：{name}"
                    )
                    continue
                required = {
                    "默认值",
                    "最低值",
                    "最高值",
                    "最小单位",
                    "单位",
                    "显示",
                    "说明",
                }
                if set(definition) != required:
                    self.add(
                        "战斗定义", "定义/战斗/属性.json", f"属性字段不完整：{name}"
                    )
                    continue
                if (
                    not definition["最低值"]
                    <= definition["默认值"]
                    <= definition["最高值"]
                ):
                    self.add(
                        "战斗定义", "定义/战斗/属性.json", f"默认值超出范围：{name}"
                    )
        grades = self._json("定义/品级.json")
        if isinstance(grades, list):
            ids = [str(row.get("编号")) for row in grades if isinstance(row, dict)]
            if ids != ["01", "02", "03", "04", "05"]:
                self.add("品级", "定义/品级.json", "品级编号必须按 01..05 完整有序")

    def _audit_roles(self) -> None:
        assert self.data is not None
        role_rules = {
            name: self._json(f"规则/角色/主体/{name}.json")
            for name in ("人物", "道侣", "敌方修士", "灵兽")
        }
        expected_gender_sources = {
            "人物": "创建选择",
            "道侣": "实体",
            "敌方修士": "随机",
        }
        for name, source in expected_gender_sources.items():
            rule = role_rules[name]
            gender_rule = rule.get("性别") if isinstance(rule, dict) else None
            expected_gender_rule = {"来源": source, "定义": "性别"}
            if name == "敌方修士":
                expected_gender_rule["抽取"] = "等概率"
            if gender_rule != expected_gender_rule:
                self.add(
                    "角色",
                    f"规则/角色/主体/{name}.json",
                    f"{name}性别规则必须引用性别定义并使用来源：{source}",
                )
        companion_rule = role_rules["道侣"]
        if not isinstance(companion_rule, dict) or companion_rule.get("邀约") != {
            "好感要求": 100,
            "首次邀约性别关系": "不同",
            "再次邀约检查性别": False,
        }:
            self.add(
                "角色",
                "规则/角色/主体/道侣.json",
                "道侣首次邀约必须要求双方性别不同，再次邀约不得重复检查",
            )
        beast_rule = role_rules["灵兽"]
        if isinstance(beast_rule, dict) and "性别" in beast_rule:
            self.add("角色", "规则/角色/主体/灵兽.json", "灵兽不得套用修士性别规则")
        growth_files = {
            path.stem for path in (DATA / "规则" / "角色" / "成长").glob("*.json")
        }
        for name, rule in role_rules.items():
            if isinstance(rule, dict) and rule.get("成长规则") not in growth_files:
                self.add(
                    "角色",
                    f"规则/角色/主体/{name}.json",
                    f"成长规则不存在：{rule.get('成长规则')}",
                )
        for name in ("人物", "道侣"):
            rule = role_rules[name]
            if not isinstance(rule, dict) or set(rule.get("修行槽位", {})) != SLOT_KEYS:
                self.add(
                    "角色",
                    f"规则/角色/主体/{name}.json",
                    "修行槽位只能完整包含功法、真意、气机",
                )
            self._audit_role_weapon_pools(name, rule)
        for name in ("敌方修士", "灵兽"):
            rule = role_rules[name]
            if not isinstance(rule, dict):
                continue
            if name == "敌方修士":
                self._audit_role_weapon_pools(name, rule)
            elif "本命武器" in rule:
                self.add(
                    "角色",
                    f"规则/角色/主体/{name}.json",
                    "灵兽不得定义本命武器或器律池",
                )
            self._audit_role_tiers(name, rule)

        weapon_names: set[str] = set()
        companion_genders: Counter[str] = Counter()
        genders_by_file: dict[str, Counter[str]] = defaultdict(Counter)
        grade_ids = {
            str(value.get("编号"))
            for value in self._json("定义/品级.json")
            if isinstance(value, dict)
        }
        for identity, raw in self.data.entities("道侣").items():
            row = materialize(raw)
            path = self.data.entity_record("道侣", identity).source_file
            gender = row.get("性别")
            if gender not in GENDERS:
                self.add(
                    "道侣",
                    path,
                    f"{row.get('名称', identity)} 性别必须来自性别定义",
                )
            else:
                companion_genders[str(gender)] += 1
                genders_by_file[path][str(gender)] += 1
            for key in ("功法池", "真意池", "气机池"):
                if not isinstance(row.get(key), str) or not row[key].strip():
                    self.add("道侣", path, f"{row.get('名称', identity)} 缺少个人{key}")
            weapon = row.get("本命武器")
            if not isinstance(weapon, dict) or set(weapon) != WEAPON_KEYS:
                self.add(
                    "道侣",
                    path,
                    f"{row.get('名称', identity)} 本命武器必须显式保存名称、等级、经验、器律",
                )
                continue
            if weapon["等级"] != row.get("等级"):
                self.add(
                    "道侣",
                    path,
                    f"{row.get('名称', identity)} 初始武器等级与人物等级不一致",
                )
            if not isinstance(weapon["器律"], list):
                self.add(
                    "道侣",
                    path,
                    f"{row.get('名称', identity)} 本命武器器律必须是编号列表",
                )
            elif any(not _entity_id(value, "70") for value in weapon["器律"]):
                self.add(
                    "道侣",
                    path,
                    f"{row.get('名称', identity)} 本命武器器律包含非法编号",
                )
            weapon_name = str(weapon.get("名称") or "").strip()
            if not weapon_name:
                self.add("道侣", path, f"{row.get('名称', identity)} 本命武器名称为空")
            elif weapon_name in weapon_names:
                self.add("道侣", path, f"道侣本命武器名称重复：{weapon_name}")
            weapon_names.add(weapon_name)
            gift = row.get("结交", {}).get("圆满回礼")
            if not isinstance(gift, dict):
                self.add("道侣", path, f"{row.get('名称', identity)} 缺少圆满回礼")
            else:
                if gift.get("编号") not in self.data.entities("物品"):
                    self.add(
                        "道侣", path, f"{row.get('名称', identity)} 圆满回礼物品不存在"
                    )
                if gift.get("品级") not in grade_ids:
                    self.add(
                        "道侣", path, f"{row.get('名称', identity)} 圆满回礼品级不存在"
                    )
                if not _positive_int(gift.get("数量")):
                    self.add(
                        "道侣", path, f"{row.get('名称', identity)} 圆满回礼数量非法"
                    )

        if companion_genders != Counter({"男": 132, "女": 132}):
            self.add(
                "道侣",
                "内容/世界",
                f"道侣性别必须严格对半，当前男 {companion_genders['男']}、女 {companion_genders['女']}",
            )
        for path, counts in genders_by_file.items():
            if abs(counts["男"] - counts["女"]) > 1:
                self.add(
                    "道侣",
                    path,
                    f"单个地点的道侣性别数量相差超过一人：男 {counts['男']}、女 {counts['女']}",
                )

        for identity, raw in self.data.entities("敌人").items():
            row = materialize(raw)
            path = self.data.entity_record("敌人", identity).source_file
            kind = row.get("角色规则")
            if kind == "灵兽":
                if "性别" in row:
                    self.add("敌人", path, f"灵兽 {identity} 不得保存修士性别")
                if "本命武器" in row:
                    self.add("敌人", path, f"灵兽 {identity} 不得定义本命武器")
                growth = row.get("每级成长")
                if not isinstance(growth, dict) or set(growth) != {
                    "血气上限",
                    "精神上限",
                    "攻击",
                    "防御",
                }:
                    self.add("敌人", path, f"灵兽 {identity} 必须保存四项完整每级成长")
            elif kind == "敌方修士":
                if "性别" in row:
                    self.add(
                        "敌人",
                        path,
                        f"敌方修士 {identity} 的性别必须生成时随机，不得写死在敌人定义中",
                    )
                weapon = row.get("本命武器")
                if not isinstance(weapon, dict) or set(weapon) != ENEMY_WEAPON_KEYS:
                    self.add(
                        "敌人",
                        path,
                        f"敌方修士 {identity} 必须保存武器名称与一级基础攻击",
                    )
                if "每级成长" in row:
                    self.add("敌人", path, f"敌方修士 {identity} 不得复制共享修士成长")
            else:
                self.add("敌人", path, f"{identity} 引用了未知角色规则：{kind}")
            self._audit_enemy_common(identity, row, path)
        self._audit_role_initial_items(role_rules.get("人物"))

    def _audit_role_initial_items(self, rule: Any) -> None:
        if not isinstance(rule, dict):
            return
        grade_ids = {
            str(value.get("编号"))
            for value in self._json("定义/品级.json")
            if isinstance(value, dict)
        }
        for index, item in enumerate(rule.get("物品", [])):
            if not isinstance(item, dict) or not _entity_id(
                item.get("编号"), ("10", "12", "14", "16")
            ):
                self.add(
                    "角色",
                    "规则/角色/主体/人物.json",
                    f"初始物品[{index}] 必须引用丹药编号",
                )
            elif not _positive_int(item.get("数量")):
                self.add(
                    "角色",
                    "规则/角色/主体/人物.json",
                    f"初始物品[{index}] 数量必须为正整数",
                )
            elif item.get("品级") not in grade_ids:
                self.add(
                    "角色",
                    "规则/角色/主体/人物.json",
                    f"初始物品[{index}] 必须使用有效两位品级编号",
                )
            elif self.data is not None and item["编号"] not in self.data.entities(
                "物品"
            ):
                self.add(
                    "角色",
                    "规则/角色/主体/人物.json",
                    f"初始物品引用不存在：{item['编号']}",
                )

    def _audit_role_weapon_pools(self, name: str, rule: Any) -> None:
        if not isinstance(rule, dict):
            return
        weapon = rule.get("本命武器")
        if name in {"人物", "道侣"}:
            if not isinstance(weapon, dict) or weapon != {
                "器律来源": "玩家器藏",
                "装配方式": "手动覆炼",
            }:
                self.add(
                    "角色",
                    f"规则/角色/主体/{name}.json",
                    "人物与道侣本命武器必须从玩家器藏手动覆炼器律",
                )
            return
        pools = weapon.get("器律池") if isinstance(weapon, dict) else None
        expected = ["器律池-灵器", "器律池-法器", "器律池-法宝", "器律池-后天灵宝"]
        if pools != expected:
            self.add(
                "角色",
                f"规则/角色/主体/{name}.json",
                "本命武器必须按四个器阶显式引用器律池",
            )
        if name == "敌方修士" and (
            not isinstance(weapon, dict) or weapon.get("等级来源") != "实际等级"
        ):
            self.add(
                "角色",
                f"规则/角色/主体/{name}.json",
                "敌方修士必须明确以实际等级初始化本命武器等级",
            )

    def _audit_role_tiers(self, name: str, rule: dict[str, Any]) -> None:
        tiers = rule.get("阶梯")
        if not isinstance(tiers, list) or not tiers:
            self.add("角色", f"规则/角色/主体/{name}.json", "缺少阶梯字典列表")
            return
        expected_start = 1
        for index, tier in enumerate(tiers):
            path = f"规则/角色/主体/{name}.json"
            if not isinstance(tier, dict):
                self.add("角色", path, f"阶梯[{index}] 不是字典")
                continue
            levels = tier.get("等级范围")
            if not _ordered_pair(levels, minimum=1):
                self.add("角色", path, f"阶梯[{index}] 等级范围非法")
                continue
            if levels[0] != expected_start:
                self.add("角色", path, f"阶梯等级不连续：期望从 {expected_start} 开始")
            expected_start = levels[1] + 1
            slots = tier.get("修行槽位")
            if (
                not isinstance(slots, dict)
                or set(slots) != SLOT_KEYS
                or any(not _positive_int(value) for value in slots.values())
            ):
                self.add("角色", path, f"阶梯 {tier.get('阶梯', index)} 修行槽位非法")
            for pool_key in ("功法池", "真意池", "气机池"):
                if (
                    not isinstance(tier.get(pool_key), str)
                    or not tier[pool_key].strip()
                ):
                    self.add(
                        "角色", path, f"阶梯 {tier.get('阶梯', index)} 缺少{pool_key}"
                    )
        if expected_start != 101:
            self.add(
                "角色", f"规则/角色/主体/{name}.json", "阶梯必须连续覆盖 1..100 级"
            )

    def _audit_enemy_common(self, name: str, row: dict[str, Any], path: str) -> None:
        if not _ordered_pair(row.get("等级"), minimum=1, maximum=100):
            self.add("敌人", path, f"{name} 等级范围非法")
        fluctuation = row.get("实力波动")
        attribute_definitions = self._json("定义/战斗/属性.json")
        allowed_attributes = (
            set(attribute_definitions)
            if isinstance(attribute_definitions, dict)
            else set()
        )
        if not isinstance(fluctuation, dict):
            self.add("敌人", path, f"{name} 缺少实力波动")
        else:
            attributes = fluctuation.get("属性")
            if (
                not isinstance(attributes, list)
                or not attributes
                or not set(attributes) <= allowed_attributes
            ):
                self.add("敌人", path, f"{name} 实力波动属性非法")
            if not _ordered_pair(fluctuation.get("倍率"), minimum=1):
                self.add("敌人", path, f"{name} 实力波动倍率非法")
        if not _positive_int(row.get("权重")):
            self.add("敌人", path, f"{name} 权重必须是正整数")
        for field in ("灵石",):
            drop = row.get("掉落")
            if not isinstance(drop, dict) or not _ordered_pair(
                drop.get(field), minimum=0
            ):
                self.add("敌人", path, f"{name} 掉落.{field} 必须是非负整数范围")
        reward = row.get("交锋所得")
        for field in ("人物经验", "本命武器经验"):
            if not isinstance(reward, dict) or not _ordered_pair(
                reward.get(field), minimum=0
            ):
                self.add("敌人", path, f"{name} 交锋所得.{field} 必须是非负整数范围")

    def _audit_items(self) -> None:
        assert self.data is not None
        classes = self._json("规则/物品/分类.json")
        effects = self._json("定义/物品/使用效果.json")
        class_rules = (
            {
                str(row["类别"]): row
                for row in classes
                if isinstance(row, dict) and row.get("类别")
            }
            if isinstance(classes, list)
            else {}
        )
        effect_rules = (
            {
                str(row["类型"]): row
                for row in effects
                if isinstance(row, dict) and row.get("类型")
            }
            if isinstance(effects, list)
            else {}
        )
        gender_effect = effect_rules.get("转变性别")
        if gender_effect != {
            "类型": "转变性别",
            "执行器": "转变性别",
            "目标": "玩家自身",
            "必填字段": [],
        }:
            self.add(
                "物品效果",
                "定义/物品/使用效果.json",
                "转变性别必须只作用于玩家自身",
            )
        for identity, raw in self.data.entities("物品").items():
            row = materialize(raw)
            record = self.data.entity_record("物品", identity)
            path = record.source_file
            category = record.number_category
            rule = class_rules.get(category)
            if rule is None:
                self.add("物品", path, f"{identity} 使用未登记分类：{category}")
                continue
            common = {"编号", "名称", "说明", "权重", "参考价"}
            required = common | set(rule.get("必填字段", []))
            allowed = required | set(rule.get("可选字段", []))
            missing = required - set(row)
            extra = set(row) - allowed
            if missing:
                self.add(
                    "物品", path, f"{identity} 缺少字段：{'、'.join(sorted(missing))}"
                )
            if extra:
                self.add(
                    "物品",
                    path,
                    f"{identity} 存在分类未声明字段：{'、'.join(sorted(extra))}",
                )
            expected_order = ["编号", "名称", "说明"]
            if "强度" in row:
                expected_order.append("强度")
            expected_order.append("权重")
            if "使用效果" in row:
                expected_order.append("使用效果")
            expected_order.append("参考价")
            if list(row) != expected_order:
                self.add("物品", path, f"{identity} 字段顺序未按统一物品契约排列")
            if not _positive_int(row.get("权重")):
                self.add("物品", path, f"{identity} 权重必须是正整数")
            if not _positive_number(row.get("参考价")):
                self.add("物品", path, f"{identity} 参考价必须大于零")
            if category == "丹药":
                self._audit_item_effect(
                    identity, row.get("使用效果"), effect_rules, path
                )

    def _audit_item_effect(
        self,
        identity: str,
        effect: Any,
        rules: dict[str, dict[str, Any]],
        path: str,
    ) -> None:
        if not isinstance(effect, dict):
            self.add("物品效果", path, f"丹药 {identity} 使用效果必须是对象")
            return
        kind = str(effect.get("类型") or "")
        rule = rules.get(kind)
        if rule is None:
            self.add(
                "物品效果", path, f"丹药 {identity} 使用未知效果：{kind or '<空>'}"
            )
            return
        required = {"类型", *rule.get("必填字段", [])}
        allowed = required | set(rule.get("可选字段", []))
        missing = required - set(effect)
        extra = set(effect) - allowed
        if missing:
            self.add(
                "物品效果",
                path,
                f"丹药 {identity} 效果缺字段：{'、'.join(sorted(missing))}",
            )
        if extra:
            self.add(
                "物品效果",
                path,
                f"丹药 {identity} 效果有未登记字段：{'、'.join(sorted(extra))}",
            )
        for node in _walk_dicts(effect):
            mechanism = node.get("机制")
            if (
                isinstance(mechanism, str)
                and self.data is not None
                and mechanism not in self.data.entities("机制")
            ):
                self.add(
                    "物品效果",
                    path,
                    f"丹药 {identity} 引用不存在的战斗机制：{mechanism}",
                )
            for reference in node.get("战斗机制", ()):
                if self.data is not None and reference not in self.data.entities(
                    "机制"
                ):
                    self.add(
                        "物品效果",
                        path,
                        f"丹药 {identity} 引用不存在的战斗机制：{reference}",
                    )
        if kind in {"恢复血气", "恢复精神"}:
            value = effect.get("恢复百分比")
            if (
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or not 0 < value <= 100
            ):
                self.add(
                    "物品效果", path, f"丹药 {identity} 恢复百分比必须位于 (0, 100]"
                )
        if kind == "境界突破":
            permanent = effect.get("永久属性")
            if permanent is not None:
                allowed = set(self._json("定义/战斗/属性.json"))
                if not isinstance(permanent, dict) or not set(permanent) <= allowed:
                    self.add(
                        "物品效果", path, f"丹药 {identity} 永久属性包含未定义战斗属性"
                    )
                elif any(
                    not isinstance(value, int | float) or isinstance(value, bool)
                    for value in permanent.values()
                ):
                    self.add("物品效果", path, f"丹药 {identity} 永久属性必须是数值")

    def _audit_alchemy(self) -> None:
        assert self.data is not None
        recipes = self.data.entities("丹方")
        alchemy_rules = self._json("规则/炼药/丹则.json")
        lead_rule = (
            alchemy_rules.get("药引", {}) if isinstance(alchemy_rules, dict) else {}
        )
        if lead_rule.get("类别") != "兽宝" or not _positive_int(
            lead_rule.get("每炉数量")
        ):
            self.add("炼药", "规则/炼药/丹则.json", "药引必须定义为每炉正数件兽宝")
        try:
            beast_leads = self.data.number_category_members("兽宝")
        except Exception as exc:  # noqa: BLE001
            self.add("炼药", "内容/物品/兽宝", f"兽宝虚拟全池无效：{exc}")
            beast_leads = ()
        if not beast_leads:
            self.add("炼药", "内容/物品/兽宝", "兽宝虚拟全池不能为空")
        medicines = {
            identity: materialize(value)
            for identity, value in self.data.entities("物品").items()
            if identity[:2] in {"10", "12", "14", "16"}
        }
        furnace_rows = self._json("规则/炼药/炉法.json")
        difficulty_rows = self._json("规则/炼药/难度.json")
        furnaces = (
            {
                str(row.get("名称")): row
                for row in furnace_rows
                if isinstance(row, dict) and row.get("名称")
            }
            if isinstance(furnace_rows, list)
            else {}
        )
        herb_rows = self._json("规则/炼药/归脉.json")
        valid_medicine_veins = (
            {
                row.get(key)
                for row in herb_rows
                if isinstance(row, dict)
                for key in ("本脉", "旁脉")
                if row.get(key)
            }
            if isinstance(herb_rows, list)
            else set()
        )
        used_furnaces: set[str] = set()
        for name, furnace in furnaces.items():
            parts = furnace.get("辅材")
            if not isinstance(parts, list) or not parts:
                self.add("炼药", "规则/炼药/炉法.json", f"炉法 {name} 缺少辅材药脉")
                continue
            veins = [part.get("药脉") for part in parts if isinstance(part, dict)]
            if len(veins) != len(parts) or len(veins) != len(set(veins)):
                self.add(
                    "炼药", "规则/炼药/炉法.json", f"炉法 {name} 药脉必须完整且不重复"
                )
            if any(vein not in valid_medicine_veins for vein in veins):
                self.add("炼药", "规则/炼药/炉法.json", f"炉法 {name} 使用未登记药脉")
            if any(
                not isinstance(part, dict) or not _positive_int(part.get("味数"))
                for part in parts
            ):
                self.add("炼药", "规则/炼药/炉法.json", f"炉法 {name} 味数必须为正整数")
        difficulties = (
            {
                row.get("炼制难度"): row
                for row in difficulty_rows
                if isinstance(row, dict)
            }
            if isinstance(difficulty_rows, list)
            else {}
        )
        outputs: dict[str, list[str]] = defaultdict(list)
        for identity, raw in recipes.items():
            row = materialize(raw)
            path = self.data.entity_record("丹方", identity).source_file
            if "药引池" in row:
                self.add("炼药", path, f"丹方 {identity} 不应重复声明全兽宝药引池")
            output = str(row.get("成丹") or "")
            outputs[output].append(identity)
            medicine = medicines.get(output)
            if medicine is None:
                self.add(
                    "炼药", path, f"丹方 {identity} 成丹引用不存在：{output or '<空>'}"
                )
            elif row.get("名称") not in {
                f"{medicine.get('名称')}方",
                f"{medicine.get('名称')}丹方",
            }:
                self.add("炼药", path, f"丹方 {identity} 与成丹名称不一致")
            if row.get("强度") != (medicine or {}).get("强度"):
                self.add("炼药", path, f"丹方 {identity} 与成丹强度不一致")
            difficulty = difficulties.get(row.get("炼制难度"))
            if difficulty is None:
                self.add("炼药", path, f"丹方 {identity} 炼制难度未登记")
            furnace = furnaces.get(str(row.get("炉法") or ""))
            if furnace is None:
                self.add("炼药", path, f"丹方 {identity} 炉法未登记：{row.get('炉法')}")
            elif difficulty is not None:
                used_furnaces.add(str(row.get("炉法")))
                tastes = sum(
                    part.get("味数", 0)
                    for part in furnace.get("辅材", [])
                    if isinstance(part, dict)
                )
                limits = difficulty.get("辅材总味数", {})
                if (
                    not limits.get("最少", math.inf)
                    <= tastes
                    <= limits.get("最多", -math.inf)
                ):
                    self.add(
                        "炼药",
                        path,
                        f"丹方 {identity} 的炉法共 {tastes} 味，不符合难度 {row.get('炼制难度')} 的范围",
                    )
        unused_furnaces = set(furnaces) - used_furnaces
        if unused_furnaces:
            self.add(
                "炼药",
                "规则/炼药/炉法.json",
                f"存在没有丹方使用的炉法：{'、'.join(sorted(unused_furnaces))}",
            )
        for identity in medicines:
            count = len(outputs.get(identity, ()))
            if count != 1:
                path = self.data.entity_record("物品", identity).source_file
                self.add(
                    "炼药", path, f"丹药 {identity} 必须恰有一张丹方，当前 {count} 张"
                )
        self._audit_material_mapping(
            "炼药",
            "灵植-",
            "规则/炼药/归脉.json",
            "灵植池",
        )
        self._audit_realm_chain()

    def _audit_realm_chain(self) -> None:
        assert self.data is not None
        realms = {
            identity: materialize(value)
            for identity, value in self.data.entities("境界").items()
        }
        by_level = sorted(realms.values(), key=lambda value: value["等级下限"])
        expected_low = 1
        for index, realm in enumerate(by_level):
            path = self.data.entity_record("境界", realm["编号"]).source_file
            if (
                realm["等级下限"] != expected_low
                or realm["等级上限"] - realm["等级下限"] != 4
            ):
                self.add("境界", path, f"境界 {realm['编号']} 必须连续占用五级")
            expected_low = realm["等级上限"] + 1
            next_id = realm.get("下一境界")
            if index == len(by_level) - 1:
                if next_id is not None:
                    self.add("境界", path, "最终境界不应有下一境界")
            elif next_id != by_level[index + 1]["编号"]:
                self.add("境界", path, "下一境界未指向等级相邻的境界")
        if expected_low != 101:
            self.add("境界", "内容/角色/境界.json", "境界必须完整覆盖 1..100 级")
        targets: Counter[str] = Counter()
        for identity, raw in self.data.entities("物品").items():
            effect = materialize(raw).get("使用效果")
            if not isinstance(effect, dict) or effect.get("类型") != "境界突破":
                continue
            target = effect.get("目标境界")
            targets[target] += 1
            path = self.data.entity_record("物品", identity).source_file
            if target not in realms:
                self.add("突破丹", path, f"突破丹 {identity} 目标境界不存在：{target}")
            permanent = effect.get("永久属性")
            if permanent is not None and (
                not isinstance(permanent, dict) or not permanent
            ):
                self.add(
                    "突破丹",
                    path,
                    f"突破丹 {identity} 永久属性必须是非空属性字典",
                )
        expected_targets = set(realms) - {by_level[0]["编号"]}
        if set(targets) != expected_targets:
            self.add(
                "突破丹",
                "内容/物品/丹药/突破丹",
                "突破丹必须覆盖除初始境界外的全部境界节点",
            )

    def _audit_forging(self) -> None:
        assert self.data is not None
        vessel_rule = self._json("规则/炼器/器则.json")
        tiers = {
            row.get("名称"): row
            for row in vessel_rule.get("器阶", [])
            if isinstance(vessel_rule, dict) and isinstance(row, dict)
        }
        methods_rows = self._json("规则/炼器/铸法.json")
        methods = (
            {
                row.get("名称"): row
                for row in methods_rows
                if isinstance(row, dict) and row.get("名称")
            }
            if isinstance(methods_rows, list)
            else {}
        )
        ore_rows = self._json("规则/炼器/归脉.json")
        valid_casting_veins = (
            {
                row.get(key)
                for row in ore_rows
                if isinstance(row, dict)
                for key in ("本脉", "旁脉")
                if row.get(key)
            }
            if isinstance(ore_rows, list)
            else set()
        )
        beast_rows = self._json("规则/炼器/归引.json")
        valid_beast_veins = (
            {
                row.get("兽脉")
                for row in beast_rows
                if isinstance(row, dict) and row.get("兽脉")
            }
            if isinstance(beast_rows, list)
            else set()
        )
        laws_by_tier: dict[str, set[str]] = defaultdict(set)
        used_methods: set[str] = set()
        for name, method in methods.items():
            tier = tiers.get(method.get("器阶"))
            if tier is None:
                self.add("炼器", "规则/炼器/铸法.json", f"铸法 {name} 器阶未登记")
                continue
            parts = method.get("辅材")
            if not isinstance(parts, list) or not parts:
                self.add("炼器", "规则/炼器/铸法.json", f"铸法 {name} 缺少辅材铸脉")
                continue
            veins = [part.get("铸脉") for part in parts if isinstance(part, dict)]
            if len(veins) != len(parts) or len(veins) != len(set(veins)):
                self.add(
                    "炼器", "规则/炼器/铸法.json", f"铸法 {name} 铸脉必须完整且不重复"
                )
            if any(vein not in valid_casting_veins for vein in veins):
                self.add("炼器", "规则/炼器/铸法.json", f"铸法 {name} 使用未登记铸脉")
            if any(
                not isinstance(part, dict) or not _positive_int(part.get("份数"))
                for part in parts
            ):
                self.add("炼器", "规则/炼器/铸法.json", f"铸法 {name} 份数必须为正整数")
            total = sum(part.get("份数", 0) for part in parts if isinstance(part, dict))
            limits = tier.get("矿材份数")
            if (
                not _ordered_pair(limits, minimum=0)
                or not limits[0] <= total <= limits[1]
            ):
                self.add(
                    "炼器",
                    "规则/炼器/铸法.json",
                    f"铸法 {name} 共 {total} 份矿材，不符合 {method.get('器阶')} 的范围",
                )
        for identity, raw in self.data.entities("器律").items():
            row = materialize(raw)
            path = self.data.entity_record("器律", identity).source_file
            tier_name = row.get("器阶")
            tier = tiers.get(tier_name)
            if tier is None:
                self.add("炼器", path, f"器律 {identity} 器阶未登记：{tier_name}")
                continue
            laws_by_tier[str(tier_name)].add(identity)
            method = methods.get(row.get("铸法"))
            if method is None:
                self.add("炼器", path, f"器律 {identity} 铸法未登记：{row.get('铸法')}")
            elif method.get("器阶") != tier_name:
                self.add("炼器", path, f"器律 {identity} 的器阶与铸法器阶不一致")
            else:
                used_methods.add(str(row.get("铸法")))
            beast = row.get("兽引")
            if not isinstance(beast, list) or len(beast) != tier.get("兽引数量"):
                self.add("炼器", path, f"器律 {identity} 兽引数量与器阶不一致")
            elif any(value not in valid_beast_veins for value in beast):
                self.add("炼器", path, f"器律 {identity} 使用未登记兽脉")
            if not isinstance(row.get("能力"), list) or not row["能力"]:
                self.add("炼器", path, f"器律 {identity} 缺少战斗能力")
        unused_methods = set(methods) - used_methods
        if unused_methods:
            self.add(
                "炼器",
                "规则/炼器/铸法.json",
                f"存在没有器律使用的铸法：{'、'.join(sorted(unused_methods))}",
            )
        for tier in ("灵器", "法器", "法宝", "后天灵宝"):
            file_id = f"器律池-{tier}"
            try:
                members = set(self.data.pool_members((file_id,), "器律"))
            except Exception as exc:  # noqa: BLE001
                self.add("炼器", f"内容/炼器/池/{file_id}.json", str(exc))
                continue
            if members != laws_by_tier[tier]:
                missing = sorted(laws_by_tier[tier] - members)
                extra = sorted(members - laws_by_tier[tier])
                self.add(
                    "炼器",
                    f"内容/炼器/池/{file_id}.json",
                    f"器阶池覆盖错误，缺少={missing}，多出={extra}",
                )
        self._audit_material_mapping("炼器", "灵矿-", "规则/炼器/归脉.json", "灵矿池")
        self._audit_material_mapping("炼器", "兽宝-", "规则/炼器/归引.json", "兽宝池")

    def _audit_material_mapping(
        self, domain: str, prefix: str, rule_path: str, key: str
    ) -> None:
        rows = self._json(rule_path)
        mapped = (
            [row.get(key) for row in rows if isinstance(row, dict)]
            if isinstance(rows, list)
            else []
        )
        duplicates = [
            name for name, count in Counter(mapped).items() if name and count > 1
        ]
        for name in duplicates:
            self.add(domain, rule_path, f"材料池映射重复：{name}")
        sources = {path.stem for path in (DATA / "内容").rglob(f"{prefix}*.json")}
        mapped_set = {str(value) for value in mapped if value}
        for name in sorted(sources - mapped_set):
            self.add(domain, rule_path, f"材料池没有归类：{name}")
        for name in sorted(mapped_set - sources):
            self.add(domain, rule_path, f"归类引用不存在的材料池：{name}")

    def _audit_build_content(self) -> None:
        assert self.data is not None
        mechanisms = set(self.data.entities("机制"))
        ability_names = self._defined_ability_names()
        weights: dict[int, str] = {}
        for identity, raw in self.data.entities("机制").items():
            path = self.data.entity_record("机制", identity).source_file
            value = materialize(raw)
            self._audit_ability_tree(
                "机制",
                identity,
                [value.get("节点")],
                path,
                mechanisms,
                ability_names,
            )
        for section in ("功法", "真意", "气机", "器律"):
            for identity, raw in self.data.entities(section).items():
                path = self.data.entity_record(section, identity).source_file
                value = materialize(raw)
                if section != "器律":
                    weight = value.get("权重")
                    name = str(value.get("名称") or "")
                    if not _positive_int(weight):
                        self.add(
                            "全池权重", path, f"{section} {identity} 权重必须是正整数"
                        )
                    else:
                        previous = weights.get(weight)
                        if previous is not None and previous != name:
                            self.add(
                                "全池权重",
                                path,
                                f"异名修行实体权重重复：{previous}、{name} -> {weight}",
                            )
                        else:
                            weights[weight] = name
                self._audit_ability_tree(
                    section,
                    identity,
                    value.get("能力"),
                    path,
                    mechanisms,
                    ability_names,
                )
        for identity, raw in self.data.entities("战场环境").items():
            path = self.data.entity_record("战场环境", identity).source_file
            value = materialize(raw)
            stages = value.get("阶段")
            if not isinstance(stages, list) or not stages:
                self.add("战场环境", path, f"环境 {identity} 至少需要一个承伤阶段")
                continue
            if value.get("名称") != "无相境" and len(stages) < 2:
                self.add("战场环境", path, f"环境 {identity} 至少需要两个承伤阶段")
                continue
            thresholds = [
                stage.get("起始承伤比例") for stage in stages if isinstance(stage, dict)
            ]
            if thresholds != sorted(thresholds) or not math.isclose(thresholds[0], 0.0):
                self.add("战场环境", path, f"环境 {identity} 阶段阈值必须从 0 严格递增")
            if len(set(thresholds)) != len(thresholds) or any(
                value < 0 for value in thresholds
            ):
                self.add("战场环境", path, f"环境 {identity} 阶段阈值必须非负且不重复")
            for stage in stages:
                if not isinstance(stage, dict):
                    continue
                for field in ("入阶能力", "常驻能力"):
                    self._audit_ability_tree(
                        "战场环境",
                        identity,
                        stage.get(field),
                        path,
                        mechanisms,
                        ability_names,
                        allow_empty=True,
                    )

    def _audit_ability_tree(
        self,
        section: str,
        identity: str,
        value: Any,
        path: str,
        mechanisms: set[str],
        ability_names: set[str],
        *,
        allow_empty: bool = False,
    ) -> None:
        if not isinstance(value, list):
            self.add(section, path, f"{identity} 能力根节点必须是非空列表")
            return
        if not value and not allow_empty:
            self.add(section, path, f"{identity} 能力列表不能为空")
        for node in _walk_dicts(value):
            ability = node.get("能力")
            if ability is not None and ability_names and ability not in ability_names:
                self.add(section, path, f"{identity} 使用未登记原子能力：{ability}")
            for key in ("机制",):
                reference = node.get(key)
                if (
                    isinstance(reference, str)
                    and _entity_id(reference, "60")
                    and reference not in mechanisms
                ):
                    self.add(
                        section, path, f"{identity} 引用不存在的战斗机制：{reference}"
                    )
            references = node.get("战斗机制")
            if isinstance(references, list):
                for reference in references:
                    if reference not in mechanisms:
                        self.add(
                            section,
                            path,
                            f"{identity} 引用不存在的战斗机制：{reference}",
                        )

    def _defined_ability_names(self) -> set[str]:
        value = self._json("定义/战斗/原子能力.json")
        result: set[str] = set()
        for node in _walk_dicts(value):
            name = node.get("名称")
            if isinstance(name, str):
                result.add(name)
        return result

    def _audit_formations(self) -> None:
        assert self.data is not None
        expected_grades = ["黄", "玄", "地", "天", "圣"]
        for identity, raw in self.data.entities("阵法").items():
            row = materialize(raw)
            path = self.data.entity_record("阵法", identity).source_file
            grades = row.get("品级")
            if (
                not isinstance(grades, list)
                or [value.get("品级") for value in grades if isinstance(value, dict)]
                != expected_grades
            ):
                self.add("阵法", path, f"阵法 {identity} 必须完整按黄玄地天圣五品定义")
                continue
            for grade in grades:
                name = grade["品级"]
                material_key = "最低消耗" if name == "圣" else "消耗"
                materials = grade.get(material_key)
                if not isinstance(materials, dict) or set(materials) != {
                    "兽宝",
                    "灵矿",
                    "灵植",
                }:
                    self.add(
                        "阵法", path, f"阵法 {identity}/{name} 必须只按三类材料定义消耗"
                    )
                elif any(not _positive_int(value) for value in materials.values()):
                    self.add(
                        "阵法", path, f"阵法 {identity}/{name} 材料消耗必须是正整数"
                    )
                stages = grade.get("地势阶段")
                if not isinstance(stages, list) or [
                    value.get("阶段") for value in stages
                ] != [1, 2, 3, 4]:
                    self.add(
                        "阵法", path, f"阵法 {identity}/{name} 必须完整定义四段地势响应"
                    )

    def _audit_world(self) -> None:
        assert self.data is not None
        terrains = {
            materialize(value).get("名称")
            for value in self.data.entities("战场环境").values()
        }
        locations = {
            identity: materialize(value)
            for identity, value in self.data.entities("地点").items()
        }
        regions = {
            identity: materialize(value)
            for identity, value in self.data.entities("区域").items()
        }
        _, terrain_by_point = self._audit_terrain_domains(terrains)
        region_domains = {
            name: _coordinate_domain_points(row.get("坐标带"))
            for name, row in regions.items()
        }
        terrain_table = self._json("内容/世界/地势.json")
        self._audit_height_table(terrain_table)
        coordinates: dict[tuple[int, int], str] = {}
        for name, row in locations.items():
            path = self.data.entity_record("地点", name).source_file
            coordinate = row.get("坐标")
            if not _coordinate(coordinate):
                self.add("世界", path, f"地点 {name} 坐标必须是 0..99 的二维整数")
                continue
            point = (coordinate[0], coordinate[1])
            previous = coordinates.get(point)
            if previous is not None:
                self.add("世界", path, f"地点坐标重复：{name} 与 {previous} -> {point}")
            else:
                coordinates[point] = name
            record = self.data.entity_record("地点", name)
            owner = record.directory_owner
            region = regions.get(owner or "")
            if region is None:
                self.add("世界", path, f"地点 {name} 无法从目录确定区域")
            else:
                if point not in region_domains.get(owner or "", set()):
                    self.add("世界", path, f"地点 {name} 坐标不在所属区域 {owner} 内")
                if point not in terrain_by_point:
                    self.add("世界", path, f"地点 {name} 没有命中地形分区")
            self._audit_location_functions(name, row, path)
        trading_shops = {
            f"{name}商店"
            for name, row in locations.items()
            if "交易" in row.get("可用功能", [])
        }
        for file_id in sorted(set(self.data.entities("地点商店")) - trading_shops):
            path = self.data.entity_record("地点商店", file_id).source_file
            self.add("世界", path, f"地点商店没有对应的交易地点：{file_id}")
        for name, row in regions.items():
            path = self.data.entity_record("区域", name).source_file
            if set(row) != {"类别", "坐标带", "说明"}:
                self.add("世界", path, f"区域 {name} 只能保存类别、坐标带和说明")
            points = region_domains.get(name)
            if not points:
                self.add("世界", path, f"区域 {name} 坐标带非法或为空")
            elif not _connected_points(points):
                self.add("世界", path, f"区域 {name} 坐标域不连通")
        self._audit_world_partition(region_domains)
        self._audit_world_definitions(terrains)
        self._audit_world_role_distribution(locations, terrain_by_point)
        self._audit_roads(locations)

    def _audit_height_table(self, value: Any) -> None:
        path = "内容/世界/地势.json"
        if not isinstance(value, dict):
            self.add("地势", path, "地势必须是对象")
            return
        table = value.get("地表高度")
        if not isinstance(table, list) or len(table) != 100:
            self.add("地势", path, "地表高度必须恰有 100 行")
            return
        for index, row in enumerate(table):
            if not isinstance(row, list) or len(row) != 100:
                self.add("地势", path, f"地表高度第 {index} 行必须恰有 100 项")
            elif any(
                isinstance(item, bool) or not isinstance(item, int) for item in row
            ):
                self.add("地势", path, f"地表高度第 {index} 行只能保存整数米")

    def _audit_location_functions(
        self, name: str, row: dict[str, Any], path: str
    ) -> None:
        functions = row.get("可用功能")
        if not isinstance(functions, list) or len(functions) != len(set(functions)):
            self.add("世界", path, f"地点 {name} 可用功能必须是无重复列表")
            functions = []
        definitions = self._json("定义/世界/地点功能.json")
        function_rules = (
            {
                value.get("名称"): value
                for value in definitions
                if isinstance(value, dict) and value.get("名称")
            }
            if isinstance(definitions, list)
            else {}
        )
        for function in functions:
            definition = function_rules.get(function)
            if definition is None:
                self.add("世界", path, f"地点 {name} 使用未登记功能：{function}")
                continue
            requirement = definition.get("要求", {})
            for field in requirement.get("非空字段", []):
                if not row.get(field):
                    self.add(
                        "世界",
                        path,
                        f"地点 {name} 的 {function} 功能缺少非空字段：{field}",
                    )
            for field in requirement.get("正数范围字段", []):
                if not _ordered_pair(row.get(field), minimum=1):
                    self.add(
                        "世界",
                        path,
                        f"地点 {name} 的 {function} 功能缺少正数范围：{field}",
                    )
            for section in definition.get("同目录内容", []):
                file_id = f"{name}{section}"
                try:
                    if section == "商店":
                        self.data.entity("地点商店", file_id)
                        owner = self.data.entity_record(
                            "地点商店", file_id
                        ).directory_owner
                        if owner != name:
                            raise ValueError(f"归属目录为 {owner or '<空>'}")
                    else:
                        self.data.pool_members((file_id,), section)
                except Exception as exc:  # noqa: BLE001
                    self.add(
                        "世界",
                        path,
                        f"地点 {name} 的 {function} 功能缺少同目录{section}内容：{exc}",
                    )
        has_exploration = "探险" in functions
        for legacy_field in ("灵植池", "灵矿池", "道侣池", "敌人池"):
            if legacy_field in row:
                self.add(
                    "世界", path, f"地点 {name} 不应保存可派生字段：{legacy_field}"
                )
        if has_exploration:
            if not _ordered_pair(row.get("单次遭遇敌人倍率"), minimum=1):
                self.add("世界", path, f"地点 {name} 单次遭遇敌人倍率非法")
        elif row.get("单次遭遇敌人倍率"):
            self.add("世界", path, f"地点 {name} 不提供探险却保存了探险数据")

    def _audit_terrain_domains(
        self, terrains: set[Any]
    ) -> tuple[dict[str, set[tuple[int, int]]], dict[tuple[int, int], str]]:
        rows = self._json("内容/世界/地形分区.json")
        domains: dict[str, set[tuple[int, int]]] = {}
        owners: dict[tuple[int, int], str] = {}
        if not isinstance(rows, list):
            self.add("世界", "内容/世界/地形分区.json", "地形分区必须是字典列表")
            return domains, owners
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or set(row) != {"名称", "地形", "坐标带"}:
                self.add(
                    "世界", "内容/世界/地形分区.json", f"地形分区[{index}]结构非法"
                )
                continue
            name = row.get("名称")
            terrain = row.get("地形")
            if not isinstance(name, str) or not name or name in domains:
                self.add(
                    "世界",
                    "内容/世界/地形分区.json",
                    f"地形分区[{index}]名称为空或重复",
                )
                continue
            if terrain not in terrains:
                self.add(
                    "世界",
                    "内容/世界/地形分区.json",
                    f"地形分区 {name} 引用不存在的战场环境：{terrain}",
                )
            points = _coordinate_domain_points(row.get("坐标带"))
            domains[name] = points
            if not points:
                self.add(
                    "世界",
                    "内容/世界/地形分区.json",
                    f"地形分区 {name} 坐标带非法或为空",
                )
            elif not _connected_points(points):
                self.add(
                    "世界", "内容/世界/地形分区.json", f"地形分区 {name} 坐标域不连通"
                )
            for point in points:
                previous = owners.get(point)
                if previous is not None:
                    self.add(
                        "世界",
                        "内容/世界/地形分区.json",
                        f"地形分区重叠：{point} -> {previous}、{name}",
                    )
                else:
                    owners[point] = str(terrain or "")
        if len(owners) != 10000:
            self.add(
                "世界",
                "内容/世界/地形分区.json",
                f"地形分区必须覆盖100x100全境，当前{len(owners)}格",
            )
        return domains, owners

    def _audit_world_partition(self, regions: dict[str, set[tuple[int, int]]]) -> None:
        owners: dict[tuple[int, int], str] = {}
        overlaps: set[tuple[int, int]] = set()
        for name, points in regions.items():
            for point in points:
                if point in owners:
                    overlaps.add(point)
                else:
                    owners[point] = name
        if overlaps:
            self.add("世界", "内容/世界", f"区域边界重叠 {len(overlaps)} 格")
        if len(owners) != 10000:
            self.add(
                "世界",
                "内容/世界",
                f"区域边界必须覆盖 100x100 全境，当前 {len(owners)} 格",
            )

    def _audit_world_definitions(self, environment_names: set[Any]) -> None:
        terrain_names = {str(value) for value in environment_names if value != "无相境"}
        passage = self._json("规则/行路/地形通行.json")
        passage_names = (
            {
                str(value.get("地形"))
                for value in passage
                if isinstance(value, dict) and value.get("地形")
            }
            if isinstance(passage, list)
            else set()
        )
        if passage_names != terrain_names:
            self.add(
                "行路",
                "规则/行路/地形通行.json",
                f"地形通行必须覆盖全部地表环境，缺少={sorted(terrain_names - passage_names)}，多出={sorted(passage_names - terrain_names)}",
            )
        for prefix, directory in (("灵植-", "灵植"), ("灵矿-", "灵矿")):
            pools = {
                path.stem
                for path in (DATA / "内容" / "物品" / directory).glob(f"{prefix}*.json")
            }
            expected = {f"{prefix}{name}" for name in terrain_names}
            if pools != expected:
                self.add(
                    "世界",
                    f"内容/物品/{directory}",
                    f"{directory}地形池必须逐地形覆盖，缺少={sorted(expected - pools)}，多出={sorted(pools - expected)}",
                )
        world = self._json("内容/世界/晓楠修仙界.json")
        road_names = set(world.get("道路", ())) if isinstance(world, dict) else set()
        road_dataset = set(self._dataset("道路"))
        road_rules = self._json("规则/行路/道路通行.json")
        road_rule_names = (
            {
                str(value.get("道路"))
                for value in road_rules
                if isinstance(value, dict) and value.get("道路")
            }
            if isinstance(road_rules, list)
            else set()
        )
        if road_names != road_dataset or road_names != road_rule_names:
            self.add(
                "行路",
                "内容/世界/晓楠修仙界.json",
                "世界道路类别、道路文件和道路通行规则必须完全一致",
            )

    def _audit_world_role_distribution(
        self,
        locations: dict[str, dict[str, Any]],
        terrain_by_point: dict[tuple[int, int], str],
    ) -> None:
        assert self.data is not None
        defense_kinds: set[str] = set()
        for name, row in locations.items():
            record = self.data.entity_record("地点", name)
            region = record.directory_owner or ""
            kinds: set[str] = set()
            enemy_ids: set[str] = set()
            pools = (f"{name}敌人",) if "探险" in row.get("可用功能", ()) else ()
            for pool in pools:
                try:
                    for identity in self.data.pool_members((pool,), "敌人"):
                        enemy_ids.add(identity)
                        kinds.add(
                            materialize(self.data.entity("敌人", identity)).get(
                                "角色规则"
                            )
                        )
                except Exception as exc:  # noqa: BLE001
                    self.add(
                        "世界", record.source_file, f"地点 {name} 敌人池无法展开：{exc}"
                    )
            if region in SOUTHERN_REGIONS and kinds - {"灵兽"}:
                self.add("世界", record.source_file, f"南方地点 {name} 混入敌方修士")
            if region in NORTHERN_REGIONS and kinds - {"敌方修士"}:
                self.add("世界", record.source_file, f"北方地点 {name} 混入灵兽")
            if region == DEFENSE_REGION:
                defense_kinds.update(kinds)
            terrain = terrain_by_point.get(tuple(row.get("坐标", ())), "")
            self._audit_location_drops(
                name,
                terrain,
                record.source_file,
                enemy_ids,
            )
        if defense_kinds != {"灵兽", "敌方修士"}:
            self.add(
                "世界",
                "内容/世界/镇岳防线",
                "镇岳防线总敌人池必须同时包含灵兽与敌方修士",
            )

    def _audit_location_drops(
        self,
        location_name: str,
        terrain: str,
        path: str,
        enemy_ids: set[str],
    ) -> None:
        assert self.data is not None
        for derived_pool in (f"灵植-{terrain}", f"灵矿-{terrain}"):
            try:
                self.data.pool_members((derived_pool,), "物品")
            except Exception as exc:  # noqa: BLE001
                self.add("世界", path, f"地点 {location_name} 的地形池无效：{exc}")
        for identity in enemy_ids:
            enemy = materialize(self.data.entity("敌人", identity))
            drops = enemy.get("掉落", {})
            if "物品池" in drops:
                self.add("世界", path, f"敌人 {identity} 不应保存旧物品池字段")
            extra_pools = set(drops.get("额外物品池", ()))
            derived_prefixes = ("灵植-", "灵矿-", "兽宝-")
            if any(str(value).startswith(derived_prefixes) for value in extra_pools):
                self.add("世界", path, f"敌人 {identity} 的额外物品池混入可派生池")
            for pool in extra_pools:
                try:
                    self.data.pool_members((str(pool),), "物品")
                except Exception as exc:  # noqa: BLE001
                    self.add("世界", path, f"敌人 {identity} 额外物品池无效：{exc}")
            if enemy.get("角色规则") == "灵兽":
                unique_pool = f"兽宝-{identity}"
                try:
                    members = self.data.pool_members((unique_pool,), "物品")
                except Exception as exc:  # noqa: BLE001
                    self.add("世界", path, f"灵兽 {identity} 独有兽宝池无效：{exc}")
                else:
                    if len(members) < 3:
                        self.add(
                            "世界",
                            path,
                            f"灵兽 {identity} 独有兽宝池至少需要三件兽宝",
                        )

    def _audit_roads(self, locations: dict[str, dict[str, Any]]) -> None:
        roads = self._dataset("道路")
        graph: dict[str, set[str]] = defaultdict(set)
        covered: set[str] = set()
        direct_pairs: set[frozenset[str]] = set()
        for path, rows in roads.items():
            if not isinstance(rows, list):
                continue
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    self.add("道路", path, f"道路[{index}] 不是字典")
                    continue
                start = row.get("起点")
                end = row.get("终点")
                if start not in locations or end not in locations:
                    self.add("道路", path, f"道路端点不存在：{start} -> {end}")
                    continue
                direct_pair = frozenset((start, end))
                if direct_pair in direct_pairs:
                    self.add("道路", path, f"道路端点重复：{start} <-> {end}")
                direct_pairs.add(direct_pair)
                coordinates = row.get("途经坐标")
                if (
                    not isinstance(coordinates, list)
                    or len(coordinates) < 2
                    or any(not _coordinate(value) for value in coordinates)
                ):
                    self.add("道路", path, f"道路 {start}->{end} 坐标链非法")
                    continue
                if (
                    coordinates[0] != locations[start]["坐标"]
                    or coordinates[-1] != locations[end]["坐标"]
                ):
                    self.add(
                        "道路", path, f"道路 {start}->{end} 坐标链端点与地点不一致"
                    )
                for left, right in pairwise(coordinates):
                    dx = abs(left[0] - right[0])
                    dy = abs(left[1] - right[1])
                    if max(dx, dy) != 1:
                        self.add(
                            "道路",
                            path,
                            f"道路 {start}->{end} 存在不连续坐标：{left}->{right}",
                        )
                        break
                graph[start].add(end)
                graph[end].add(start)
                covered.update((start, end))
        missing = set(locations) - covered
        if missing:
            self.add(
                "道路",
                "内容/世界/道路",
                f"未接入道路的地点：{'、'.join(sorted(missing))}",
            )
        world = self._json("内容/世界/晓楠修仙界.json")
        start = world.get("出生地") if isinstance(world, dict) else None
        reached: set[str] = set()
        queue = deque([start]) if start in locations else deque()
        while queue:
            current = queue.popleft()
            if current in reached:
                continue
            reached.add(current)
            queue.extend(graph[current] - reached)
        if reached != set(locations):
            self.add(
                "道路",
                "内容/世界/道路",
                f"道路网络未从出生地连通全部地点，缺少 {len(set(locations) - reached)} 个",
            )

    def _audit_presentations(self) -> None:
        for name, relative_path in (
            ("战报", "展示/战斗/战报.json"),
            ("行程", "展示/行路/行程.json"),
        ):
            value = self._json(relative_path)
            if not isinstance(value, dict) or not value:
                self.add("展示", relative_path, f"{name}展示定义必须是非空对象")

    def _json(self, relative: str) -> Any:
        path = (DATA / relative).resolve()
        value = self.documents.get(path)
        if value is None:
            self.add("文件", DATA / relative, "必需 JSON 不存在或未能解析")
        return value

    def _dataset(self, name: str) -> dict[str, Any]:
        if self.data is None:
            return {}
        try:
            return materialize(self.data.dataset(name))
        except Exception as exc:  # noqa: BLE001
            self.add("数据集", "data", f"数据集 {name} 无法读取：{exc}")
            return {}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"JSON 对象存在重复键：{key}")
        result[key] = value
    return result


def _relative(path: str | Path) -> str:
    raw = Path(path)
    try:
        return raw.resolve().relative_to(ROOT).as_posix()
    except (OSError, ValueError):
        return raw.as_posix()


def _entity_id(
    value: Any,
    prefix: str | tuple[str, ...] | None = None,
) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 6
        and value.isdigit()
        and (prefix is None or value.startswith(prefix))
    )


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value > 0


def _has_machine_float_tail(value: float) -> bool:
    for digits in range(7):
        rounded = round(value, digits)
        if rounded != value and math.isclose(
            value,
            rounded,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            return True
    return False


def _ordered_pair(value: Any, *, minimum: int, maximum: int | None = None) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
        and minimum <= value[0] <= value[1]
        and (maximum is None or value[1] <= maximum)
    )


def _coordinate(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(
            isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= 99
            for item in value
        )
    )


def _coordinate_domain_points(value: Any) -> set[tuple[int, int]]:
    if not isinstance(value, list) or not value:
        return set()
    result: set[tuple[int, int]] = set()
    seen_y: set[int] = set()
    for band in value:
        if not isinstance(band, dict) or set(band) != {"y", "x轴"}:
            return set()
        y = band.get("y")
        ranges = band.get("x轴")
        if (
            isinstance(y, bool)
            or not isinstance(y, int)
            or not 0 <= y <= 99
            or y in seen_y
            or not isinstance(ranges, list)
            or not ranges
        ):
            return set()
        seen_y.add(y)
        previous_end = -1
        for x_range in ranges:
            if (
                not _ordered_pair(x_range, minimum=0, maximum=99)
                or x_range[0] <= previous_end
            ):
                return set()
            result.update((x, y) for x in range(x_range[0], x_range[1] + 1))
            previous_end = x_range[1]
    return result


def _connected_points(points: set[tuple[int, int]]) -> bool:
    if not points:
        return False
    reached: set[tuple[int, int]] = set()
    queue = deque([next(iter(points))])
    while queue:
        point = queue.popleft()
        if point in reached:
            continue
        reached.add(point)
        x, y = point
        queue.extend(
            neighbor
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            if neighbor in points and neighbor not in reached
        )
    return reached == points


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def main() -> int:
    audit = Audit()
    audit.run()
    findings = sorted(audit.findings)
    counts = Counter(value.domain for value in findings)
    print(f"全量 JSON 审查完成：{len(audit.documents)} 个文件，{len(findings)} 个问题")
    for domain, count in sorted(counts.items()):
        print(f"- {domain}: {count}")
    for finding in findings:
        print(f"[{finding.domain}] {finding.path}: {finding.message}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
