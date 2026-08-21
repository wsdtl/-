"""铜雀台命令回复构造。"""

from __future__ import annotations

from game.features.tongquetai import (
    TongquetaiFeature,
    TongquetaiPreview,
    TongquetaiSettlement,
)
from message import Action, M


def preview(feature: TongquetaiFeature, value: TongquetaiPreview):
    builder = (
        M.document()
        .header(feature.copy("预览", "标题"))
        .section(value.location_name, icon="location")
        .line(feature.copy("预览", "登台"))
        .line(feature.copy("预览", "启阵", 名称=value.companion_name))
        .row(
            (feature.copy("预览", "道侣"), f"{value.companion_name} · {value.companion_level}级"),
            (feature.copy("预览", "修为"), value.cultivation),
        )
        .section("两条归流", icon="notice")
        .row(
            (feature.copy("预览", "护契所得"), value.protected.offered),
            (feature.copy("预览", "人物承接"), value.protected.accepted),
        )
        .field(feature.copy("预览", "溢散"), value.protected.discarded)
        .line(feature.copy("预览", "护契预示"))
        .row(
            (feature.copy("预览", "离契所得"), value.severed.offered),
            (feature.copy("预览", "人物承接"), value.severed.accepted),
        )
        .field(feature.copy("预览", "溢散"), value.severed.discarded)
        .line(feature.copy("预览", "离契预示"))
        .line(
            feature.copy("预览", "护契可用")
            if value.has_medicine
            else feature.copy("预览", "护契不足")
        )
        .line(feature.copy("预览", "保留"))
        .line(feature.copy("预览", "警示"))
    )
    if value.treasure_activation is not None:
        activation = value.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    actions = tuple(
        Action(
            str(button["编号"]),
            str(button["名称"]),
            str(button["命令"]),
            behavior=str(button["行为"]),
            style=str(button["样式"]),
        )
        for button in feature.actions(has_medicine=value.has_medicine)
    )
    return builder.actions(actions).build()


def settled(feature: TongquetaiFeature, value: TongquetaiSettlement):
    builder = (
        M.document()
        .header(feature.copy("结算", "标题"))
        .section(value.location_name, icon="notice")
        .line(feature.copy("结算", "剥离", 名称=value.companion_name))
        .row(
            (feature.copy("结算", "人物"), value.character_name),
            (feature.copy("结算", "道侣"), value.companion_name),
        )
        .row(
            (feature.copy("结算", "获得修为"), value.accepted),
            (feature.copy("结算", "溢散修为"), value.discarded),
        )
        .line(feature.copy("结算", "重置", 名称=value.companion_name))
    )
    if value.replayed:
        builder.line(feature.copy("结算", "已处理"))
    elif value.mode == "护契":
        builder.line(feature.copy("结算", "护契")).line(
            feature.copy("结算", "护契回应", 名称=value.companion_name)
        ).field("消耗", f"{value.medicine_grade_name}{value.medicine_name} × 1")
    else:
        builder.line(feature.copy("结算", "离契")).line(
            feature.copy("结算", "离契回应", 名称=value.companion_name)
        ).line(
            feature.copy(
                "结算",
                "返回",
                名称=value.companion_name,
                地点=value.companion_origin,
            )
        )
    if value.treasure_activation is not None:
        activation = value.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    return builder.build()


def error(feature: TongquetaiFeature, message: str):
    return (
        M.document()
        .section(feature.copy("错误", "标题"), icon="notice")
        .line(message)
        .line(feature.copy("错误", "格式"))
        .build()
    )


__all__ = ["error", "preview", "settled"]
