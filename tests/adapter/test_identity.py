from __future__ import annotations

import pytest

from launch.adapter import (
    AdapterCapabilities,
    MessageContext,
    ReplyTarget,
)
from launch.adapter.qq.event import parse_message_event
from launch.adapter.qq.target import QqSendTarget, qq_group_target


def test_qq_group_event_keeps_user_and_name_as_separate_facts() -> None:
    event = parse_message_event(
        {
            "t": "GROUP_AT_MESSAGE_CREATE",
            "id": "event-1",
            "d": {
                "id": "message-1",
                "content": "帮助",
                "group_openid": "group-1",
                "author": {
                    "member_openid": "qq-user-1",
                    "user_openid": "qq-user-1",
                    "nickname": "群昵称",
                },
            },
        }
    )

    assert event is not None
    assert event.user_id == "qq-user-1"
    assert event.sender_name == "群昵称"
    send_target = QqSendTarget.from_event(event)
    assert send_target.user_id == "qq-user-1"
    assert send_target.group_id == "group-1"
    reply_target = qq_group_target(
        "group-1",
        user_id=event.user_id,
    )
    assert reply_target.user_id == "qq-user-1"
    assert reply_target.target_id == "group-1"


def test_qq_private_event_uses_the_same_user_id_name() -> None:
    event = parse_message_event(
        {
            "t": "C2C_MESSAGE_CREATE",
            "id": "event-2",
            "d": {
                "id": "message-2",
                "content": "帮助",
                "author": {
                    "user_openid": "qq-user-1",
                    "username": "私聊昵称",
                },
            },
        }
    )

    assert event is not None
    assert event.user_id == "qq-user-1"
    assert event.group_id == ""
    assert event.sender_name == "私聊昵称"
    assert QqSendTarget.from_event(event).user_id == "qq-user-1"


def test_qq_interaction_normalizes_protocol_openid_to_user_id() -> None:
    event = parse_message_event(
        {
            "t": "INTERACTION_CREATE",
            "id": "event-3",
            "d": {
                "id": "interaction-1",
                "group_openid": "group-1",
                "group_member_openid": "qq-user-1",
                "data": {
                    "resolved": {
                        "button_data": "帮助",
                        "message_id": "message-3",
                    }
                },
            },
        }
    )

    assert event is not None
    assert event.user_id == "qq-user-1"
    assert event.group_id == "group-1"


def test_message_context_rejects_mixed_user_ids() -> None:
    target = ReplyTarget("local", "user-2", "user-2", "private")

    with pytest.raises(ValueError, match="user_id 不一致"):
        MessageContext(
            adapter="local",
            user_id="user-1",
            request_id="event-1",
            command="帮助",
            message="",
            raw_message="帮助",
            conversation_type="private",
            reply_target=target,
            capabilities=AdapterCapabilities(),
        )
