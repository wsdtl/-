"""运行期按文件名读取 data 目录中的 JSON。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonDataError(ValueError):
    """请求的数据文件不存在、越界或不是合法 JSON。"""


class JsonDataReader:
    """按需读取单个文件或一个分类目录，不预载、不缓存。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def read(self, relative_path: str | Path) -> Any:
        raw_path = str(relative_path or "").strip()
        if not raw_path:
            raise JsonDataError("JSON 文件必须使用 data 内的相对路径")
        requested = Path(raw_path)
        if requested.is_absolute():
            raise JsonDataError("JSON 文件必须使用 data 内的相对路径")
        if requested.suffix.lower() != ".json":
            requested = requested.with_suffix(".json")

        path = (self.root / requested).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise JsonDataError("JSON 文件不能超出 data 目录") from exc
        if not path.is_file():
            raise JsonDataError(f"数据文件不存在：{requested.as_posix()}")

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JsonDataError(f"数据文件读取失败：{requested.as_posix()}：{exc}") from exc

    def read_directory(self, relative_path: str | Path) -> tuple[tuple[str, Any], ...]:
        """读取分类目录内的全部 JSON；子目录由自己的组件另行负责。"""

        directory = self._resolve_directory(relative_path)
        files = sorted(
            (path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".json"),
            key=lambda path: path.name.casefold(),
        )
        if not files:
            requested = directory.relative_to(self.root).as_posix()
            raise JsonDataError(f"数据目录没有 JSON 文件：{requested}")
        result = []
        for path in files:
            relative = path.relative_to(self.root).as_posix()
            try:
                result.append((relative, json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError) as exc:
                raise JsonDataError(f"数据文件读取失败：{relative}：{exc}") from exc
        return tuple(result)

    def _resolve_directory(self, relative_path: str | Path) -> Path:
        raw_path = str(relative_path or "").strip()
        if not raw_path:
            raise JsonDataError("JSON 目录必须使用 data 内的相对路径")
        requested = Path(raw_path)
        if requested.is_absolute():
            raise JsonDataError("JSON 目录必须使用 data 内的相对路径")
        directory = (self.root / requested).resolve()
        try:
            directory.relative_to(self.root)
        except ValueError as exc:
            raise JsonDataError("JSON 目录不能超出 data 目录") from exc
        if not directory.is_dir():
            raise JsonDataError(f"数据目录不存在：{requested.as_posix()}")
        return directory
