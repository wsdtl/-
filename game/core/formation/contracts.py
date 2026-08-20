"""阵法炼制、待战和战斗快照的稳定公共契约。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.database import StateMutation


class FormationError(ValueError):
    """阵法规则或请求无法完成。"""


class FormationUnavailableError(FormationError):
    """当前位置没有阵师或未开放指定阵法。"""


class FormationMaterialError(FormationError):
    """三相材料不足。"""


class FormationConflictError(FormationError):
    """阵法提交时相关状态已经变化。"""


@dataclass(frozen=True)
class FormationStatus:
    initialized: bool
    formation_count: int
    master_count: int
    fixed_grade_count: int
    unlimited_grade: str


@dataclass(frozen=True)
class FormationMaster:
    master_id: str
    name: str
    location_name: str
    title: str
    platform_name: str
    heritage: str
    speech_style: str
    formation_ids: tuple[str, ...]


@dataclass(frozen=True)
class FormationDefinition:
    formation_id: str
    name: str
    monitors: tuple[str, ...]
    core: str


@dataclass(frozen=True)
class FormationMaterial:
    category: str
    item_id: str
    name: str
    grade_id: str
    grade_name: str
    quantity: int


@dataclass(frozen=True)
class FormationRequirement:
    category: str
    required: int
    selected: int

    @property
    def missing(self) -> int:
        return max(0, self.required - self.selected)


@dataclass(frozen=True)
class FormationAssessment:
    formation: FormationDefinition
    grade_id: str
    grade_name: str
    materials: tuple[FormationMaterial, ...]
    requirements: tuple[FormationRequirement, ...]
    capacity: float
    impact: float
    nodes: int
    transmission: float
    can_form: bool


@dataclass(frozen=True)
class FormationPreview:
    user_id: str
    location_name: str
    master: FormationMaster
    formation: FormationDefinition
    grade_id: str
    grade_name: str
    request_text: str
    materials: tuple[FormationMaterial, ...]
    requirements: tuple[FormationRequirement, ...]
    capacity: float
    impact: float
    nodes: int
    transmission: float
    can_form: bool


@dataclass(frozen=True)
class FormationEntry:
    formation: FormationDefinition


@dataclass(frozen=True)
class FormationOverview:
    user_id: str
    location_name: str
    master: FormationMaster
    entries: tuple[FormationEntry, ...]
    page: int
    page_count: int


@dataclass(frozen=True)
class FormationResult:
    preview: FormationPreview
    reserve_key: str
    quantity_before: int
    quantity_after: int
    replayed: bool


@dataclass(frozen=True)
class FormationPrepared:
    user_id: str
    reserve_key: str
    formation_id: str
    name: str
    grade_id: str
    grade_name: str
    materials: tuple[tuple[str, str], ...]
    version: int


@dataclass(frozen=True)
class FormationArmResult:
    prepared: FormationPrepared
    replayed: bool


@dataclass(frozen=True)
class FormationStageProfile:
    threshold_multiplier: float
    cycle_multiplier: float
    impact_multiplier: float


@dataclass(frozen=True)
class FormationNodeRules:
    enemy_formation_first: bool
    target_count_field: str
    target_sort: tuple[str, ...]
    impact_distribution: str
    unique_targets: bool
    minimum_targets: int


@dataclass(frozen=True)
class FormationBattleProfile:
    formation_id: str
    name: str
    grade_name: str
    position: int
    capacity: float
    impact: float
    nodes: int
    transmission: float
    stages: tuple[FormationStageProfile, ...]


@dataclass(frozen=True)
class FormationActivationPlan:
    prepared: FormationPrepared
    profile: FormationBattleProfile
    operation: StateMutation


__all__ = [
    "FormationActivationPlan",
    "FormationArmResult",
    "FormationAssessment",
    "FormationBattleProfile",
    "FormationConflictError",
    "FormationDefinition",
    "FormationEntry",
    "FormationError",
    "FormationMaster",
    "FormationMaterial",
    "FormationMaterialError",
    "FormationNodeRules",
    "FormationOverview",
    "FormationPrepared",
    "FormationPreview",
    "FormationRequirement",
    "FormationResult",
    "FormationStageProfile",
    "FormationStatus",
    "FormationUnavailableError",
]
