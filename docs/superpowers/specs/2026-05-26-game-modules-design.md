# iFlyCompass 联机小游戏模块设计文档

**版本**: REL2.6.0  
**日期**: 2026-05-26  
**设计目标**: 为 iFlyCompass 添加斗地主、象棋、五子棋三个联机小游戏，支持房间内消息聊天与战绩统计

---

## 1. 架构方案

采用 **方案 B：每个游戏独立大厅 + 独立模块**，完全参照现有 Flask Blueprint 模块化架构（`modules/chat/`、`modules/md/` 等）。

每个游戏有独立的 Blueprint、API、Socket.IO namespace、模板、前端脚本。房间管理和游戏逻辑完全隔离，避免不同游戏状态机差异导致的耦合问题。

---

## 2. 模块与文件结构

### 后端模块

```
modules/
├── game_doudizhu/          # 斗地主
│   ├── __init__.py         # Blueprint 注册 + Socket.IO namespace
│   ├── routes.py           # 页面路由 (/games/doudizhu, /games/doudizhu/room/<id>)
│   ├── api.py              # REST API (创建/加入/退出/获取房间列表/战绩)
│   └── websocket.py        # Socket.IO 事件处理
├── game_chess/             # 象棋
│   ├── __init__.py
│   ├── routes.py
│   ├── api.py
│   └── websocket.py        # Socket.IO 事件 + 走法验证
├── game_gomoku/            # 五子棋
│   ├── __init__.py
│   ├── routes.py
│   ├── api.py
│   └── websocket.py        # Socket.IO 事件 + 五连判断
```

### 数据模型

```
models/
├── __init__.py             # 导出 GameRecord, UserGameStats
└── game_stats.py           # 新增：游戏战绩模型
```

### 模板文件（全部在 templates/ 根目录）

```
templates/
├── games.html              # 游戏大厅（替代 tools.html 空状态）
├── doudizhu.html           # 斗地主游戏页
├── chess.html              # 象棋游戏页
└── gomoku.html             # 五子棋游戏页
```

### 静态资源

```
assets/
├── css/games.css           # 游戏公共样式（棋盘、手牌、消息区）
└── js/
    ├── game_socket.js      # Socket.IO 游戏客户端基类
    ├── doudizhu.js         # 斗地主前端逻辑
    ├── chess.js            # 象棋前端逻辑
    └── gomoku.js           # 五子棋前端逻辑
```

### 集成点

- `app.py`: 注册 `game_doudizhu_bp`, `game_chess_bp`, `game_gomoku_bp` + 注册各 namespace 的 Socket.IO 事件
- `templates/tools.html`: 小游戏入口由"开发中"改为跳转到 `/board/games`
- `modules/chat/websocket.py`: 独立，不影响

---

## 3. 数据模型与房间状态设计

### 3.1 数据库模型（新增）

**GameRecord** — 每局结束后写入一条：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增ID |
| game_type | String(20) | doudizhu / chess / gomoku |
| room_id | String(36) | 房间UUID |
| started_at | DateTime | 开始时间 |
| ended_at | DateTime | 结束时间 |
| winner_ids | JSON | 赢家用户ID数组 |
| winner_names | JSON | 赢家昵称数组 |
| loser_ids | JSON | 输家用户ID数组 |
| loser_names | JSON | 输家昵称数组 |
| player_ids | JSON | 所有参与玩家ID |
| game_data | JSON | 扩展数据（斗地主倍数、象棋步数等） |

**UserGameStats** — 每个用户每个游戏一条：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 自增ID |
| user_id | Integer FK | 用户ID |
| game_type | String(20) | 游戏类型 |
| total_games | Integer | 总局数 |
| wins | Integer | 胜场 |
| losses | Integer | 负场 |
| draws | Integer | 平局（象棋/五子棋） |
| win_rate | Float | 胜率（后端计算） |
| last_played | DateTime | 最近游玩时间 |

唯一约束：`user_id` + `game_type`

### 3.2 内存房间状态（不存数据库）

