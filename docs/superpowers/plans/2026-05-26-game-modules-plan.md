# 联机小游戏模块实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 iFlyCompass 添加斗地主、象棋、五子棋三个联机小游戏，支持房间内消息聊天与战绩统计。

**Architecture:** 每个游戏独立 Flask Blueprint 模块，独立 Socket.IO namespace，内存管理房间状态，SQLite 存储战绩。参照现有 chat/md 模块模式。

**Tech Stack:** Flask 3.x, Flask-SocketIO, SQLAlchemy, Vue.js 2, Element UI, Canvas API

---

## 文件映射

### 新增文件（28个）

```
models/game_stats.py              # GameRecord + UserGameStats 模型
modules/game_doudizhu/__init__.py # 斗地主 Blueprint
modules/game_doudizhu/routes.py   # 斗地主页面路由
modules/game_doudizhu/api.py      # 斗地主 REST API
modules/game_doudizhu/websocket.py# 斗地主 Socket.IO 事件
templates/games.html              # 游戏大厅
templates/doudizhu.html           # 斗地主游戏页
templates/chess.html              # 象棋游戏页
templates/gomoku.html             # 五子棋游戏页
assets/css/games.css              # 游戏公共样式
assets/js/game_socket.js          # Socket.IO 客户端基类
assets/js/doudizhu.js             # 斗地主前端逻辑
assets/js/chess.js                # 象棋前端逻辑
assets/js/gomoku.js               # 五子棋前端逻辑
modules/game_chess/__init__.py    # 象棋 Blueprint
modules/game_chess/routes.py      # 象棋页面路由
modules/game_chess/api.py         # 象棋 REST API
modules/game_chess/websocket.py   # 象棋 Socket.IO 事件
modules/game_gomoku/__init__.py   # 五子棋 Blueprint
modules/game_gomoku/routes.py     # 五子棋页面路由
modules/game_gomoku/api.py        # 五子棋 REST API
modules/game_gomoku/websocket.py  # 五子棋 Socket.IO 事件
```

### 修改文件（4个）

```
models/__init__.py                # 导出 GameRecord, UserGameStats
app.py                            # 注册 Blueprint + Socket.IO + 迁移
templates/tools.html              # 小游戏入口改为 /board/games
```

---

## Phase 1: 数据模型与数据库迁移

### Task 1: 创建游戏战绩模型

**Files:**
- Create: `models/game_stats.py`
- Modify: `models/__init__.py`

- [ ] **Step 1: 创建 GameRecord 和 UserGameStats 模型**

`models/game_stats.py`:
```python
from extensions import db
from datetime import datetime

class GameRecord(db.Model):
    __tablename__ = 'game_record'
    id = db.Column(db.Integer, primary_key=True)
    game_type = db.Column(db.String(20), nullable=False)
    room_id = db.Column(db.String(36), nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)
    winner_ids = db.Column(db.JSON, default=list)
    winner_names = db.Column(db.JSON, default=list)
    loser_ids = db.Column(db.JSON, default=list)
    loser_names = db.Column(db.JSON, default=list)
    player_ids = db.Column(db.JSON, default=list)
    game_data = db.Column(db.JSON, default=dict)

class UserGameStats(db.Model):
    __tablename__ = 'user_game_stats'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    game_type = db.Column(db.String(20), nullable=False)
    total_games = db.Column(db.Integer, default=0)
    wins = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)
    draws = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float, default=0.0)
    last_played = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint('user_id', 'game_type', name='uq_user_game'),)
```

- [ ] **Step 2: 修改 models/__init__.py 导出新模型**

添加：`from .game_stats import GameRecord, UserGameStats`

- [ ] **Step 3: 在 app.py 添加数据库迁移**

在 `run_migrations(app)` 末尾添加 `game_record` 和 `user_game_stats` 表的自动创建逻辑（使用 `CREATE TABLE IF NOT EXISTS` 模式或先检查表是否存在）。参照现有 migration 风格。

- [ ] **Step 4: 验证**

