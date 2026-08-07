"""查看类命令入口。"""

from __future__ import annotations

from collections.abc import Mapping

from game.app import current_game_services
from message import M

from ..command import GameCommand, HelpSpec


@GameCommand.command(
    cmd="查看物品",
    guard_rule="始终可用",
    help=HelpSpec(
        category="资源",
        summary="按编号或名称查看正式物品定义与功能",
        usage=("查看物品 编号", "查看物品 名称"),
        side_effect="只读查询，不改变人物、背包或世界状态",
        order=10,
    ),
)
async def inspect_item(
    *,
    message: str,
    manager,
    **_,
) -> None:
    query = " ".join(str(message or "").split())
    if not query:
        await manager.send(
            M.document()
            .section("查看物品", icon="item")
            .line("请提供物品编号或完整名称。")
            .line("例如：查看物品 100005")
            .line("例如：查看物品 小还丹")
            .build(),
        )
        return

    result = current_game_services().features.chakan_wupin.inspect(query)
    if result.detail is None and result.candidates:
        reply = (
            M.document()
            .header("物品查询")
            .section("名称不唯一", icon="notice")
            .line(f"“{query}”对应多个物品，请使用编号精确查看。")
            .section("候选")
        )
        for index, candidate in enumerate(result.candidates, start=1):
            reply.item(index, f"{candidate.name} · {candidate.category} · {candidate.item_id}")
        await manager.send(reply.build())
        return

    if result.detail is None:
        await manager.send(
            M.document()
            .section("物品查询", icon="notice")
            .line(f"未找到物品：{query}")
            .line("请使用正式编号或 JSON 中的完整名称。")
            .build(),
        )
        return

    detail = result.detail
    reply = (
        M.document()
        .header(detail.name)
        .section("基础信息", icon="item")
        .row(("类别", detail.category), ("编号", detail.item_id))
        .section("说明", icon="docs")
        .line(detail.description)
    )
    effect = detail.fields.get("使用效果")
    if effect is not None:
        reply.section("功能", icon="skill")
        for line in _effect_lines(effect):
            reply.line(line)
    if "强度" in detail.fields:
        reply.section("强度", icon="status").line(str(detail.fields["强度"]))
    if effect is None and "强度" not in detail.fields:
        reply.section("功能", icon="notice").line("当前定义未声明直接使用效果。")
    await manager.send(reply.build())


def _effect_lines(value: object, prefix: str = "") -> tuple[str, ...]:
    if isinstance(value, Mapping):
        lines: list[str] = []
        for key, raw in value.items():
            label = f"{prefix}{key}" if not prefix else f"{prefix}·{key}"
            if isinstance(raw, Mapping):
                lines.extend(_effect_lines(raw, label))
            elif isinstance(raw, (list, tuple)):
                lines.append(f"{label}：{'、'.join(map(str, raw))}")
            else:
                lines.append(f"{label}：{raw}")
        return tuple(lines)
    return (str(value),)


__all__ = []