每个活跃房间在内存中是一个字典，存放在各模块的内存字典中（参照 `chat/websocket.py` 的 `room_users`）：

```python
{
    'room_id': 'uuid',
    'name': '房间名',
    'game_type': 'doudizhu'|'chess'|'gomoku',
    'status': 'waiting'|'playing'|'ended',
    'creator_id': 1,
    'creator_name': '张三',
    'created_at': datetime,
    'max_players': 2|3,      # 斗地主3人，象棋/五子棋2人
    'password': '',           # 可选密码
    'players': [
        {
            'user_id': 1,
            'username': '张三',
            'nickname': '张三',
            'seat': 0,
            'ready': True,
            'role': '',           # 斗地主专用: landlord/peasant
            'is_online': True
        }
    ],
    'messages': [
        {'username': '系统', 'message': '张三 加入了房间', 'timestamp': '14:32:10', 'type': 'system'}
    ],
    'game_state': {...},       # 各游戏特有运行时状态（见下）
    'spectators': []           # 旁观者（可选，暂不实现）
}
```

**房间清理机制**：
- 玩家主动离开且房间无人 → 立即删除
- 游戏结束后 5 分钟无操作 → 自动清理
- 房主离开 → 房间解散，通知所有玩家

### 3.3 斗地主游戏状态 (`game_state`)

```python
{
    'deck': list,                       # 54张牌（发牌前）
    'hands': {0: [], 1: [], 2: []},     # 每个座位的手牌（已排序）
    'landlord': -1,                     # 地主座位号
    'bid_scores': {0: 0, 1: 0, 2: 0},   # 叫分记录
    'phase': 'bidding'|'playing'|'ended',
    'current_turn': 0,                  # 当前操作座位
    'last_play': {'seat': -1, 'cards': [], 'type': 'pass'},  # 上次出牌
    'multiple': 1,                      # 倍数
    'spring': False,                    # 春天标记
    'bottom_cards': []                  # 底牌3张
}
```

**牌面编码**：`3-10` 用数字，`11=J, 12=Q, 13=K, 14=A, 15=2, 16=小王, 17=大王`。花色 `s/h/d/c`（黑桃/红桃/方块/梅花）。实际游戏逻辑中花色仅用于前端展示，牌型比较只看 rank。

**牌型系统**：
- 单张、对子、三张、三带一、三带二、顺子（5+连张）、连对（3+连对）、飞机、飞机带翅膀、四带二、炸弹（4张同rank）、王炸（大小王）
- 只有炸弹和王炸能压过非炸弹牌型；炸弹之间比较 rank；王炸最大

### 3.4 象棋游戏状态 (`game_state`)

```python
{
    'board': [['r_rook', 'r_knight', 'r_elephant', 'r_guard', 'r_king',
               'r_guard', 'r_elephant', 'r_knight', 'r_rook'], ...],  # 10行×9列
    'current_turn': 'red',               # 'red' 或 'black'
    'red_player': 0,                     # 红方座位
    'black_player': 1,                   # 黑方座位
    'move_history': [],                  # [(from_x, from_y, to_x, to_y, piece), ...]
    'winner': None,
    'check_status': False,
    'draw_offered_by': None              # 谁发起了求和
}
```

**棋子编码**：`{颜色}_{类型}`，颜色 `r=红, b=黑`。类型：`king`（帅/将）、`rook`（车）、`knight`（马）、`elephant`（象/相）、`guard`（士/仕）、`cannon`（炮）、`pawn`（兵/卒）。

### 3.5 五子棋游戏状态 (`game_state`)

```python
{
    'board': [[0]*15 for _ in range(15)],  # 15×15，0=空, 1=黑, 2=白
    'current_turn': 1,                      # 1=黑, 2=白
    'black_player': 0,
    'white_player': 1,
    'move_history': [],                     # [(x, y, player), ...]
    'winner': None,
    'winning_line': [],                     # 获胜五子坐标
    'draw_offered_by': None
}
```

---

## 4. Socket.IO 事件设计

