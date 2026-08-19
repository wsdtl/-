from game.features.guiyuan import GuiyuanFeature, GuiyuanPreview, GuiyuanResult
from message import M


def preview(feature: GuiyuanFeature, value: GuiyuanPreview):
    builder = M.document().header(feature.copy("预览", "标题")).section(value.location_name, icon="location").field("同行道侣", value.companion_name).line(feature.copy("预览", "说明"))
    for index, (category, count) in enumerate(value.counts, start=1):
        builder.item(index, f"{category} · 当前承载 {count} 项")
    return builder.line(feature.copy("预览", "有丹" if value.has_medicine else "无丹")).build()


def result(feature: GuiyuanFeature, value: GuiyuanResult):
    return M.document().header(feature.copy("结算", "标题")).section(value.companion_name, icon="companion").line(feature.copy("结算", "完成", 类别=value.category, 数量=value.content_count)).build()


def error(feature: GuiyuanFeature, message: str):
    return M.document().section(feature.copy("错误", "标题"), icon="notice").line(message).build()
