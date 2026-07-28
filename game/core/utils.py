"""多个 feature 共用、且不包含具体玩法规则的小工具。"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> str:
    """返回可直接持久化的 UTC ISO 时间。"""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def elapsed_seconds(started_at: str, ended_at: str) -> int:
    """计算两个 ISO 时间之间经过的完整秒数，异常倒时钟按零处理。"""

    started = datetime.fromisoformat(str(started_at))
    ended = datetime.fromisoformat(str(ended_at))
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if ended.tzinfo is None:
        ended = ended.replace(tzinfo=timezone.utc)
    return max(0, int((ended - started).total_seconds()))


def require_user_id(value: object) -> str:
    """规整并校验消息框架提供的用户 ID。"""

    user_id = str(value or "").strip()
    if not user_id:
        raise ValueError("用户 ID 不能为空")
    return user_id


__all__ = ["elapsed_seconds", "require_user_id", "utc_now"]