三个游戏各使用独立的 Socket.IO namespace：
- `/game-doudizhu`
- `/game-chess`
- `/game-gomoku`

### 4.1 通用事件（三个游戏共用）

**客户端 → 服务端**：

| 事件 | 参数 | 说明 |
|------|------|------|
| `create_room` | `{name, password?}` | 创建房间 |
| `join_room` | `{room_id, password?}` | 加入房间 |
| `leave_room` | `{}` | 离开当前房间 |
| `ready` | `{ready: true/false}` | 准备/取消准备 |
| `start_game` | `{}` | 房主开始游戏 |
| `send_message` | `{message}` | 发送聊天消息 |

**服务端 → 客户端**：

| 事件 | 数据 | 说明 |
|------|------|------|
| `room_created` | `{room_id, room}` | 房间创建成功 |
| `room_joined` | `{room}` | 加入成功 |
| `player_joined` | `{player, room}` | 广播：玩家加入 |
| `player_left` | `{user_id, username, room}` | 广播：玩家离开 |
| `player_ready` | `{user_id, ready, room}` | 广播：准备状态变化 |
| `game_started` | `{game_state, room}` | 广播：游戏开始 |
| `game_ended` | `{winner_ids, winner_names, reason, room}` | 广播：游戏结束 |
| `room_disbanded` | `{reason}` | 房间解散 |
| `new_message` | `{username, message, timestamp, type}` | 广播新消息 |
| `error` | `{message}` | 错误提示 |
| `room_list` | `{rooms}` | 房间列表更新 |
| `room_state` | `{room}` | 完整房间状态（用于重连） |

### 4.2 斗地主特有事件

**客户端 → 服务端**：

| 事件 | 参数 | 说明 |
|------|------|------|
| `bid` | `{score: 0\|1\|2\|3}` | 叫分，0=不叫 |
| `play_cards` | `{cards: [{suit, rank}, ...]}` | 出牌 |
| `pass` | `{}` | 不出 |

**服务端 → 客户端**：

| 事件 | 数据 | 说明 |
|------|------|------|
| `bidding_turn` | `{seat, room}` | 轮到谁叫分 |
| `bid_result` | `{seat, score, room}` | 叫分结果 |
| `landlord_decided` | `{landlord, bottom_cards, hands, room}` | 地主确定，发底牌 |
| `play_turn` | `{seat, room}` | 轮到谁出牌 |
| `cards_played` | `{seat, cards, card_type, room}` | 出牌结果 |
| `pass_turn` | `{seat, room}` | 某人不出 |

### 4.3 象棋特有事件

**客户端 → 服务端**：

| 事件 | 参数 | 说明 |
|------|------|------|
| `move` | `{from: [x,y], to: [x,y]}` | 走棋 |
| `offer_draw` | `{}` | 求和 |
| `resign` | `{}` | 认输 |

**服务端 → 客户端**：

| 事件 | 数据 | 说明 |
|------|------|------|
| `move_result` | `{from, to, piece, captured, room}` | 走棋结果 |
| `check` | `{seat, room}` | 将军 |
| `checkmate` | `{winner_seat, winner_name, room}` | 将死 |
| `stalemate` | `{reason, room}` | 困毙/和棋 |
| `draw_offered` | `{by_seat, by_name, room}` | 有人求和 |
| `draw_accepted` | `{room}` | 求和接受 |
| `draw_declined` | `{by_seat, room}` | 求和拒绝 |

### 4.4 五子棋特有事件

**客户端 → 服务端**：

| 事件 | 参数 | 说明 |
|------|------|------|
| `move` | `{x, y}` | 落子 |
| `offer_draw` | `{}` | 求和 |
| `resign` | `{}` | 认输 |

**服务端 → 客户端**：

| 事件 | 数据 | 说明 |
|------|------|------|
| `move_result` | `{x, y, player, room}` | 落子结果 |
| `five_in_row` | `{winner_seat, winner_name, winning_line, room}` | 五连 |
| `board_full` | `{room}` | 棋盘满，平局 |
| `draw_offered` / `draw_accepted` / `draw_declined` | 同象棋 | 求和相关 |

