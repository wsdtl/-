from game.features.butian import ButianFeature, ButianResult
from message import M


def result(feature: ButianFeature, value: ButianResult):
    return M.document().header(feature.copy("结算", "标题")).section(value.target_name, icon="cultivation").field("补正境界", value.realm_name).field(value.attribute, value.value).line(feature.copy("结算", "完成")).build()


def error(feature: ButianFeature, message: str):
    return M.document().section(feature.copy("错误", "标题"), icon="notice").line(message).build()
