# 晓楠修仙

当前仓库处于战斗底座重构阶段。正式 JSON 是规则与内容的唯一主体，Python 只保留通用基础设施、严格读取、战斗执行和结果展示，不再保留旧玩法服务作为未来实现模板。

## 当前保留范围

```text
data/                       正式定义、规则、内容与展示 JSON
game/core/                  JSON、SQLite、时间等基础能力
game/rules/                 通用战斗核心与战报生成
game/content.py             当前内容视图
game/content_loading.py     JSON 索引、引用和资源池展开
game/cmd/                   具体玩法命令入口（当前为空）
game/public/                控制台、战报等公共服务入口
launch/                     Local、QQ、HTTP 与生命周期适配
message/                    通用消息协议
static/game-console/        控制台前端
static/battle-report/       战报前端
tools/                      游戏外校核、评分、平衡与维护脚本
```

控制台和战报属于基础设施，通过 `game.public` 独立注册。`game.cmd` 以后只注册具体玩法命令。人物、修士、功法装配、地点、闭关、探险、纳戒等旧业务命令与 `game/features` 玩法服务已经移除，后续必须按正式 JSON 契约重新建立。

## JSON 驱动边界

- `data/定义` 声明底层概念、字段和编号规则。
- `data/规则` 声明运行规则和结算顺序。
- `data/内容` 保存可引用的正式实体与资源池。
- `data/展示` 保存战报等展示契约。
- Python 不复制实体正文，不用硬编码替代 JSON 分类、编号、属性、机制或池引用。
- 校核、评分和平衡只在 `tools/` 中运行，不进入游戏进程、存档、抽取和战斗裁定。

功法、附魔、宝石是三个独立内容方向。它们可以组合战斗基石，但不共享一套方向名、随机词条或评分数据。评分仅服务游戏外平衡维护。

## 启动

Windows：

```powershell
cd C:\Users\16841\Desktop\晓楠修仙
start.bat
```

Linux 或 Docker：

```bash
bash start.sh
```

默认服务地址为 `http://127.0.0.1:8845`，天道控制台为 `http://127.0.0.1:8845/game-console`。当前没有可玩的业务命令闭环；入口保留是为了支撑后续重构和基础设施验收。

## 战报演示

战报演示直接使用 JSON 内容、通用战斗核心和参战快照，不依赖人物、敌人或探险服务：

```powershell
python -X utf8 scripts/generate_battle_report_demo.py
```

## 验证

```powershell
python -X utf8 -m compileall -q game launch message scripts tests main.py local.py
python -X utf8 -m unittest discover -s tests
```

测试与工具不得把已移除的业务层重新带回运行链路。
