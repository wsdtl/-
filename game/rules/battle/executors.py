"""战斗 JSON 可以绑定的最小执行语义。

这里登记的是 Python 真正能够执行的底层动作，不登记任何功法、机制或
玩家可见能力名。同一个执行器可以被多个 JSON 能力复用。
"""

from __future__ import annotations

from types import MappingProxyType


EXECUTOR_CATEGORIES = MappingProxyType(
    {
        "装配属性": frozenset({"装配"}),
        "装配主动技能": frozenset({"装配"}),
        "装配被动技能": frozenset({"装配"}),
        "引用机制": frozenset({"引用"}),
        "顺序执行": frozenset({"组合"}),
        "条件执行": frozenset({"组合"}),
        "监听事件": frozenset({"触发"}),
        "读取数值": frozenset({"数值"}),
        "选择目标": frozenset({"目标"}),
        "选择技能": frozenset({"目标"}),
        "概率条件": frozenset({"条件"}),
        "标签条件": frozenset({"条件"}),
        "造成伤害": frozenset({"效果"}),
        "恢复资源": frozenset({"效果"}),
        "添加状态": frozenset({"效果"}),
        "修改技能冷却": frozenset({"效果"}),
        "抵挡致命伤害": frozenset({"效果"}),
    }
)


__all__ = ["EXECUTOR_CATEGORIES"]
