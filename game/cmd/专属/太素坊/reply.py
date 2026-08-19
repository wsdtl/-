from game.features.yixing import YixingFeature, YixingResult
from message import M


def result(feature: YixingFeature, value: YixingResult):
    return M.document().header(feature.copy("结算", "标题")).section(value.name, icon="character").row(("原性别", value.gender_before), ("现性别", value.gender_after)).line(feature.copy("结算", "完成")).build()


def error(feature: YixingFeature, message: str):
    return M.document().section(feature.copy("错误", "标题"), icon="notice").line(message).build()