### 4.5 异常处理

- **非法操作**（如轮不到你出牌、牌型不合法、走法违规）：返回 `error` 事件，不广播状态变更
- **玩家断线**：标记 `is_online=False`，30秒内未重连则判负（斗地主：若游戏进行中则房间解散）
- **房主离开**：房间解散，所有玩家收到 `room_disbanded`，非游戏中可立即重新创建
- **求和流程**：A 发送 `offer_draw` → B 收到 `draw_offered` → B 可发送 `accept_draw` 或 `decline_draw` → 广播 `draw_accepted` 或 `draw_declined`

---

## 5. REST API 设计

### 5.1 通用 API（每个游戏模块前缀不同）

斗地主前缀 `/api/doudizhu/`，象棋 `/api/chess/`，五子棋 `/api/gomoku/`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rooms` | 获取活跃房间列表 |
| POST | `/rooms` | 创建房间 `{name, password?}` |
| POST | `/rooms/<id>/join` | 加入房间 `{password?}` |
| POST | `/rooms/<id>/leave` | 离开房间 |
| GET | `/rooms/<id>` | 获取房间详情 |

### 5.2 战绩 API（统一前缀 `/api/game/`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/stats/<game_type>` | 获取某游戏战绩（当前用户） |
| GET | `/stats/<game_type>?user_id=` | 获取某用户某游戏战绩 |
| GET | `/records?game_type=&limit=20` | 最近对局记录 |
| GET | `/leaderboard/<game_type>` | 排行榜（按胜率排序） |

---

## 6. UI 界面设计

### 6.1 games.html — 游戏大厅

替代现有 `tools.html` 中"小游戏功能开发中"的空状态。

- **风格**：Element UI + Vue 2，与 tools.html 完全一致
- **左侧导航**：高亮"小游戏"
- **主体区域**：
  - 三个游戏卡片网格（参照工具卡片样式）：斗地主（3人）、象棋（2人）、五子棋（2人）
  - 每个卡片含：图标、名称、人数说明、"进入大厅"按钮
  - 下方：最近对局战绩列表（从 API 拉取）
- **点击卡片**：跳转到对应游戏的子大厅页面

### 6.2 游戏子大厅页面（doudizhu.html / chess.html / gomoku.html）

**子大厅布局**：
- 标题栏：游戏名 + 返回按钮 + 创建房间按钮
- 房间列表：卡片式网格，显示房间名、人数（如 1/3）、状态（等待中/游戏中）
- 创建房间弹窗：输入房间名、密码（可选）
- 加入有密码房间：弹窗输入密码

**房间内布局**（游戏进行时）：

```
┌──────────────────────────────┬─────────────┐
│                              │             │
│      【游戏主区域】            │  消息面板    │
│                              │             │
│  斗地主：玩家头像+手牌数(顶部) │  ─────────  │
│          出牌区(中央)         │  系统消息   │
│          我的牌区(底部)       │  玩家消息   │
│          [出牌][过牌]         │  ─────────  │
│                              │  [输入][发送]│
│  象棋/五子棋：棋盘(Canvas)    │             │
│          [认输][求和]        │             │
│                              │             │
└──────────────────────────────┴─────────────┘
```

**消息面板**（右侧，宽度 280px）：
- 独立滚动区域
- 系统消息（灰色小字）+ 玩家消息（带昵称）
- 底部输入框 + 发送按钮
- 支持 Enter 键发送
- 样式参照 chat.html

### 6.3 响应式适配

- 桌面端：左右分栏（游戏区 + 消息面板）
- 移动端（< 768px）：消息面板收缩为底部浮窗或标签页切换

---

## 7. 游戏规则实现要点

### 7.1 斗地主

- **发牌**：随机洗牌，每人17张，留3张底牌
- **叫分**：从座位0开始轮流，可叫1/2/3分或不叫（0分）。最高分者为地主，若都未叫则由座位0当地主（叫1分）
- **出牌**：地主先出，轮流出牌，必须出比上轮大的牌型（或 pass）。连续两人都 pass 则新一轮由最后出牌者先出
- **胜负**：任意一方出完所有牌即结束。地主先出完则地主胜，任一农民先出完则农民胜（2人同时赢）
- **倍数**：初始1倍，炸弹×2，王炸×2，春天（地主出完农民未出一张牌）×2

