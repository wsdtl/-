"""托管命令回复构造。"""

from __future__ import annotations

from game.features.tuoguan import HostingCopy, HostingResult
from message import M

_MODE_KEYS = {"personal": "独行", "team": "队伍", "sect": "宗门"}
_ERROR_KEYS = {
    "member_cannot_start": "不是领队",
    "member_cannot_cancel": "跟随者不能取消",
    "already_hosting": "已经托管",
    "not_hosting": "尚未托管",
    "participant_busy": "参与者忙碌",
    "fellowship_conflict": "同行冲突",
    "group_changed": "同行变化",
    "state_incomplete": "同行变化",
    "session_invalid": "同行变化",
    "transaction_invalid": "同行变化",
    "request_conflict": "同行变化",
}


def result(copy: HostingCopy, value: HostingResult):
    mode_key = _MODE_KEYS[value.mode]
    return (
        M.document()
        .header(_text(copy, "结果", "标题"))
        .inline_section(
            _text(copy, "结果", "标题"),
            _text(copy, "结果", value.action),
            icon=_text(copy, "图标", "结果"),
        )
        .section(_text(copy, "结果", "范围"), icon=_text(copy, "图标", "状态"))
        .field(_text(copy, "结果", "范围"), _text(copy, "结果", mode_key))
        .field(_text(copy, "结果", "人数"), value.participant_count)
        .build()
    )


def error(copy: HostingCopy, code: str):
    return (
        M.document()
        .section(_text(copy, "结果", "标题"), icon=_text(copy, "图标", "结果"))
        .line(_text(copy, "错误", _ERROR_KEYS.get(code, "同行变化")))
        .build()
    )


def _text(copy: HostingCopy, section: str, key: str) -> str:
    return copy.text[section][key]


__all__ = ["error", "result"]
