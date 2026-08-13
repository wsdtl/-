"""按正式身份、所在地与喜爱灵植重建道侣结交内容。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
WORLD = DATA / "内容" / "世界"
PLANTS = DATA / "内容" / "物品" / "灵植"
ORES = DATA / "内容" / "物品" / "灵矿"

TEMPERAMENTS = (
    "沉静谨慎，不轻易表露喜恶",
    "清醒果决，遇事从不拖泥带水",
    "温和持重，习惯先听完别人的话",
    "疏朗坦荡，不喜欢无谓的试探",
    "冷峻自律，对自己比对旁人更严",
    "从容敏锐，常能察觉细微变化",
    "清傲寡言，不肯轻易向人低头",
    "热诚直率，心中所想很少遮掩",
    "随和细致，总会记住旁人的小事",
    "坚韧沉着，越到困境越显镇定",
    "洒脱不羁，不愿受繁文缛节束缚",
    "谨严克制，做任何事都留有分寸",
    "外柔内刚，看似温和却极有主见",
    "锋锐好胜，把每次交手都看得认真",
    "淡泊安静，更愿意用行动表达心意",
    "明快机敏，常以轻松言语化解僵局",
    "稳重务实，相信长久胜过一时热烈",
    "孤高自持，只敬佩真正守诺之人",
    "心思通透，不愿让情绪支配判断",
    "真诚坦率，厌恶虚情与敷衍",
    "耐心绵长，认定一事便不会半途而废",
    "警觉内敛，需要很久才肯放下戒心",
    "豁达爽利，得失面前很少纠缠",
    "沉稳敏感，常把关切藏在寻常言语里",
)

RELATION_STYLES = (
    "对初识之人保持距离，熟悉之后却很护短",
    "看重言行一致，一次失信便很难重新取信",
    "不擅长说漂亮话，却愿意替亲近之人承担风险",
    "喜欢坦率相处，越是绕弯越令其戒备",
    "很少主动亲近旁人，一旦认定便极重情义",
    "习惯观察细节，会把别人无意说过的话记在心里",
    "愿意给人改过机会，却不会纵容反复欺瞒",
    "待人有礼而有边界，真正的信任需要时间积累",
    "容易被真诚打动，但不接受以贵重衡量心意",
    "更相信共同行路的经历，而不是一时承诺",
    "表面随性，实际对离别与失约格外在意",
    "遇到分歧会直接说清，不让猜疑积压",
    "对陌生人言语简短，对熟悉之人反而颇为健谈",
    "不愿欠下人情，收到心意总会设法回报",
    "认定的关系不会轻易放弃，但也不强留离去之人",
    "欣赏有耐心的人，不喜欢用热闹掩盖敷衍",
    "重视彼此选择，反感把陪伴视作理所当然",
    "习惯独自解决难题，却会接受可信之人的帮助",
    "很少追问过去，更在意眼前是否真诚",
    "对善意回应得含蓄，却从不忘记曾受的照拂",
    "愿意分享所知所见，但不会替旁人决定道路",
    "把承诺看得很重，宁可不说也不轻易食言",
    "喜欢安静相处，不需要时时以言语证明亲近",
    "面对真正信任的人，会显露少见的柔软与幽默",
)

TITLE_VALUES = {
    "游方医者": "行医时重视性命与分寸，不拿伤病换取人情",
    "守土剑修": "守土与守诺在其心中同样重要",
    "清修术士": "相信根基与心境比一时强弱更值得珍惜",
    "巡山修士": "熟悉山川草木，也尊重每个人选择的道路",
    "炼体行者": "推崇踏实磨炼，最看不起虚张声势",
    "护阵修士": "习惯顾全整体，也愿为亲近之人守住退路",
}
TITLE_ACTIONS = {
    "游方医者": "辨药察脉",
    "守土剑修": "巡看城防与旧日剑痕",
    "清修术士": "静坐调息、梳理术理",
    "巡山修士": "踏查山川与灵植长势",
    "炼体行者": "磨炼筋骨、校正吐纳",
    "护阵修士": "检视阵纹与地脉流转",
}
HEALING_REWARDS = ("100001", "100002", "100003", "100004", "100005", "100006")


def main() -> None:
    plants = _pool_items(PLANTS)
    ores = _pool_items(ORES)
    paths = sorted(WORLD.rglob("*道侣.json"))
    personalities: set[str] = set()
    count = 0
    for path in paths:
        rows = _read(path)
        location = path.stem.removesuffix("道侣")
        for row in rows:
            count += 1
            companion_id = _text(row["编号"])
            index = int(companion_id) - 500001
            identity = row["身份"]
            title = _text(identity["称号"])
            join = row["结交"]
            pool = _single(join["灵植池"], f"{companion_id}.结交.灵植池")
            terrain = pool.removeprefix("灵植-")
            personality = _personality(index, title)
            if personality in personalities:
                raise ValueError(f"性格方向重复：{companion_id}")
            personalities.add(personality)
            identity["性格方向"] = personality
            identity["话语"] = _daily_lines(location, terrain, title, index)
            row["说明"] = f"居于{location}的{title}，{personality}。"
            join["圆满回礼"] = _reward(title, index, terrain, plants, ores)
            join["喜好话语"] = _preference_line(terrain, index)
            join["收礼话语"] = _accept_lines(terrain, index)
            join["婉拒话语"] = _refuse_lines(title, terrain, index)
            join["圆满话语"] = _full_line(location, index)
            join["邀约话语"] = _invite_line(index)
            join["暂别话语"] = _farewell_line(location, index)
            join.pop("入队话语", None)
            join.pop("离队话语", None)
        _write(path, rows)
    if count != 264:
        raise ValueError(f"道侣数量应为264，实际为{count}")
    _audit(paths)
    print(f"已重建 {count} 名道侣的性格、话语与圆满回礼")


def _personality(index: int, title: str) -> str:
    temperament = TEMPERAMENTS[index % len(TEMPERAMENTS)]
    relation = RELATION_STYLES[(index // len(TEMPERAMENTS)) % len(RELATION_STYLES)]
    return f"{temperament}；{relation}；{TITLE_VALUES[title]}"


def _daily_lines(location: str, terrain: str, title: str, index: int) -> list[str]:
    openings = (
        f"我常在{location}{TITLE_ACTIONS[title]}，{terrain}一带的气候变化瞒不过我。",
        f"{location}看似平静，真正熟悉{terrain}风物的人却知道四时各有不同。",
        f"我在{location}住得久了，连{terrain}灵气何时转盛都能看出几分。",
    )
    reflections = (
        "同行之事不必急着许诺，肯把每一步走稳才是真心。",
        "修行路长，能记住旁人的一句话，有时比赠出重宝更难得。",
        "我不在意一时热闹，只看一个人久处之后是否仍守本心。",
        "人与人相交也像养护灵脉，急于求成反而容易伤了根本。",
    )
    return [openings[index % 3], reflections[index % 4]]


def _preference_line(terrain: str, index: int) -> str:
    endings = (
        "它们的气息最合我如今的修行。",
        "那份灵韵于我而言很容易辨认。",
        "比起贵重，我更看重它们生长得是否纯净。",
        "若采得其时，寻常一株也胜过华而不实的珍物。",
    )
    return f"我一向偏爱生长在{terrain}的灵植，{endings[index % 4]}"


def _accept_lines(terrain: str, index: int) -> list[str]:
    first = (
        f"这株灵植带着{terrain}特有的气息，你确实记住了我的喜好。",
        f"能在灵息未散时带来这株{terrain}灵植，你费心了。",
        f"这份{terrain}灵植保存得很好，我便不与你客气了。",
        f"我认得这缕灵韵，它正是{terrain}所生，多谢。",
    )
    second = (
        "礼物贵贱并不重要，被人放在心上才难得。",
        "我会好好收着，也会记得是谁将它带到我面前。",
        "你肯留意这些细枝末节，这份心意比灵植本身更重。",
        "既是你亲手送来，我便收下这份情分。",
    )
    return [first[index % 4], second[(index // 4) % 4]]


def _refuse_lines(title: str, terrain: str, index: int) -> list[str]:
    first = (
        f"心意我领了，只是此物与我的修行并不相合；我真正偏爱的是{terrain}灵植。",
        f"这件东西于我没有用处，你还是留给真正需要它的人吧。若是{terrain}灵植，我一眼便能认出。",
        f"不必用不合适的礼物勉强表达心意，我不会因此见怪。{terrain}所生的灵植才与我有缘。",
        f"我不能收下此物，白白耗费资源并非相交之道；{terrain}灵植才适合我如今的修行。",
    )
    second = {
        "游方医者": "药性与人心都不可强配，差之毫厘便会适得其反。",
        "守土剑修": "我更看重你是否坦诚，不必拿旁物遮掩。",
        "清修术士": "灵性不合便是无缘，强留反而扰乱气机。",
        "巡山修士": "山野之物各有归处，把它留给合适的人更好。",
        "炼体行者": "有话直说便好，不必在不合用的东西上费力。",
        "护阵修士": "阵中每一物都须各安其位，赠礼也是一样。",
    }
    return [first[index % 4], second[title]]


def _full_line(location: str, index: int) -> str:
    return (
        f"从初见到如今，你的心意我都记得。若你愿意，往后也可来{location}寻我。",
        "许多话不必反复说，你待我的真心，我已经明白了。",
        "一路相识并非偶然，这份情谊，我愿认真回应。",
        "能将一份心意坚持到今日并不容易，我不会轻慢它。",
    )[index % 4]


def _invite_line(index: int) -> str:
    return (
        "既然心意已明，我愿随你一同前行。",
        "往后的路不必独行，算我一个。",
        "你既亲自来邀，我便与你共走这一程。",
        "好，我收拾片刻，随后便与你动身。",
    )[index % 4]


def _farewell_line(location: str, index: int) -> str:
    return (
        f"我先回{location}，你处理完手边之事，再来寻我便是。",
        f"暂且别过。我仍在{location}，无需为我担心。",
        f"这一程先走到这里，我回{location}等你的消息。",
        f"你自去忙吧，我会回{location}照看旧事。",
    )[index % 4]


def _reward(
    title: str,
    index: int,
    terrain: str,
    plants: dict[str, tuple[str, ...]],
    ores: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    plant_ids = plants[f"灵植-{terrain}"]
    ore_ids = ores[f"灵矿-{terrain}"]
    if title == "游方医者":
        return {"编号": HEALING_REWARDS[index % 6], "品级": "02", "数量": 1}
    if title == "清修术士":
        return {"编号": plant_ids[index % 2], "品级": "02", "数量": 1}
    if title == "巡山修士":
        return {"编号": plant_ids[(index + 1) % 2], "品级": "01", "数量": 2}
    if title == "守土剑修":
        return {"编号": ore_ids[index % 2], "品级": "02", "数量": 1}
    if title == "炼体行者":
        return {"编号": ore_ids[(index + 1) % 2], "品级": "01", "数量": 2}
    return {"编号": ore_ids[index % 2], "品级": "02", "数量": 1}


def _pool_items(directory: Path) -> dict[str, tuple[str, ...]]:
    return {
        path.stem: tuple(_text(row["编号"]) for row in _read(path))
        for path in sorted(directory.glob("*.json"))
    }


def _audit(paths: list[Path]) -> None:
    rows = [row for path in paths for row in _read(path)]
    required = {
        "灵植池",
        "圆满回礼",
        "喜好话语",
        "收礼话语",
        "婉拒话语",
        "圆满话语",
        "邀约话语",
        "暂别话语",
    }
    for row in rows:
        if set(row["结交"]) != required or len(row["身份"]["话语"]) != 2:
            raise ValueError(f"{row['编号']}结交内容不完整")
        if len(row["结交"]["收礼话语"]) != 2 or len(row["结交"]["婉拒话语"]) != 2:
            raise ValueError(f"{row['编号']}赠礼话语不完整")
    for label, values in {
        "性格方向": [r["身份"]["性格方向"] for r in rows],
        "说明": [r["说明"] for r in rows],
    }.items():
        duplicates = [value for value, count in Counter(values).items() if count > 1]
        if duplicates:
            raise ValueError(f"{label}存在重复：{duplicates[0]}")
    rewards = {
        (r["结交"]["圆满回礼"]["编号"], r["结交"]["圆满回礼"]["品级"]) for r in rows
    }
    if len(rewards) < 50:
        raise ValueError(f"圆满回礼分布不足：仅{len(rewards)}种")


def _read(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"{path}必须是字典列表")
    return value


def _write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _single(value: Any, label: str) -> str:
    if not isinstance(value, list) or len(value) != 1:
        raise ValueError(f"{label}必须只包含一个资源池")
    return _text(value[0])


def _text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("文本不能为空")
    return text


if __name__ == "__main__":
    main()
