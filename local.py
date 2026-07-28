"""通过正式本地适配器触发一条消息。"""

from __future__ import annotations

from argparse import ArgumentParser
import asyncio

from launch.adapter.local import LocalEventHandler, dispatch
from main import create_app


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="从本地适配器触发晓楠修仙命令")
    parser.add_argument("command", nargs="+", help="要发送的完整命令")
    parser.add_argument("--user", default="local-player", help="本地用户 ID")
    parser.add_argument("--event", default="", help="可选消息事件 ID")
    return parser


async def run() -> int:
    args = build_parser().parse_args()
    create_app()
    await LocalEventHandler.run()
    try:
        result = await dispatch(
            client_id=args.user,
            raw_message=" ".join(args.command),
            event_id=args.event,
        )
    finally:
        await LocalEventHandler.shutdown()

    for reply in result.replies:
        content = getattr(reply.message, "content", "")
        if content:
            print(content)
    return 0 if result.matched and result.replies else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