### 7.2 象棋

- **走法验证**（`game_chess/websocket.py` 内联或独立函数）：
  - 帅/将：九宫格内，一格移动，不能对脸
  - 仕/士：九宫格内，斜线一格
  - 相/象：田字格，不能过河，不能塞象眼
  - 马：日字格，不能蹩马腿
  - 车：直线，不能越子
  - 炮：直线，移动不越子，吃子必须隔一个子
  - 兵/卒：过河前只能前进，过河后可左右或前进
- **将军检测**：每步棋模拟执行后，检查对方帅/将是否被将军
- **胜负**：将死对方帅/将、对方认输、对方超时（可选）
- **和棋**：双方同意求和、困毙（无合法走法但未被将军）、长将（连续将军对方无法摆脱，需实现重复局面检测）

### 7.3 五子棋

- **落子**：空位方可落子，黑白交替
- **胜负**：任意方向（横、竖、左上-右下、右上-左下）连续5子同色即胜
- **和棋**：棋盘满且无五连
- **禁手**（可选，暂不支持）：职业规则中的三三禁手、四四禁手、长连禁手

---

## 8. 与现有系统集成

### 8.1 app.py 变更

```python
from modules.game_doudizhu import game_doudizhu_bp
from modules.game_chess import game_chess_bp
from modules.game_gomoku import game_gomoku_bp
from modules.game_doudizhu.websocket import register_doudizhu_events
from modules.game_chess.websocket import register_chess_events
from modules.game_gomoku.websocket import register_gomoku_events

# 注册 Blueprint
app.register_blueprint(game_doudizhu_bp)
app.register_blueprint(game_chess_bp)
app.register_blueprint(game_gomoku_bp)

# 注册 Socket.IO 事件
register_doudizhu_events(socketio)
register_chess_events(socketio)
register_gomoku_events(socketio)
```

### 8.2 models/__init__.py 变更

导出 `GameRecord` 和 `UserGameStats`

### 8.3 app.py 迁移

在 `run_migrations()` 中自动创建 `game_record` 和 `user_game_stats` 表

### 8.4 tools.html 变更

小游戏入口导航到 `/board/games`（即 games.html 对应的路由）

---

## 9. 安全考虑

- **用户鉴权**：所有游戏 API 和 Socket.IO 事件要求登录（使用 `@login_required` 或检查 `current_user.is_authenticated`）
- **房间密码**：明文不传，前端 MD5 或 SHA256 哈希后比对（简单防窥探）
- **操作校验**：服务端校验每步操作合法性（轮次、牌型、走法），不信任客户端状态
- **防刷**：创建房间频率限制（同IP 1分钟内最多3个）

---

## 10. 扩展性

新增游戏的成本：
1. 创建 `modules/game_xxx/`（参照现有模板）
2. 创建 `templates/xxx.html`
3. 创建 `assets/js/xxx.js`
4. 在 `app.py` 注册 Blueprint + Socket.IO 事件
5. 在 `games.html` 添加游戏卡片

大约 1-2 天可添加一个新游戏。

---

## 11. 范围确认

**本次实现范围**：
- ✅ 斗地主、象棋、五子棋三个游戏
- ✅ 房间内实时消息聊天
- ✅ 战绩统计（数据库表 + API）
- ✅ 排行榜
- ✅ 房间密码保护
- ✅ 求和/认输功能（象棋/五子棋）

**明确不在范围内**：
- ❌ 观战模式（spectators）
- ❌ 象棋/五子棋 AI 对战
- ❌ 斗地主 AI 机器人（用户明确要求不加）
- ❌ 比赛/锦标赛系统
- ❌ 禁手规则（五子棋）
- ❌ 计时器/超时判负
- ❌ 游戏回放
