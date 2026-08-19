"""交易玩法微服务的稳定公共契约。"""


class TradeFeatureError(RuntimeError):
    """交易玩法无法完成请求。"""


__all__ = ["TradeFeatureError"]
