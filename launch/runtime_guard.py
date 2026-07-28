"""框架运行时互斥保护。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from .config import config
from .log import C, logger


class RuntimeGuard:
    """保护一个项目实例同一时间只进入一个服务进程。"""

    _held_paths: set[Path] = set()

    def __init__(self, lock_file: Path | None = None) -> None:
        self.lock_file = lock_file or config.base_dir / "launch" / "runtime" / "server.lock"
        self._handle: BinaryIO | None = None

    def acquire(self) -> None:
        """获取项目运行锁，失败时直接中止启动。"""

        if self._handle is not None:
            return

        path = self.lock_file.resolve()
        if path in RuntimeGuard._held_paths:
            raise RuntimeError(_lock_error_message(path))

        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+b")
        try:
            _lock_file(handle)
        except OSError as exc:
            handle.close()
            raise RuntimeError(_lock_error_message(path)) from exc

        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n".encode("ascii"))
        handle.flush()

        RuntimeGuard._held_paths.add(path)
        self.lock_file = path
        self._handle = handle
        logger.opt(colors=True).success(
            C.join(
                C.ok("运行时单实例锁已获取"),
                C.kv("lock", path),
            )
        )

    def release(self) -> None:
        """释放项目运行锁。"""

        handle = self._handle
        if handle is None:
            return

        path = self.lock_file.resolve()
        try:
            _unlock_file(handle)
        finally:
            handle.close()
            RuntimeGuard._held_paths.discard(path)
            self._handle = None


def _lock_file(handle: BinaryIO) -> None:
    """跨平台非阻塞文件锁。"""

    if os.name == "nt":
        import msvcrt

        _ensure_lock_byte(handle)
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: BinaryIO) -> None:
    """释放跨平台文件锁。"""

    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _ensure_lock_byte(handle: BinaryIO) -> None:
    """Windows locking 需要锁定至少一个存在的字节。"""

    handle.seek(0, os.SEEK_END)
    if handle.tell() > 0:
        return
    handle.write(b"\0")
    handle.flush()


def _lock_error_message(path: Path) -> str:
    return (
        f"检测到同一个项目实例已经在运行：{path}。"
        "本项目包含定时任务和后台消息队列，不能多开服务端或使用多 worker。"
    )


runtime_guard = RuntimeGuard()
