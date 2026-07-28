"""配置驱动的业务模块发现与 HTTP 路由装载。

框架只根据 .env 中的模块计划导入包。普通模块依靠导入完成命令、回调或任务
注册；路由模块还必须公开 router。launch 不硬编码任何业务包名。
"""

from fastapi import APIRouter
from abc import abstractmethod
from pathlib import Path
from importlib import import_module
from typing import Callable, Iterator, List, Tuple

from .log import C, logger
from .config import config


class Routers:
    """保存待导入模块和待注册路由模块。"""

    router_list: List[str] = []
    module_list: List[str] = []

    @staticmethod
    def clear() -> None:
        """
        清空上一次收集到的模块和路由。

        create_app() 在测试或热重载场景下可能被多次调用。
        每次重新收集前先清空，避免把旧结果带到新的 app 里。
        """

        Routers.router_list = []
        Routers.module_list = []

    @staticmethod
    def run() -> None:
        """按原顺序去重。"""

        Routers.router_list = list(dict.fromkeys(Routers.router_list))
        Routers.module_list = list(dict.fromkeys(Routers.module_list))

    class Router:
        """用于类型约束的 HTTP 路由模块协议。"""

        @abstractmethod
        def router(self) -> "APIRouter":
            """带 HTTP 路由的模块需要在 __init__.py 暴露 router。"""
            ...


class LoadRouter:
    """根据 RouterConfig 收集模块路径。"""

    @staticmethod
    def module_to_path(folder: str) -> Path:
        """把 Python 模块路径转成本地目录路径。"""

        path = Path(*folder.split(".")) if "." in folder else Path(folder)
        if path.is_absolute():
            return path

        return config.base_dir / path

    @staticmethod
    def package_children(folder: str) -> Iterator[str]:
        """遍历某个目录下带 __init__.py 的子包。"""

        base_path = LoadRouter.require_directory(folder)

        for child in sorted(base_path.iterdir(), key=lambda item: item.name):
            if child.is_dir() and (child / "__init__.py").exists():
                yield child.name

    @staticmethod
    def require_directory(folder: str) -> Path:
        """确认配置指向的是一个真实目录。"""

        path = LoadRouter.module_to_path(folder)
        if not path.is_dir():
            raise FileNotFoundError(f"模块目录不存在或不是目录：{folder} -> {path}")

        return path

    @staticmethod
    def require_package(folder: str) -> Path:
        """确认配置指向的是一个 Python 包目录。"""

        path = LoadRouter.require_directory(folder)
        init_file = path / "__init__.py"
        if not init_file.is_file():
            raise FileNotFoundError(f"模块缺少 __init__.py：{folder} -> {init_file}")

        return path

    @staticmethod
    def load_router_folders(folder: str) -> None:
        """收集某个目录下所有带 router 的子模块。

        例：folder="src" 时，会收集 src.xxx、src.yyy。
        """

        for module in LoadRouter.package_children(folder):
            Routers.router_list.append(f"{folder}.{module}")
            Routers.module_list.append(f"{folder}.{module}")

    @staticmethod
    def load_router_folder(folder: str) -> None:
        """收集一个自身带 router 的模块。"""

        LoadRouter.require_package(folder)
        Routers.router_list.append(folder)
        Routers.module_list.append(folder)

    @staticmethod
    def load_router_group(folder: str) -> None:
        """收集一个路由组。

        组本身带 router，组内子目录只作为普通模块导入。
        """

        LoadRouter.load_router_folder(folder)
        for module in LoadRouter.package_children(folder):
            Routers.module_list.append(f"{folder}.{module}")

    @staticmethod
    def load_module(folder: str) -> None:
        """收集一个普通模块，不要求它提供 router。"""

        Routers.module_list.append(folder)

    @staticmethod
    def load_module_group(folder: str) -> None:
        """收集某个目录下所有普通子模块。

        例：folder="auto" 时，会收集 auto.cfg 这类子模块。
        """

        for module in LoadRouter.package_children(folder):
            Routers.module_list.append(f"{folder}.{module}")


def FastAPILoadRouter() -> None:
    """按配置收集业务模块和路由模块。"""

    Routers.clear()

    load_plan: Tuple[Tuple[Callable[[str], None], List[str]], ...] = (
        (LoadRouter.load_module_group, config.router.module_groups),
        (LoadRouter.load_router_folder, config.router.router_folders),
        (LoadRouter.load_module, config.router.modules),
        (LoadRouter.load_router_group, config.router.router_groups),
        (LoadRouter.load_router_folders, config.router.router_child_folders),
    )

    for loader, modules in load_plan:
        for module in modules:
            loader(module)


def module_tag(module_name: str) -> str:
    """根据模块名生成 /docs 分类名。

    例如：

        src.室温监控 -> 室温监控
        src.user.api -> api

    以后想显示更完整的分类名，可以只改这里。
    """

    return module_name.rsplit(".", 1)[-1]


def FastAPIIncludeRouter(app) -> None:
    """导入业务模块，并把 HTTP router 注册到 FastAPI。

    必须在 create_app() 阶段执行，否则 /docs 生成 OpenAPI 时可能看不到路由。
    - 普通模块只导入，用来触发 OnEvent / Scheduler 等装饰器注册。
    - 带 router 的模块会 app.include_router(...)。
    - router 会自动补 tags=[模块名]，用于 /docs 分类。
    """

    if getattr(app.state, "business_router_loaded", False):
        return

    FastAPILoadRouter()
    Routers.run()

    for module_name in Routers.module_list:
        try:
            module: Routers.Router = import_module(module_name)
        except Exception as exc:
            logger.opt(colors=True, exception=exc).error(
                C.join(
                    C.fail("Loaded module error"),
                    C.kv("module", module_name),
                )
            )
            raise

        if module_name in Routers.router_list:
            router = getattr(module, "router", None)
            if router is None:
                raise AttributeError(f"路由模块未暴露 router：{module_name}")

            tag = module_tag(module_name)
            app.include_router(router, tags=[tag])
            logger.opt(colors=True).success(
                C.join(
                    C.ok("Loaded module include router"),
                    C.kv("module", module_name),
                    C.kv("tag", tag),
                )
            )
        else:
            logger.opt(colors=True).success(
                C.join(
                    C.ok("Loaded module not include router"),
                    C.kv("module", module_name),
                )
            )

    app.state.business_router_loaded = True