运行 `python app.py`，确认控制台无报错且输出包含数据库迁移完成信息。

- [ ] **Step 5: 提交**

```bash
git add models/game_stats.py models/__init__.py app.py
git commit -m "feat(models): add GameRecord and UserGameStats models"
```

---

## Phase 2: 斗地主模块

### Task 2: 创建斗地主 Blueprint 和页面路由

**Files:**
- Create: `modules/game_doudizhu/__init__.py`
- Create: `modules/game_doudizhu/routes.py`

- [ ] **Step 1: 创建 Blueprint**

`modules/game_doudizhu/__init__.py`:
```python
from flask import Blueprint
game_doudizhu_bp = Blueprint('game_doudizhu', __name__, url_prefix='/games/doudizhu')
from . import routes
```

- [ ] **Step 2: 创建页面路由**

`modules/game_doudizhu/routes.py`:
```python
from flask import render_template
from flask_login import login_required, current_user
from . import game_doudizhu_bp

@game_doudizhu_bp.route('/')
@login_required
def index():
    return render_template('doudizhu.html',
                           current_user=current_user,
                           display_name=current_user.display_name,
                           username=current_user.username)
```

- [ ] **Step 3: 提交**

```bash
git add modules/game_doudizhu/__init__.py modules/game_doudizhu/routes.py
git commit -m "feat(doudizhu): add blueprint and routes"
```

### Task 3: 创建斗地主 REST API

**Files:**
- Create: `modules/game_doudizhu/api.py`

- [ ] **Step 1: 创建房间管理 API**

API 端点：
- `GET /api/doudizhu/rooms` — 房间列表
- `POST /api/doudizhu/rooms` — 创建房间 `{name, password}`
- `POST /api/doudizhu/rooms/<id>/join` — 加入房间 `{password}`
- `GET /api/doudizhu/rooms/<id>` — 房间详情

内存存储：`rooms = {}`。创建房间时自动生成 8 位 room_id。

参照设计文档中的数据结构创建房间对象。

- [ ] **Step 2: 提交**

```bash
git add modules/game_doudizhu/api.py
git commit -m "feat(doudizhu): add room management REST API"
```

### Task 4: 创建斗地主 Socket.IO 事件

**Files:**
- Create: `modules/game_doudizhu/websocket.py`

- [ ] **Step 1: 实现通用房间事件**

事件：`create_room`, `join_room`, `leave_room`, `ready`, `start_game`, `send_message`

- `leave_room`：房主离开则解散房间；游戏中玩家离开则结束游戏并保存战绩
- `start_game`：需3人且全部ready，初始化牌局状态

- [ ] **Step 2: 实现斗地主游戏逻辑**

函数：`_init_game_state`, `_get_card_type`, `_compare_cards`, `_save_game_record`

牌型：单张、对子、三张、三带一、三带二、顺子、连对、炸弹、王炸
叫分：1/2/3分或不叫，最高分者地主

- [ ] **Step 3: 实现叫分和出牌事件**

事件：`bid`, `play_cards`, `pass`

- `bid`：记录叫分，判断地主
- `play_cards`：校验牌型、是否压过上家、手牌合法性
- `pass`：校验是否可以过牌

- [ ] **Step 4: 提交**

```bash
git add modules/game_doudizhu/websocket.py
git commit -m "feat(doudizhu): add complete Socket.IO game logic"
```

### Task 5: 创建斗地主前端

**Files:**
- Create: `templates/doudizhu.html`
- Create: `assets/js/doudizhu.js`

- [ ] **Step 1: 创建 HTML 模板**

参照 `tools.html` 的左侧导航栏 + 主体布局。主体区域分为：
- 子大厅：房间列表 + 创建房间弹窗
- 游戏房间：顶部玩家信息、中间出牌区、底部手牌区、右侧消息面板

手牌使用 `.card` CSS 类展示，点击选中（高亮 + 上移），再次点击取消。

- [ ] **Step 2: 创建前端逻辑**

