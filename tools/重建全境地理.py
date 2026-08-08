"""按统一山河骨架重建区域、地形、地点、地势与道路。"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD_ROOT = ROOT / "data" / "内容" / "世界"
ROAD_ROOT = WORLD_ROOT / "道路"
SIZE = 100
SEA_LEVEL = 0
ABYSS_DEPTH = -33333
COAST_BLEND_CELLS = 15


@dataclass(frozen=True)
class Place:
    region: str
    name: str
    xy: tuple[int, int]
    zone: str
    terrain: str
    altitude: int


def place(
    region: str,
    name: str,
    xy: tuple[int, int],
    zone: str,
    terrain: str,
    altitude: int,
) -> Place:
    return Place(region, name, xy, zone, terrain, altitude)


PLACES = (
    place("青岚州", "松风苑", (9, 12), "松风林", "松林", 1200),
    place("青岚州", "溪隐台", (15, 17), "青溪谷", "溪谷", 800),
    place("青岚州", "白石坞", (10, 24), "白石岭", "石岭", 4200),
    place("青岚州", "翠竹苑", (22, 20), "翠竹林", "竹林", 1800),
    place("青岚州", "云水观", (28, 14), "云水雾岭", "云雾山地", 5200),
    place("青岚州", "青溪津", (16, 28), "青溪河谷", "河谷", 500),
    place("青岚州", "落霞台", (30, 26), "落霞丘", "丘陵", 2200),
    place("青岚州", "岚谷坞", (25, 33), "岚谷", "山谷", 2900),
    place("青岚州", "青岚城", (18, 36), "青岚山麓", "山麓", 3200),
    place("丹霞州", "红枫台", (36, 10), "红枫林", "枫林", 1600),
    place("丹霞州", "暖沙洲", (47, 8), "暖沙地", "沙地", 120),
    place("丹霞州", "朱果苑", (59, 12), "朱果林", "林地", 1000),
    place("丹霞州", "石泉涧", (41, 18), "石泉岩地", "岩地", 3300),
    place("丹霞州", "鹤栖台", (53, 22), "鹤栖河谷", "河谷", 900),
    place("丹霞州", "炉烟坊", (64, 17), "炉烟火坡", "火山坡", 7200),
    place("丹霞州", "赤岩坊", (42, 28), "赤岩丹崖", "丹崖", 9800),
    place("丹霞州", "丹泉苑", (60, 30), "丹泉谷地", "温泉谷地", 1800),
    place("丹霞州", "丹霞城", (51, 35), "丹霞丘陵", "丘陵", 3800),
    place("镜湖州", "水月汀", (69, 11), "水月湖湾", "湖湾", 80),
    place("镜湖州", "银沙洲", (80, 8), "银沙洲", "沙洲", 35),
    place("镜湖州", "雁回汀", (92, 12), "雁回河口", "河口", 60),
    place("镜湖州", "芦汀洲", (72, 19), "芦汀湿地", "芦苇湿地", 15),
    place("镜湖州", "莲舟渡", (84, 17), "莲舟湖汊", "湖汊", 40),
    place("镜湖州", "清漪台", (95, 23), "清漪水网", "水网平原", 90),
    place("镜湖州", "澄波埠", (76, 28), "澄波湖滨", "湖滨", 180),
    place("镜湖州", "荷风洲", (91, 30), "荷风湿地", "湿地", 20),
    place("镜湖州", "镜湖城", (84, 36), "镜湖城滨", "湖滨", 240),
    place("云京州", "望云台", (7, 38), "望云高地", "高地", 4800),
    place("云京州", "鹤鸣台", (14, 41), "鹤鸣丘陵", "丘陵", 2600),
    place("云京州", "雨花苑", (27, 37), "雨花谷地", "谷地", 1500),
    place("云京州", "星落原", (9, 47), "星落原野", "原野", 1100),
    place("云京州", "桥西渡", (20, 45), "桥西河谷", "河谷", 850),
    place("云京州", "风栖台", (31, 43), "长风谷", "风谷", 3000),
    place("云京州", "飞云驿", (12, 52), "飞云山麓", "山麓", 6200),
    place("云京州", "栖霞台", (29, 50), "栖霞云岭", "云岭", 9300),
    place("云京州", "铜雀台", (24, 55), "铜雀孤峰", "高地", 7800),
    place("云京州", "云京城", (18, 53), "云京盆地", "山间盆地", 3600),
    place("天衡州", "平川原", (36, 38), "平川原", "平原", 480),
    place("天衡州", "玉泉涧", (46, 40), "玉泉谷", "泉谷", 1200),
    place("天衡州", "青禾原", (61, 37), "青禾沃野", "沃野", 420),
    place("天衡州", "灵田苑", (39, 46), "灵田沃野", "沃野", 650),
    place("天衡州", "古槐台", (52, 45), "古槐林", "林地", 1500),
    place("天衡州", "朝阳台", (64, 44), "朝阳平原", "平原", 800),
    place("天衡州", "归元观", (42, 53), "归元丘陵", "丘陵", 2600),
    place("天衡州", "太素坊", (60, 52), "太素河谷", "河谷", 1100),
    place("天衡州", "天衡城", (51, 55), "天衡高地", "高地", 4200),
    place("玄河州", "河湾洲", (68, 38), "河湾", "河湾", 80),
    place("玄河州", "柳堤渡", (78, 36), "柳堤", "河堤", 120),
    place("玄河州", "沧浪洲", (92, 39), "沧浪河口", "河口", 20),
    place("玄河州", "渔火津", (72, 45), "渔火沙洲", "沙洲", 30),
    place("玄河州", "白帆渡", (85, 43), "白帆江岸", "江岸", 60),
    place("玄河州", "水门埠", (95, 47), "水门水网", "水网平原", 15),
    place("玄河州", "临江埠", (75, 52), "临江岸", "江岸", 180),
    place("玄河州", "玄渡津", (90, 54), "玄渡河谷", "河谷", 600),
    place("玄河州", "玄河城", (83, 53), "玄河冲积原", "冲积平原", 520),
    place("镇岳防线", "铁壁军镇", (10, 60), "铁壁荒丘", "荒丘", 4800),
    place("镇岳防线", "西极关", (6, 66), "西极峡谷", "峡谷", 7600),
    place("镇岳防线", "烽火军镇", (25, 60), "烽火丘陵", "丘陵", 4200),
    place("镇岳防线", "苍狼关", (18, 67), "苍狼草原", "草原", 3200),
    place("镇岳防线", "玄甲军镇", (40, 58), "玄甲山麓", "山麓", 6200),
    place("镇岳防线", "雁门关", (31, 69), "雁门山口", "山口", 9200),
    place("镇岳防线", "龙脊关", (46, 70), "龙脊山脊", "山脊", 14800),
    place("镇岳防线", "镇北军镇", (58, 59), "镇北高原", "高原", 7800),
    place("镇岳防线", "镇岳关", (55, 67), "镇岳山口", "山口", 10400),
    place("镇岳防线", "破虏军镇", (73, 58), "破虏河谷", "河谷", 3200),
    place("镇岳防线", "断云关", (68, 68), "断云山脊", "山脊", 13200),
    place("镇岳防线", "玄河关", (82, 66), "玄河关谷", "河谷", 2800),
    place("镇岳防线", "定远军镇", (90, 59), "定远平原", "平原", 1800),
    place("镇岳防线", "东海关", (94, 65), "东海岸", "海岸", 100),
    place("朔风荒原", "朔风原", (12, 75), "朔风原", "草原", 1800),
    place("朔风荒原", "风蚀谷", (29, 80), "风蚀谷", "峡谷", 4200),
    place("朔风荒原", "枯草甸", (44, 83), "枯草甸", "草甸", 2500),
    place("寒渊林海", "寒雾林", (57, 75), "寒雾林", "寒林", 3800),
    place("寒渊林海", "冰泉谷", (74, 81), "冰泉谷", "冰谷", 5600),
    place("寒渊林海", "沉木泽", (90, 78), "沉木泽", "寒沼", 150),
    place("烬脊群山", "黑石岭", (11, 90), "黑石岭", "黑岩山岭", 16500),
    place("烬脊群山", "熔痕谷", (30, 94), "熔痕谷", "熔岩谷", 13800),
    place("烬脊群山", "灰烬峰", (47, 97), "灰烬群峰", "火山", 23000),
    place("天裂禁地", "裂天原", (58, 89), "裂天原", "裂隙荒原", 14500),
    place("天裂禁地", "寂雷谷", (77, 94), "寂雷谷", "雷谷", 17700),
    place("天裂禁地", "无光崖", (93, 97), "无光绝岭", "断崖", 28710),
)


REGION_META = {
    "青岚州": (
        "州",
        "青溪水脉穿过西南群岭，松林、竹海和云雾山地围住青岚城与诸处山坞。",
    ),
    "丹霞州": (
        "州",
        "南境丹崖与温泉谷地沿地火脉舒展，赤岩、林苑和炉坊散落在高低错落的山口间。",
    ),
    "镜湖州": (
        "州",
        "镜湖与东南海潮相接，湖汊、沙洲、湿地和河口共同织成水路密集的泽国。",
    ),
    "云京州": (
        "州",
        "西部云岭向镇岳山系抬升，山间盆地、河谷和飞舟古驿组成南北往来的门户。",
    ),
    "天衡州": (
        "州",
        "六州腹地由沃野、泉谷与丘陵交错构成，天衡城据高地统摄向四方伸展的商路。",
    ),
    "玄河州": (
        "州",
        "玄河自镇岳山口奔向东南水网，沿途分出江岸、沙洲、河湾与广阔冲积平原。",
    ),
    "镇岳防线": (
        "防线",
        "防线顺镇岳山系与玄河峡口曲折延展，关隘占据鞍部，军镇列于南坡补给线。",
    ),
    "朔风荒原": (
        "荒野",
        "西北高原在封界群山前逐渐开阔，草原、风蚀峡谷和枯草甸承受终年朔风。",
    ),
    "寒渊林海": (
        "荒野",
        "东北寒林随玄河上游起伏，冰泉谷与沉木寒沼把林海切成彼此隔绝的幽暗地带。",
    ),
    "烬脊群山": (
        "荒野",
        "西北封界山群由黑岩断脊、熔岩谷和灰烬火山接续而成，峰线向天裂禁地合拢。",
    ),
    "天裂禁地": (
        "荒野",
        "东北绝岭被天裂、雷谷和无光断崖撕开，群峰高过云层并封住全境北端。",
    ),
}


ROAD_LINKS = {
    "官道": (
        ("青溪津", "青岚城"),
        ("青岚城", "岚谷坞"),
        ("赤岩坊", "丹霞城"),
        ("丹泉苑", "丹霞城"),
        ("鹤栖台", "丹霞城"),
        ("飞云驿", "云京城"),
        ("桥西渡", "云京城"),
        ("栖霞台", "云京城"),
        ("归元观", "天衡城"),
        ("太素坊", "天衡城"),
        ("古槐台", "天衡城"),
        ("归元观", "平川原"),
        ("太素坊", "青禾原"),
        ("镜湖城", "玄河城"),
        ("玄渡津", "玄河城"),
        ("青岚城", "云京城"),
        ("青岚城", "丹霞城"),
        ("丹霞城", "天衡城"),
        ("丹霞城", "镜湖城"),
        ("云京城", "天衡城"),
        ("天衡城", "玄河城"),
        ("云京城", "铁壁军镇"),
        ("天衡城", "镇北军镇"),
        ("玄河城", "定远军镇"),
    ),
    "乡道": (
        ("松风苑", "溪隐台"),
        ("溪隐台", "翠竹苑"),
        ("白石坞", "翠竹苑"),
        ("溪隐台", "青溪津"),
        ("翠竹苑", "岚谷坞"),
        ("落霞台", "岚谷坞"),
        ("红枫台", "暖沙洲"),
        ("暖沙洲", "石泉涧"),
        ("朱果苑", "鹤栖台"),
        ("鹤栖台", "丹泉苑"),
        ("望云台", "鹤鸣台"),
        ("鹤鸣台", "星落原"),
        ("星落原", "桥西渡"),
        ("桥西渡", "雨花苑"),
        ("雨花苑", "风栖台"),
        ("平川原", "灵田苑"),
        ("灵田苑", "古槐台"),
        ("玉泉涧", "古槐台"),
        ("古槐台", "朝阳台"),
        ("朝阳台", "青禾原"),
    ),
    "山道": (
        ("白石坞", "青岚城"),
        ("云水观", "岚谷坞"),
        ("石泉涧", "赤岩坊"),
        ("炉烟坊", "赤岩坊"),
        ("望云台", "飞云驿"),
        ("风栖台", "栖霞台"),
        ("栖霞台", "铜雀台"),
        ("栖霞台", "玄甲军镇"),
        ("黑石岭", "熔痕谷"),
        ("熔痕谷", "灰烬峰"),
        ("裂天原", "寂雷谷"),
        ("寂雷谷", "无光崖"),
    ),
    "堤道": (
        ("水月汀", "芦汀洲"),
        ("水月汀", "银沙洲"),
        ("银沙洲", "莲舟渡"),
        ("银沙洲", "雁回汀"),
        ("芦汀洲", "澄波埠"),
        ("莲舟渡", "镜湖城"),
        ("澄波埠", "镜湖城"),
        ("雁回汀", "荷风洲"),
        ("清漪台", "荷风洲"),
        ("荷风洲", "镜湖城"),
        ("河湾洲", "柳堤渡"),
        ("河湾洲", "渔火津"),
        ("柳堤渡", "白帆渡"),
        ("白帆渡", "沧浪洲"),
        ("沧浪洲", "水门埠"),
        ("渔火津", "临江埠"),
        ("白帆渡", "临江埠"),
        ("水门埠", "玄渡津"),
        ("临江埠", "玄河城"),
    ),
    "军道": (
        ("铁壁军镇", "烽火军镇"),
        ("烽火军镇", "玄甲军镇"),
        ("玄甲军镇", "镇北军镇"),
        ("镇北军镇", "破虏军镇"),
        ("破虏军镇", "定远军镇"),
        ("铁壁军镇", "西极关"),
        ("铁壁军镇", "苍狼关"),
        ("烽火军镇", "苍狼关"),
        ("烽火军镇", "雁门关"),
        ("玄甲军镇", "雁门关"),
        ("玄甲军镇", "龙脊关"),
        ("镇北军镇", "龙脊关"),
        ("镇北军镇", "镇岳关"),
        ("破虏军镇", "断云关"),
        ("破虏军镇", "玄河关"),
        ("定远军镇", "玄河关"),
        ("定远军镇", "东海关"),
        ("西极关", "苍狼关"),
        ("苍狼关", "雁门关"),
        ("雁门关", "龙脊关"),
        ("龙脊关", "镇岳关"),
        ("镇岳关", "断云关"),
        ("断云关", "玄河关"),
        ("玄河关", "东海关"),
    ),
    "荒径": (
        ("西极关", "朔风原"),
        ("苍狼关", "朔风原"),
        ("雁门关", "风蚀谷"),
        ("龙脊关", "风蚀谷"),
        ("镇岳关", "枯草甸"),
        ("断云关", "寒雾林"),
        ("玄河关", "冰泉谷"),
        ("东海关", "沉木泽"),
        ("朔风原", "风蚀谷"),
        ("风蚀谷", "枯草甸"),
        ("寒雾林", "冰泉谷"),
        ("冰泉谷", "沉木泽"),
        ("朔风原", "黑石岭"),
        ("寒雾林", "裂天原"),
        ("灰烬峰", "裂天原"),
    ),
    "栈道": (
        ("风蚀谷", "熔痕谷"),
        ("枯草甸", "灰烬峰"),
        ("冰泉谷", "寂雷谷"),
        ("沉木泽", "无光崖"),
    ),
}


def stable_phase(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 2**32 * math.tau


def warped(x: int, y: int) -> tuple[float, float]:
    return (
        x + 2.5 * math.sin(y / 8.2) + 1.1 * math.sin((x + y) / 13.7),
        y + 2.1 * math.sin(x / 9.4) + 0.9 * math.sin((x - y) / 11.3),
    )


WARPED_PLACES = {item.name: warped(*item.xy) for item in PLACES}


def defense_south(x: int) -> int:
    return round(57 + 2 * math.sin((x + 5) / 17) + math.sin(x / 9))


def defense_north(x: int) -> int:
    return round(72 + 2.1 * math.sin((x - 10) / 14) + math.sin(x / 6))


def northern_ridge_south(x: int) -> int:
    return round(86 + 2 * math.sin((x + 3) / 12) + 1.2 * math.sin(x / 5))


def northern_divide(y: int) -> int:
    return round(50 + 4 * math.sin(y / 9) + 2 * math.sin(y / 3.7))


SOUTHERN_REGIONS = (
    "青岚州",
    "丹霞州",
    "镜湖州",
    "云京州",
    "天衡州",
    "玄河州",
)


def nearest_southern_region(x: int, y: int) -> str:
    wx, wy = warped(x, y)
    scores: dict[str, float] = {}
    for region in SOUTHERN_REGIONS:
        distances = []
        for item in PLACES:
            if item.region != region:
                continue
            sx, sy = WARPED_PLACES[item.name]
            distances.append((wx - sx) ** 2 + ((wy - sy) * 1.08) ** 2)
        phase = stable_phase(region)
        scores[region] = min(distances) * (
            1 + 0.035 * math.sin(x / 8.5 + phase) + 0.025 * math.cos(y / 7.2 - phase)
        )
    return min(scores, key=scores.__getitem__)


def build_region_grid() -> list[list[str]]:
    grid: list[list[str]] = []
    for y in range(SIZE):
        row: list[str] = []
        for x in range(SIZE):
            if y < defense_south(x):
                region = nearest_southern_region(x, y)
            elif y <= defense_north(x):
                region = "镇岳防线"
            elif y < northern_ridge_south(x):
                region = "朔风荒原" if x < northern_divide(y) else "寒渊林海"
            else:
                region = "烬脊群山" if x < northern_divide(y) else "天裂禁地"
            row.append(region)
        grid.append(row)
    return grid


def south_coast(x: int) -> float:
    return 4.8 + 1.7 * math.sin((x + 9) / 9.5) + 1.1 * math.sin(x / 3.9)


def west_coast(y: int) -> float:
    return 3.6 + 1.8 * math.sin((y + 4) / 10.5) + 0.9 * math.sin(y / 4.3)


def east_coast(y: int) -> float:
    return 96.0 - 1.7 * math.sin((y + 8) / 11.2) - 0.9 * math.sin(y / 4.8)


def is_land(x: int, y: int) -> bool:
    if y < south_coast(x):
        return False
    if y <= 89 and x < west_coast(y):
        return False
    return not (y <= 89 and x > east_coast(y))


def is_abyss(x: int, y: int) -> bool:
    return ((x - 101) / 19) ** 2 + ((y + 2) / 16) ** 2 <= 1


def sea_zone(x: int, y: int) -> str:
    if is_abyss(x, y):
        return "东南天渊"
    if y < south_coast(x):
        return "南溟外海"
    if x < west_coast(y):
        return "西溟外海"
    return "东溟外海"


def build_zone_grid() -> list[list[str]]:
    grid = [
        ["" if is_land(x, y) else sea_zone(x, y) for x in range(SIZE)]
        for y in range(SIZE)
    ]
    costs = [[math.inf for _ in range(SIZE)] for _ in range(SIZE)]
    queue: list[tuple[float, int, str, int, int]] = []
    counter = 0
    for item in PLACES:
        x, y = item.xy
        costs[y][x] = 0
        grid[y][x] = item.zone
        heapq.heappush(queue, (0, counter, item.zone, x, y))
        counter += 1
    while queue:
        current_cost, _, zone, x, y = heapq.heappop(queue)
        if current_cost != costs[y][x] or grid[y][x] != zone:
            continue
        phase = stable_phase(zone)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < SIZE and 0 <= ny < SIZE and is_land(nx, ny)):
                continue
            step = (
                1
                + 0.16 * math.sin(nx / 6.2 + phase)
                + 0.12 * math.cos(ny / 7.1 - phase)
                + 0.06 * math.sin((nx + ny) / 4.9 + phase / 2)
            )
            candidate = current_cost + step
            if candidate >= costs[ny][nx]:
                continue
            costs[ny][nx] = candidate
            grid[ny][nx] = zone
            heapq.heappush(queue, (candidate, counter, zone, nx, ny))
            counter += 1
    if any(is_land(x, y) and not grid[y][x] for y in range(SIZE) for x in range(SIZE)):
        raise RuntimeError("存在未归入地形分区的陆地")
    return grid


def point_segment_distance(
    x: float,
    y: float,
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    ax, ay = start
    bx, by = end
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return math.hypot(x - ax, y - ay)
    ratio = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (ax + ratio * dx), y - (ay + ratio * dy))


def polyline_distance(
    x: float, y: float, points: tuple[tuple[float, float], ...]
) -> float:
    return min(
        point_segment_distance(x, y, left, right) for left, right in pairwise(points)
    )


def smoothstep(value: float) -> float:
    ratio = max(0.0, min(1.0, value))
    return ratio * ratio * (3 - 2 * ratio)


def local_target_height(x: int, y: int) -> float:
    weights = []
    for item in PLACES:
        distance2 = (x - item.xy[0]) ** 2 + (y - item.xy[1]) ** 2
        weight = 1 / (distance2 + 12) ** 1.18
        weights.append((weight, item.altitude))
    total = sum(weight for weight, _ in weights)
    return sum(weight * altitude for weight, altitude in weights) / total


def chamfer_distance(mask: list[list[bool]]) -> list[list[float]]:
    distance = [[math.inf for _ in range(SIZE)] for _ in range(SIZE)]
    queue: list[tuple[float, int, int]] = []
    for y in range(SIZE):
        for x in range(SIZE):
            if mask[y][x]:
                distance[y][x] = 0
                heapq.heappush(queue, (0, x, y))
    while queue:
        current, x, y = heapq.heappop(queue)
        if current != distance[y][x]:
            continue
        for dx, dy in NEIGHBORS:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < SIZE and 0 <= ny < SIZE):
                continue
            candidate = current + (math.sqrt(2) if dx and dy else 1)
            if candidate < distance[ny][nx]:
                distance[ny][nx] = candidate
                heapq.heappush(queue, (candidate, nx, ny))
    return distance


def blur_land(values: list[list[float]], land: list[list[bool]]) -> list[list[float]]:
    current = values
    for _ in range(2):
        output = [row[:] for row in current]
        for y in range(SIZE):
            for x in range(SIZE):
                if not land[y][x]:
                    continue
                weighted_total = current[y][x] * 4
                total_weight = 4
                for dx, dy in NEIGHBORS:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < SIZE and 0 <= ny < SIZE and land[ny][nx]:
                        weighted_total += current[ny][nx]
                        total_weight += 1
                output[y][x] = weighted_total / total_weight
        current = output
    return current


def build_surface() -> list[list[int]]:
    land = [[is_land(x, y) for x in range(SIZE)] for y in range(SIZE)]
    coast_distance = chamfer_distance([[not value for value in row] for row in land])
    defense_line = tuple(
        (x, 64 + 2.6 * math.sin((x - 7) / 13)) for x in range(0, SIZE, 4)
    )
    qinglan_ridge = ((5, 30), (13, 36), (23, 34), (31, 25), (30, 14))
    danxia_ridge = ((34, 29), (43, 35), (54, 33), (65, 21))
    yunjing_ridge = ((4, 49), (14, 56), (25, 55), (33, 47))
    xuan_river = (
        (61, 72),
        (67, 63),
        (72, 54),
        (76, 47),
        (82, 39),
        (88, 30),
        (94, 21),
        (97, 12),
    )
    qingxi = ((29, 49), (24, 39), (16, 28), (15, 17), (10, 8))
    central_river = ((52, 58), (53, 49), (50, 40), (53, 31), (58, 21), (61, 11))
    values = [[0.0 for _ in range(SIZE)] for _ in range(SIZE)]
    for y in range(SIZE):
        for x in range(SIZE):
            if not land[y][x]:
                depth = 280 + 520 * max(0, 5 - coast_distance[y][x])
                if x < west_coast(y):
                    depth += (west_coast(y) - x) ** 1.65 * 330
                if x > east_coast(y):
                    depth += (x - east_coast(y)) ** 1.65 * 330
                if y < south_coast(x):
                    depth += (south_coast(x) - y) ** 1.65 * 360
                if is_abyss(x, y):
                    radius = math.sqrt(((x - 101) / 19) ** 2 + ((y + 2) / 16) ** 2)
                    depth = max(depth, 4200 + (1 - radius) * (abs(ABYSS_DEPTH) - 4200))
                values[y][x] = -min(abs(ABYSS_DEPTH), depth)
                continue

            value = local_target_height(x, y)
            value += 260 * math.sin(x / 5.7) + 210 * math.sin((x + y) / 8.9)
            value += 150 * math.cos(y / 4.8) + 110 * math.sin((2 * x - y) / 11.2)
            value += 2300 * math.exp(-(polyline_distance(x, y, defense_line) ** 2) / 18)
            value += 1300 * math.exp(
                -(polyline_distance(x, y, qinglan_ridge) ** 2) / 22
            )
            value += 1700 * math.exp(-(polyline_distance(x, y, danxia_ridge) ** 2) / 18)
            value += 1400 * math.exp(
                -(polyline_distance(x, y, yunjing_ridge) ** 2) / 20
            )
            value -= 1100 * math.exp(-(polyline_distance(x, y, xuan_river) ** 2) / 8)
            value -= 650 * math.exp(-(polyline_distance(x, y, qingxi) ** 2) / 7)
            value -= 700 * math.exp(-(polyline_distance(x, y, central_river) ** 2) / 8)
            lake = ((x - 83) / 17) ** 2 + ((y - 22) / 13) ** 2
            if lake < 1.6:
                value -= (1.6 - lake) * 700
            north = smoothstep((y - northern_ridge_south(x) + 2) / 11)
            value += north * (900 + 700 * math.sin(x / 7.5) ** 2)
            coast = smoothstep(coast_distance[y][x] / COAST_BLEND_CELLS)
            values[y][x] = 20 + max(0, value) * coast

    values = blur_land(values, land)

    anchor_deltas = tuple(
        (item.xy[0], item.xy[1], item.altitude - values[item.xy[1]][item.xy[0]])
        for item in PLACES
    )
    anchored = [row[:] for row in values]
    for y in range(SIZE):
        for x in range(SIZE):
            if not land[y][x]:
                continue
            weighted_delta = 0.0
            total_weight = 0.0
            for anchor_x, anchor_y, delta in anchor_deltas:
                distance2 = (x - anchor_x) ** 2 + (y - anchor_y) ** 2
                if distance2 > 64:
                    continue
                weight = math.exp(-distance2 / 14)
                weighted_delta += delta * weight
                total_weight += weight
            if total_weight:
                anchored[y][x] += weighted_delta / max(1.0, total_weight)
    values = anchored

    for y in range(SIZE):
        for x in range(SIZE):
            if not land[y][x]:
                continue
            ridge_start = northern_ridge_south(x) - 5
            ridge_progress = smoothstep((y - ridge_start) / max(1, 99 - ridge_start))
            if ridge_progress:
                ridge_floor = ridge_progress * (
                    15500
                    + 2600 * math.sin((x + 4) / 9) ** 2
                    + 900 * math.sin((x - 11) / 4.7) ** 2
                )
                values[y][x] = max(values[y][x], ridge_floor)

    for item in PLACES:
        values[item.xy[1]][item.xy[0]] = item.altitude

    result = [
        [max(ABYSS_DEPTH, min(28710, round(value))) for value in row] for row in values
    ]
    result[0][99] = ABYSS_DEPTH
    dark = next(item for item in PLACES if item.name == "无光崖")
    result[dark.xy[1]][dark.xy[0]] = 28710
    return result


NEIGHBORS = (
    (-1, -1),
    (0, -1),
    (1, -1),
    (-1, 0),
    (1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
)


def astar(
    start: tuple[int, int],
    end: tuple[int, int],
    road_type: str,
    surface: list[list[int]],
    claimed_edges: dict[tuple[tuple[int, int], tuple[int, int]], str],
    blocked_locations: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    queue: list[tuple[float, float, int, tuple[int, int]]] = []
    counter = 0
    heapq.heappush(queue, (0.0, 0.0, counter, start))
    cost = {start: 0.0}
    previous: dict[tuple[int, int], tuple[int, int]] = {}
    while queue:
        _, current_cost, _, current = heapq.heappop(queue)
        if current_cost != cost.get(current):
            continue
        if current == end:
            break
        x, y = current
        for dx, dy in NEIGHBORS:
            neighbor = (x + dx, y + dy)
            nx, ny = neighbor
            if not (0 <= nx < SIZE and 0 <= ny < SIZE):
                continue
            if neighbor in blocked_locations:
                continue
            edge = canonical_edge(current, neighbor)
            owner = claimed_edges.get(edge)
            if owner is not None and owner != road_type:
                continue
            altitude = surface[ny][nx]
            if altitude < 0 and not (road_type == "堤道" and altitude >= -180):
                continue
            diagonal = math.sqrt(2) if dx and dy else 1
            rise = abs(surface[ny][nx] - surface[y][x])
            slope_scale = {
                "官道": 520,
                "乡道": 650,
                "堤道": 700,
                "军道": 620,
                "山道": 1050,
                "荒径": 950,
                "栈道": 1500,
            }[road_type]
            step = diagonal * (1 + (rise / slope_scale) ** 1.45)
            if road_type == "堤道":
                step *= 0.72 + min(1.2, abs(altitude) / 1800)
            if road_type == "军道":
                ridge = abs(ny - (64 + 2.6 * math.sin((nx - 7) / 13)))
                step *= 0.88 + min(0.7, ridge / 18)
            if owner == road_type:
                step *= 0.42
            candidate = current_cost + step
            if candidate >= cost.get(neighbor, math.inf):
                continue
            cost[neighbor] = candidate
            previous[neighbor] = current
            counter += 1
            heuristic = math.hypot(end[0] - nx, end[1] - ny) * 0.85
            heapq.heappush(queue, (candidate + heuristic, candidate, counter, neighbor))
    if end not in cost:
        raise RuntimeError(f"道路无法生成：{road_type} {start} -> {end}")
    path = [end]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    return path


def canonical_edge(
    left: tuple[int, int], right: tuple[int, int]
) -> tuple[tuple[int, int], tuple[int, int]]:
    return (left, right) if left <= right else (right, left)


def build_roads(surface: list[list[int]]) -> dict[str, list[dict[str, Any]]]:
    locations = {item.name: item.xy for item in PLACES}
    output: dict[str, list[dict[str, Any]]] = {name: [] for name in ROAD_LINKS}
    claimed_edges: dict[tuple[tuple[int, int], tuple[int, int]], str] = {}
    all_pairs: set[frozenset[str]] = set()
    for road_type, links in ROAD_LINKS.items():
        for start_name, end_name in links:
            pair = frozenset((start_name, end_name))
            if pair in all_pairs:
                raise ValueError(f"道路端点重复：{start_name} <-> {end_name}")
            all_pairs.add(pair)
            path = astar(
                locations[start_name],
                locations[end_name],
                road_type,
                surface,
                claimed_edges,
                set(locations.values()) - {locations[start_name], locations[end_name]},
            )
            for left, right in pairwise(path):
                edge = canonical_edge(left, right)
                owner = claimed_edges.setdefault(edge, road_type)
                if owner != road_type:
                    raise ValueError(f"道路边类型冲突：{edge} -> {owner}/{road_type}")
            output[road_type].append(
                {
                    "起点": start_name,
                    "终点": end_name,
                    "途经坐标": [list(point) for point in path],
                }
            )
    return output


def spans_for(grid: list[list[str]], name: str) -> list[dict[str, Any]]:
    result = []
    for y, row in enumerate(grid):
        ranges = []
        start: int | None = None
        for x in range(SIZE + 1):
            matches = x < SIZE and row[x] == name
            if matches and start is None:
                start = x
            elif not matches and start is not None:
                ranges.append([start, x - 1])
                start = None
        if ranges:
            result.append({"y": y, "x轴": ranges})
    return result


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def location_file(item: Place) -> Path:
    return WORLD_ROOT / item.region / item.name / f"{item.name}.json"


def validate_plan(region_grid: list[list[str]], zone_grid: list[list[str]]) -> None:
    if len(PLACES) != 81:
        raise ValueError(f"地点规划必须保持81处，当前{len(PLACES)}处")
    names = [item.name for item in PLACES]
    points = [item.xy for item in PLACES]
    zones = [item.zone for item in PLACES]
    if len(set(names)) != len(names) or len(set(points)) != len(points):
        raise ValueError("地点名称或坐标重复")
    if len(set(zones)) != len(zones):
        raise ValueError("地点地形分区名称重复")
    for item in PLACES:
        x, y = item.xy
        if not location_file(item).is_file():
            raise FileNotFoundError(f"地点主体不存在：{item.region}/{item.name}")
        if not is_land(x, y):
            raise ValueError(f"地点落入外海：{item.name} {item.xy}")
        if region_grid[y][x] != item.region:
            raise ValueError(
                f"地点州域错误：{item.name} {item.region} != {region_grid[y][x]}"
            )
        if zone_grid[y][x] != item.zone:
            raise ValueError(f"地点地形分区错误：{item.name} -> {zone_grid[y][x]}")
    for region in REGION_META:
        if not connected_cells(region_grid, region):
            raise ValueError(f"州域不连通：{region}")


def connected_cells(grid: list[list[str]], name: str) -> bool:
    cells = {
        (x, y)
        for y, row in enumerate(grid)
        for x, value in enumerate(row)
        if value == name
    }
    if not cells:
        return False
    reached = set()
    queue = deque([next(iter(cells))])
    while queue:
        current = queue.popleft()
        if current in reached:
            continue
        reached.add(current)
        x, y = current
        queue.extend(
            (nx, ny)
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            if (nx, ny) in cells and (nx, ny) not in reached
        )
    return reached == cells


def road_graph_is_connected(roads: dict[str, list[dict[str, Any]]]) -> bool:
    graph: dict[str, set[str]] = defaultdict(set)
    for rows in roads.values():
        for row in rows:
            graph[row["起点"]].add(row["终点"])
            graph[row["终点"]].add(row["起点"])
    reached = set()
    queue = deque(["溪隐台"])
    while queue:
        current = queue.popleft()
        if current in reached:
            continue
        reached.add(current)
        queue.extend(graph[current] - reached)
    return reached == {item.name for item in PLACES}


def rewrite_world() -> None:
    region_grid = build_region_grid()
    zone_grid = build_zone_grid()
    validate_plan(region_grid, zone_grid)
    surface = build_surface()
    roads = build_roads(surface)
    if not road_graph_is_connected(roads):
        raise ValueError("新道路网络未覆盖全部地点")

    for item in PLACES:
        path = location_file(item)
        body = json.loads(path.read_text(encoding="utf-8"))
        body["坐标"] = list(item.xy)
        write_json(path, body)

    for region, (category, description) in REGION_META.items():
        write_json(
            WORLD_ROOT / region / f"{region}.json",
            {
                "类别": category,
                "坐标带": spans_for(region_grid, region),
                "说明": description,
            },
        )

    terrain_by_zone = {item.zone: item.terrain for item in PLACES}
    terrain_by_zone.update(
        {
            "西溟外海": "海岸",
            "南溟外海": "海岸",
            "东溟外海": "海岸",
            "东南天渊": "海岸",
        }
    )
    terrain_zones = [
        {
            "名称": zone,
            "地形": terrain_by_zone[zone],
            "坐标带": spans_for(zone_grid, zone),
        }
        for zone in sorted(terrain_by_zone)
    ]
    write_json(WORLD_ROOT / "地形分区.json", terrain_zones)

    write_json(
        WORLD_ROOT / "地势.json",
        {
            "分辨率": 1,
            "高度单位": "米",
            "海平面": SEA_LEVEL,
            "坐标边界": {"x轴": [0, 99], "y轴": [0, 99]},
            "海拔范围": [min(map(min, surface)), max(map(max, surface))],
            "水平每格米数": 10000,
            "地表高度": surface,
        },
    )

    for road_type, rows in roads.items():
        write_json(ROAD_ROOT / f"{road_type}.json", rows)

    world_path = WORLD_ROOT / "晓楠修仙界.json"
    world = json.loads(world_path.read_text(encoding="utf-8"))
    world["说明"] = (
        "晓楠修仙界以镇岳山系横分南北：南方六州沿青溪、玄河与镜湖繁衍，"
        "北境荒原和寒林一直抬升到封界群山；东、西、南三面入海，东南外海坠入天渊。"
    )
    write_json(world_path, world)

    road_count = sum(len(rows) for rows in roads.values())
    print(
        f"全境地理已重建：{len(REGION_META)}个区域、{len(terrain_zones)}片地形、"
        f"{len(PLACES)}个地点、{road_count}条道路。"
    )


def main() -> int:
    rewrite_world()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
