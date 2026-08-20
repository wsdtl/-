"""宗门命令回复构造。"""

from __future__ import annotations

from game.features.zongmen import SectAction, SectCopy, SectOperationResult, SectPage
from message import M

from ...actions import message_actions

_ERROR_KEYS = {
    "name_invalid": "名称无效",
    "name_occupied": "名称占用",
    "entrance_occupied": "入口占用",
    "already_member": "已经加入",
    "not_member": "未加入",
    "not_leader": "不是宗主",
    "leader_cannot_leave": "宗主不能退出",
    "target_missing": "缺少目标",
    "target_not_found": "目标不存在",
    "target_ambiguous": "目标不唯一",
    "cannot_invite_self": "不能邀请自己",
    "not_same_location": "不在同处",
    "not_surface": "不在地表",
    "target_busy": "目标忙碌",
    "target_already_member": "目标已经加入",
    "pending_invitation_exists": "已有邀请",
    "invitation_missing": "没有邀请",
    "invitation_expired": "邀请失效",
    "target_not_member": "目标不是成员",
    "cannot_remove_leader": "不能操作宗主",
    "cannot_transfer_self": "不能转让自己",
    "sect_changed": "宗门变化",
    "storage_not_empty": "宗藏非空",
}


def page(copy: SectCopy, value: SectPage, actions: tuple[SectAction, ...], *, notice: str = ""):
    builder = M.document().header(_text(copy, "查看", "标题"))
    if notice:
        builder.inline_section(_text(copy, "查看", "状态"), notice, icon=_text(copy, "图标", "结果"))
    if value.page == "未加入":
        builder.section(_text(copy, "查看", "状态"), icon=_text(copy, "图标", "宗门")).line(_text(copy, "查看", "未加入"))
    elif value.page == "待处理邀请":
        builder.section(_text(copy, "查看", "待处理邀请"), icon=_text(copy, "图标", "邀请")).line(_text(copy, "格式", "邀请来源").format(姓名=value.invitation_inviter_name, 宗门=value.invitation_name)).line(_text(copy, "格式", "邀请时限").format(分钟=value.invitation_minutes))
    else:
        builder.section(_text(copy, "查看", "状态"), icon=_text(copy, "图标", "宗门")).field(_text(copy, "查看", "名称"), value.name).field(_text(copy, "查看", "入口"), value.entrance).field(_text(copy, "查看", "洞天"), _text(copy, "格式", "洞天").format(洞天编号=value.cave_id))
        builder.section(_text(copy, "查看", "成员"), icon=_text(copy, "图标", "成员"))
        for index, member in enumerate(value.members, start=1):
            builder.item(index, _text(copy, "格式", "成员").format(姓名=member.name, 身份=member.role))
    return builder.actions(message_actions(actions)).build()


def operation(copy: SectCopy, value: SectOperationResult, actions: tuple[SectAction, ...]):
    notice = _text(copy, "结果", value.action).format(姓名=value.target_name)
    return page(copy, value.page, actions, notice=notice)


def error(copy: SectCopy, code: str):
    return M.document().section(_text(copy, "查看", "标题"), icon=_text(copy, "图标", "结果")).line(_text(copy, "错误", _ERROR_KEYS.get(code, "宗门变化"))).build()


def format_error(copy: SectCopy):
    return M.document().section(_text(copy, "查看", "标题"), icon=_text(copy, "图标", "结果")).line(_text(copy, "错误", "格式")).build()


def _text(copy: SectCopy, section: str, key: str) -> str:
    return copy.text[section][key]


__all__ = ["error", "format_error", "operation", "page"]