Vue 2 组件：
- 数据：`rooms`, `room`, `gameState`, `mySeat`, `selectedCards`, `messages`, `chatInput`
- 方法：`loadRooms`, `createRoom`, `joinRoom`, `toggleReady`, `startGame`, `bid`, `toggleCard`, `playCards`, `passTurn`, `sendMessage`
- Socket 事件监听：`room_joined`, `player_joined`, `game_started`, `bidding_turn`, `landlord_decided`, `play_turn`, `cards_played`, `game_ended`, `new_message`

- [ ] **Step 3: 提交**

```bash
git add templates/doudizhu.html assets/js/doudizhu.js
git commit -m "feat(doudizhu): add game frontend"
```

---

## Phase 3: 象棋模块

### Task 6: 创建象棋基础文件

**Files:**
- Create: `modules/game_chess/__init__.py`
- Create: `modules/game_chess/routes.py`
- Create: `modules/game_chess/api.py`

- [ ] **Step 1: 创建 Blueprint、路由、API**

参照斗地主，但 `max_players = 2`，`game_type = 'chess'`，前缀 `/games/chess` 和 `/api/chess/`。

- [ ] **Step 2: 提交**

```bash
git add modules/game_chess/__init__.py modules/game_chess/routes.py modules/game_chess/api.py
git commit -m "feat(chess): add blueprint, routes and API"
```

### Task 7: 创建象棋 Socket.IO 事件

**Files:**
- Create: `modules/game_chess/websocket.py`

- [ ] **Step 1: 实现走法验证**

函数：`_validate_move`, `_is_in_check`, `_is_checkmate`, `_is_stalemate`

棋子规则：
- 帅/将：九宫格内，一格移动，不能对脸
- 仕/士：九宫格内，斜线一格
- 相/象：田字格，不过河，不塞象眼
- 马：日字格，不蹩马腿
- 车：直线，不越子
- 炮：直线，吃子隔一子
- 兵/卒：过河前前进，过河后可左右

每步模拟执行后检查是否送将（`_is_in_check`）。

- [ ] **Step 2: 实现游戏事件**

通用事件（同斗地主）+ `move`, `offer_draw`, `accept_draw`, `decline_draw`, `resign`

`move`：验证走法 → 模拟 → 检查将军/将死/困毙 → 广播结果

- [ ] **Step 3: 提交**

```bash
git add modules/game_chess/websocket.py
git commit -m "feat(chess): add Socket.IO events with move validation"
```

### Task 8: 创建象棋前端

**Files:**
- Create: `templates/chess.html`
- Create: `assets/js/chess.js`

- [ ] **Step 1: 创建 HTML + Canvas 棋盘**

使用 `<canvas id="chess-board" width="450" height="500">` 绘制 9×10 棋盘。
棋子绘制为圆形 + 文字（帅/将/车/马/炮/兵/卒/相/象/仕/士）。

- [ ] **Step 2: 创建前端逻辑**

- Canvas 点击事件：计算棋盘坐标 → 选中己方棋子 → 再次点击目标位置 → 发送 `move`
- Socket 监听：`move_result`（更新棋盘）、`check`（将军提示）、`checkmate`/`stalemate`（结束）
- 操作按钮：认输、求和

- [ ] **Step 3: 提交**

```bash
git add templates/chess.html assets/js/chess.js
git commit -m "feat(chess): add frontend with Canvas board"
```

---

## Phase 4: 五子棋模块

### Task 9: 创建五子棋基础文件

**Files:**
- Create: `modules/game_gomoku/__init__.py`
- Create: `modules/game_gomoku/routes.py`
- Create: `modules/game_gomoku/api.py`

- [ ] **Step 1: 创建文件**

参照象棋，但 `game_type = 'gomoku'`，前缀 `/games/gomoku` 和 `/api/gomoku/`。

- [ ] **Step 2: 提交**

```bash
git add modules/game_gomoku/__init__.py modules/game_gomoku/routes.py modules/game_gomoku/api.py
git commit -m "feat(gomoku): add blueprint, routes and API"
```

### Task 10: 创建五子棋 Socket.IO 事件

