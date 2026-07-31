# 晓楠修仙

当前仓库处于战斗底座重构阶段。正式 JSON 是规则与内容的唯一主体，Python 只保留通用基础设施、严格读取、战斗执行和结果展示，不再保留旧玩法服务作为未来实现模板。

## 当前保留范围

```text
data/                       正式定义、规则、内容与展示 JSON
game/core/                  JSON、SQLite、时间等基础能力
game/core/data/             第一个核心微服务：正式 JSON 只读快照与索引
game/core/combat/           第二个核心微服务：行动条、CD、事件与战报
game/core/pool/             第三个核心微服务：资源池展开与逆权重抽取
game/app.py                 游戏微服务的唯一组合根
game/features/              不依赖命令协议的具体玩法微服务
game/cmd/                   具体玩法命令总入口
game/cmd/public/            控制台、战报等公共入口
launch/                     Local、QQ、HTTP 与生命周期适配
message/                    通用消息协议
static/game-console/        控制台前端
static/battle-report/       战报前端
tools/                      游戏外校核、评分、平衡与维护脚本
```

控制台和战报属于公共入口，放在 `game/cmd/public`，由 `game.cmd` 与以后重建的具体玩法命令统一挂载。`game/core` 放全局基础微服务，`game/features` 放具体玩法微服务，`game/cmd` 只负责命令、按钮和 HTTP 触发，`game/app.py` 是唯一组合根。人物、修士、功法装配、地点、闭关、探险、纳戒等旧业务实现仍未恢复，后续必须按正式 JSON 契约逐个建立。

## JSON 驱动边界

- `data/定义` 声明底层概念、字段和编号规则。
- `data/规则` 声明运行规则和结算顺序。
- `data/内容` 保存可引用的正式实体与资源池。
- `data/展示` 保存战报等展示契约。
- Python 不复制实体正文，不用硬编码替代 JSON 分类、编号、属性、机制或池引用。
- JSON 读取是 `core` 的第一个微服务；后续 `features` 微服务由 `game/app.py` 注入该依赖，`cmd` 通过 `current_game_services()` 触发服务。
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

当前地基不保留旧测试目录；验收使用编译、真实数据启动和战斗微服务最小实战调用。游戏进程不加载 `tools`，也不执行游戏外评分、校核和平衡脚本。
