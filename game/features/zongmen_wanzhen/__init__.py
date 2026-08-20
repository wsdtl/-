"""宗门万珍殿玩法微服务。"""

from .contracts import (
    WanzhenAction,
    WanzhenCopy,
    WanzhenFeatureError,
    WanzhenPage,
    WanzhenTransferResult,
)
from .service import WanzhenFeature

__all__ = [
    "WanzhenAction",
    "WanzhenCopy",
    "WanzhenFeature",
    "WanzhenFeatureError",
    "WanzhenPage",
    "WanzhenTransferResult",
]