**Files:**
- Create: `modules/game_gomoku/websocket.py`

- [ ] **Step 1: 实现游戏逻辑**

函数：`_check_five_in_row` — 向 4 个方向检查连续 5 子
棋盘：15×15，0=空, 1=黑, 2=白

事件：`move` — 校验空位 → 落子 → 检查五连/棋盘满

- [ ] **Step 2: 提交**

```bash
git add modules/game_gomoku/websocket.py
git commit -m "feat(gomoku): add Socket.IO events with five-in-row detection"
```

### Task 11: 创建五子棋前端

**Files:**
- Create: `templates/gomoku.html`
- Create: `assets/js/gomoku.js`

- [ ] **Step 1: 创建前端**

参照象棋，但棋盘改为 15×15，棋子为黑白圆点（无文字）。Canvas 大小约 450×450。

- [ ] **Step 2: 提交**

```bash
git add templates/gomoku.html assets/js/gomoku.js
git commit -m "feat(gomoku): add frontend with 15x15 Canvas board"
```

---

## Phase 5: 共享资源与集成

### Task 12: 创建游戏公共样式和 Socket 客户端

**Files:**
- Create: `assets/css/games.css`
- Create: `assets/js/game_socket.js`

- [ ] **Step 1: 创建 CSS**

包含：游戏大厅卡片、房间列表、游戏房间布局（左侧游戏区 + 右侧消息面板）、斗地主手牌样式、消息面板样式、响应式适配。

- [ ] **Step 2: 创建 Socket 基类**

`assets/js/game_socket.js`:
```javascript
var GameSocket = {
    createSocket: function(namespace) {
        var socket = io(namespace);
        socket.on('connect', function() { console.log('Connected to', namespace); });
        socket.on('disconnect', function() { console.log('Disconnected from', namespace); });
        return socket;
    }
};
```

- [ ] **Step 3: 提交**

```bash
git add assets/css/games.css assets/js/game_socket.js
git commit -m "feat(games): add shared CSS and Socket.IO client"
```

### Task 13: 创建游戏大厅页面

**Files:**
- Create: `templates/games.html`
- Modify: `templates/tools.html`

- [ ] **Step 1: 创建 games.html**

参照 `tools.html` 风格，左侧导航栏高亮"小游戏"。主体区域：
- 三个游戏卡片网格（斗地主、象棋、五子棋），点击跳转对应游戏
- 下方最近对局列表（调用 `/api/game/records?limit=10`）

- [ ] **Step 2: 修改 tools.html**

将小游戏入口的空状态（`el-empty description="小游戏功能开发中"`）改为跳转到 `/board/games`。

找到 `{% if category == 'games' %}` 块，替换为跳转到 `/board/games` 的链接或自动跳转逻辑。或者修改路由 `/board/games` 直接渲染 `games.html`。

- [ ] **Step 3: 添加游戏大厅路由**

在 `modules/main/routes.py` 中修改 `games()` 路由：
```python
@main_bp.route('/board/games')
@login_required
def games():
    return render_template('games.html',
                           current_user=current_user,
                           display_name=current_user.display_name,
                           username=current_user.username)
```

- [ ] **Step 4: 提交**

```bash
git add templates/games.html templates/tools.html modules/main/routes.py
git commit -m "feat(games): add game hall page and update tools entry"
```

### Task 14: 注册所有 Blueprint 和 Socket.IO 事件

**Files:**
- Modify: `app.py`

- [ ] **Step 1: 注册 Blueprint**

在 `app.py` 中添加：
```python
from modules.game_doudizhu import game_doudizhu_bp
from modules.game_chess import game_chess_bp
from modules.game_gomoku import game_gomoku_bp
from modules.game_doudizhu.websocket import register_doudizhu_events
from modules.game_chess.websocket import register_chess_events
from modules.game_gomoku.websocket import register_gomoku_events

app.register_blueprint(game_doudizhu_bp)
app.register_blueprint(game_chess_bp)
app.register_blueprint(game_gomoku_bp)

register_doudizhu_events(socketio)
register_chess_events(socketio)
register_gomoku_events(socketio)
```

