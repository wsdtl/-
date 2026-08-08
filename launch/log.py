"""项目日志配置。

统一导入：

    from launch import logger, C

彩色日志：

    logger.opt(colors=True).success(
        f"{C.ok('模块加载成功')} {C.kv('module', module_name)}"
    )

注意：
    只有 logger.opt(colors=True) 会解析颜色标签。
    文件日志始终写入纯文本。
"""

import inspect
import logging
import re
import sys
from typing import Any

import loguru

from .config import config

# Loguru 用类似 <red> 的标签表示颜色；动态文本需要先转义。
COLOR_TAG_RE = re.compile(r"(\\*)(</?(?:[fb]g\s)?[^<>\s]*>)")


# 项目全局 logger。业务代码优先从 launch 统一导入。
logger: Any = loguru.logger


def source_name(record: dict) -> str:
    """得到日志来源名称；uvicorn 相关日志统一显示为 uvicorn。"""

    name = record["extra"].get("source", record["name"])
    if "uvicorn" in name:
        return "uvicorn"
    return name


def patch_record(record: dict) -> None:
    """给每条日志补 extra["source"]，统一输出格式。"""

    record["extra"]["source"] = source_name(record)


class C:
    """日志颜色工具。

    只生成 loguru 颜色标签，不直接输出日志。

        logger.opt(colors=True).info(
            C.join(
                C.ok("连接成功"),
                C.kv("path", path),
            )
        )
    """

    @staticmethod
    def text(value: Any) -> str:
        """把任意值转成适合彩色日志的安全文本。"""

        def escape_tag(match: re.Match[str]) -> str:
            slashes, tag = match.groups()

            # 变成奇数个反斜杠，让 loguru 把 <tag> 当普通文本。
            return "\\" * (len(slashes) * 2 + 1) + tag

        return COLOR_TAG_RE.sub(escape_tag, str(value))

    @staticmethod
    def wrap(value: Any, color: str, *, bold: bool = False, underline: bool = False) -> str:
        """给文本包上 loguru 颜色和样式标签。"""

        text = C.text(value)
        if bold:
            text = f"<bold>{text}</bold>"
        if underline:
            text = f"<underline>{text}</underline>"
        return f"<{color}>{text}</{color}>"

    @staticmethod
    def black(text: Any) -> str:
        return C.wrap(text, "black")

    @staticmethod
    def red(text: Any) -> str:
        return C.wrap(text, "red")

    @staticmethod
    def green(text: Any) -> str:
        return C.wrap(text, "green")

    @staticmethod
    def yellow(text: Any) -> str:
        return C.wrap(text, "yellow")

    @staticmethod
    def blue(text: Any) -> str:
        return C.wrap(text, "blue")

    @staticmethod
    def magenta(text: Any) -> str:
        return C.wrap(text, "magenta")

    @staticmethod
    def cyan(text: Any) -> str:
        return C.wrap(text, "cyan")

    @staticmethod
    def white(text: Any) -> str:
        return C.wrap(text, "white")

    @staticmethod
    def ok(text: Any) -> str:
        """成功状态，绿色加粗。"""

        return C.wrap(text, "green", bold=True)

    @staticmethod
    def warn(text: Any) -> str:
        """警告状态，黄色加粗。"""

        return C.wrap(text, "yellow", bold=True)

    @staticmethod
    def fail(text: Any) -> str:
        """失败状态，红色加粗。"""

        return C.wrap(text, "red", bold=True)

    @staticmethod
    def key(text: Any) -> str:
        """字段名颜色。"""

        return C.wrap(text, "cyan")

    @staticmethod
    def value(text: Any) -> str:
        """字段值颜色。"""

        return C.wrap(text, "yellow")

    @staticmethod
    def kv(key: Any, value: Any) -> str:
        """生成 key=value 形式的彩色片段。"""

        return f"{C.key(key)}={C.value(value)}"

    @staticmethod
    def join(*parts: Any, sep: str = " ") -> str:
        """把多个日志片段拼成一个字符串。

        这个函数专门解决“日志太长，想换行排版”的问题。

        用法：
            logger.opt(colors=True).info(
                C.join(
                    C.warn("业务缓存已更新"),
                    C.kv("time", datetime.now()),
                    C.kv("count", len(docs)),
                )
            )

        注意：
        - logger.info(...) 仍然只接收一个 message 参数。
        - 逗号只写在 C.join(...) 里面，用来让代码更好排版。
        - None 会被忽略，方便按条件追加日志片段。
        """

        return sep.join(str(part) for part in parts if part is not None)

    @staticmethod
    def msg(text: Any) -> str:
        """普通消息内容，白色显示。"""

        return C.white(text)


