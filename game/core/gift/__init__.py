"""玩家资产赠送核心微服务。"""

from .contracts import GiftError, GiftResult, GiftSendCommand
from .service import GiftService

__all__ = ["GiftError", "GiftResult", "GiftSendCommand", "GiftService"]