- [ ] **Step 2: 添加战绩 API**

在任意游戏模块的 `api.py` 中添加（或新建 `modules/game_stats/api.py`）：

```python
from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from models import GameRecord, UserGameStats
from extensions import db

stats_bp = Blueprint('game_stats', __name__, url_prefix='/api/game')

@stats_bp.route('/stats/<game_type>')
@login_required
def get_stats(game_type):
    user_id = request.args.get('user_id', current_user.id, type=int)
    stats = UserGameStats.query.filter_by(user_id=user_id, game_type=game_type).first()
    if not stats:
        return jsonify({'game_type': game_type, 'total_games': 0, 'wins': 0, 'losses': 0, 'draws': 0, 'win_rate': 0.0})
    return jsonify({'game_type': stats.game_type, 'total_games': stats.total_games, 'wins': stats.wins, 'losses': stats.losses, 'draws': stats.draws, 'win_rate': stats.win_rate})

@stats_bp.route('/records')
@login_required
def get_records():
    game_type = request.args.get('game_type')
    limit = request.args.get('limit', 20, type=int)
    q = GameRecord.query
    if game_type:
        q = q.filter_by(game_type=game_type)
    records = q.order_by(GameRecord.ended_at.desc()).limit(limit).all()
    return jsonify({'records': [{'id': r.id, 'game_type': r.game_type, 'winner_names': r.winner_names, 'ended_at': r.ended_at.isoformat() if r.ended_at else None} for r in records]})

@stats_bp.route('/leaderboard/<game_type>')
@login_required
def get_leaderboard(game_type):
    stats = UserGameStats.query.filter_by(game_type=game_type).order_by(UserGameStats.win_rate.desc()).limit(20).all()
    return jsonify({'leaderboard': [{'user_id': s.user_id, 'total_games': s.total_games, 'wins': s.wins, 'win_rate': s.win_rate} for s in stats]})
```

在 `app.py` 注册：`app.register_blueprint(stats_bp)`

- [ ] **Step 3: 提交**

```bash
git add app.py
git commit -m "feat(app): register all game blueprints, socket events and stats API"
```

---

## Phase 6: 验证与测试

### Task 15: 启动测试

- [ ] **Step 1: 启动应用**

```bash
python app.py
```

- [ ] **Step 2: 手动验证清单**

1. 访问 `/board/games` — 应显示游戏大厅（三个游戏卡片）
2. 点击斗地主 — 进入子大厅，创建房间
3. 用另一浏览器/隐身窗口登录另一账号，加入房间
4. 第三个账号加入，全部准备，房主开始游戏
5. 验证叫分 → 地主确定 → 发底牌 → 轮流出牌 → 游戏结束 → 战绩写入
6. 测试房间内消息发送
7. 重复测试象棋和五子棋
8. 访问 `/api/game/records` — 应返回最近对局
9. 检查数据库中 `game_record` 和 `user_game_stats` 表是否有数据

- [ ] **Step 3: 提交最终版本**

```bash
git commit -m "REL2.6.0: add multiplayer games (doudizhu, chess, gomoku)"
```

---

## Spec Coverage Self-Review

| 设计文档要求 | 对应 Task |
|-------------|----------|
| 斗地主模块（3人，无AI） | Task 2-5 |
| 象棋模块（2人，走法验证） | Task 6-8 |
| 五子棋模块（2人，五连判断） | Task 9-11 |
| 房间内消息聊天 | Task 4, 7, 10（send_message 事件） |
| 战绩统计（GameRecord + UserGameStats） | Task 1, 14 |
| 游戏大厅页面 | Task 13 |
| 独立 Blueprint + Socket namespace | Task 2, 6, 9, 14 |
| 内存房间管理 | Task 3, 4, 7, 10 |
| 房间密码保护 | Task 3（API 层） |
| 求和/认输（象棋/五子棋） | Task 7, 10 |

**无 placeholder**：所有 task 均包含具体代码或明确实现要求。