class LoguruHandler(logging.Handler):
    """把标准 logging 日志转发给 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        """接收标准 logging 的 record，并转发给 loguru。"""

        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 让日志定位到真正调用 logging 的位置。
        frame = inspect.currentframe()
        depth = 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.bind(source=record.name).opt(depth=depth, exception=record.exc_info).log(
            level,
            record.getMessage(),
        )

    @staticmethod
    def log_filter(record: dict) -> bool:
        """保留统一过滤入口。"""

        return True


# 控制台日志格式，带颜色。
# 示例：05-14 21:36:19 [INFO] uvicorn | Shutting down
CONSOLE_FORMAT = (
    "<green>{time:MM-DD HH:mm:ss}</green> "
    "[<level>{level}</level>] "
    "<cyan>{extra[source]}</cyan> | "
    "{message}"
)


# 文件日志格式，纯文本。
FILE_FORMAT = "{time:MM-DD HH:mm:ss} [{level}] {extra[source]} | {message}"


def use_color() -> bool:
    """根据 LOG_COLOR 判断控制台是否显示颜色。"""

    if config.log.color in {"1", "true", "yes", "on"}:
        return True
    if config.log.color in {"0", "false", "no", "off"}:
        return False
    return sys.stdout.isatty()


def setup_log_levels() -> None:
    """设置 <level>...</level> 对应的颜色。"""

    logger.level("TRACE", color="<cyan><dim>")
    logger.level("DEBUG", color="<blue>")
    logger.level("INFO", color="<white>")
    logger.level("SUCCESS", color="<green><bold>")
    logger.level("WARNING", color="<yellow><bold>")
    logger.level("ERROR", color="<red><bold>")
    logger.level("CRITICAL", color="<red><bold><underline>")


def setup_logger() -> tuple[int, int]:
    """初始化控制台和文件日志。"""

    config.log.dir.mkdir(parents=True, exist_ok=True)

    # 移除默认输出，再添加项目自己的控制台和文件输出。
    logger.remove()
    logger.configure(patcher=patch_record)
    setup_log_levels()

    console_id = logger.add(
        sys.stdout,
        level=config.log.level,
        format=CONSOLE_FORMAT,
        colorize=use_color(),
        backtrace=True,
        diagnose=False,
        enqueue=True,
        filter=LoguruHandler.log_filter,
    )

    file_id = logger.add(
        config.log.file,
        level=config.log.level,
        format=FILE_FORMAT,
        encoding="utf-8",
        rotation=config.log.rotation,
        retention=config.log.retention,
        compression=config.log.compression,
        colorize=False,
        backtrace=True,
        diagnose=False,
        enqueue=True,
        filter=LoguruHandler.log_filter,
    )

    return console_id, file_id


logger_id, local_logger_id = setup_logger()


__autodoc__ = {
    "C": False,
    "logger_id": False,
    "local_logger_id": False,
}


# uvicorn 日志配置。
# main.py 通过 uvicorn.run(..., log_config=LOGGING_CONFIG) 使用。
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "default": {
            "class": "launch.log.LoguruHandler",
            "level": config.log.level,
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": config.log.level, "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": config.log.level, "propagate": False},
        "uvicorn.access": {"handlers": ["default"], "level": config.log.level, "propagate": False},
    },
}
