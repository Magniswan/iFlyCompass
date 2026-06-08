(function() {
    'use strict';

    // ===== Constants =====
    var CANVAS_W = 450;
    var CANVAS_H = 450;
    var PADDING = 25;
    var BOARD_SIZE = 15;
    var CELL_SIZE = (CANVAS_W - 2 * PADDING) / (BOARD_SIZE - 1);
    var STONE_RADIUS = CELL_SIZE * 0.4;

    // ===== Socket =====
    var socket = io('/game-gomoku');

    socket.on('connect', function() {
        console.log('[Gomoku] Socket connected');
    });

    socket.on('disconnect', function(reason) {
        console.log('[Gomoku] Socket disconnected:', reason);
    });

    // ===== Vue App =====
    var app = new Vue({
        el: '#app',
        delimiters: ['[[', ']]'],
        data: {
            isCollapse: true,
            activeMenu: 'games',
            inRoom: false,
            roomId: '',
            rooms: [],
            room: {},
            gameState: {},
            mySeat: -1,
            myColor: null,
            board: [],
            messages: [],
            chatInput: '',
            chatOpen: false,
            showCreateDialog: false,
            showPasswordDialog: false,
            joinPassword: '',
            pendingRoom: null,
            createForm: { name: '', password: '' },
            showGameOver: false,
            gameOverTitle: '',
            gameOverText: '',
            drawOffered: false,
            drawOfferedBy: null,
            lastMove: null,
            scores: {0: 0, 1: 0},
            displayName: currentDisplayName,
            username: currentUsername,
            nickname: currentNickname,
            isAdmin: isAdminUser,
            isSuperAdmin: isSuperAdminUser,
            userMenuVisible: false
        },
        computed: {
            isPlayer: function() {
                return this.mySeat !== -1;
            },
            isCreator: function() {
                return this.room && this.room.creator_id === currentUserId;
            },
            isReady: function() {
                if (this.mySeat === -1 || !this.room || !this.room.players) return false;
                var p = this.room.players[this.mySeat];
                return p && p.ready;
            },
            canStartGame: function() {
                if (!this.room || !this.room.players) return false;
                var active = this.room.players.filter(function(p) { return p !== null; });
                return active.length >= 2 && active.every(function(p) { return p.ready; });
            },
            getReadyCount: function() {
                if (!this.room || !this.room.players) return 0;
                return this.room.players.filter(function(p) { return p && p.ready; }).length;
            },
            getPlayerCount: function() {
                if (!this.room || !this.room.players) return 0;
                return this.room.players.filter(function(p) { return p !== null; }).length;
            },
            currentTurnText: function() {
                if (!this.gameState || !this.gameState.current_turn) return '';
                var turn = this.gameState.current_turn;
                var isMyTurn = this.myColor === turn;
                var turnText = turn === 1 ? '黑方' : '白方';
                return isMyTurn ? '轮到您 (' + turnText + ')' : '轮到 ' + turnText;
            }
        },
        mounted: function() {
            this.loadRooms();
            this.bindSocketEvents();
            document.addEventListener('click', this.closeUserMenu);
            window.addEventListener('resize', this.onResize);
            // 从URL参数自动加入房间
            var urlParams = new URLSearchParams(window.location.search);
            var rid = urlParams.get('room_id');
            if (rid) {
                this.roomId = rid;
                this.messages = [];
                this.resetGameState();
                socket.emit('join_room', { room_id: rid });
                window.history.replaceState({}, '', window.location.pathname);
            }
        },
        beforeDestroy: function() {
            document.removeEventListener('click', this.closeUserMenu);
            window.removeEventListener('resize', this.onResize);
        },
        watch: {
            board: function() {
                this.$nextTick(this.drawBoard);
            },
            lastMove: function() {
                this.$nextTick(this.drawBoard);
            }
        },
        methods: {
            // ===== Navigation & Menu =====
            toggleCollapse: function() {
                this.isCollapse = !this.isCollapse;
            },
            toggleUserMenu: function() {
                this.userMenuVisible = !this.userMenuVisible;
            },
            closeUserMenu: function(e) {
                if (!e.target.closest('.user-menu-container')) {
                    this.userMenuVisible = false;
                }
            },
            openProfileDialog: function() {
                this.userMenuVisible = false;
            },
            goDropSettings: function() {
                this.userMenuVisible = false;
                window.location.href = '/drop/settings';
            },
            openDropDialog: function() {
                this.userMenuVisible = false;
                if (window.DropSender) {
                    window.DropSender.openDialog();
                }
            },
            confirmLogout: function() {
                this.userMenuVisible = false;
                this.$confirm('确定要退出登录吗？', '提示', {
                    confirmButtonText: '确定',
                    cancelButtonText: '取消',
                    type: 'warning'
                }).then(function() {
                    window.location.href = '/logout';
                }).catch(function() {});
            },
            handleMenuClick: function(key) {
                this.userMenuVisible = false;
                if (this.inRoom && this.roomId) {
                    this.goBack();
                }
                if (key === 'dashboard') {
                    window.location.href = '/board';
                } else if (key === 'users') {
                    window.location.href = '/board/users';
                } else if (key === 'passkeys') {
                    window.location.href = '/board/passkeys';
                } else if (key === 'chat') {
                    window.location.href = '/board/chat';
                } else if (key === 'tools') {
                    window.location.href = '/board/tools';
                } else if (key === 'games') {
                    window.location.href = '/board/games';
                } else if (key === 'settings') {
                    window.location.href = '/board/settings';
                }
            },

            // ===== Room Management =====
            loadRooms: function() {
                var self = this;
                fetch('/api/gomoku/rooms')
                    .then(function(response) { return response.json(); })
                    .then(function(data) {
                        if (Array.isArray(data)) {
                            self.rooms = data;
                        } else if (data.error) {
                            self.$message.error(data.error);
                        }
                    })
                    .catch(function(error) {
                        console.error('加载房间列表失败:', error);
                        self.$message.error('加载房间列表失败');
                    });
            },
            createRoom: function() {
                var self = this;
                var name = this.createForm.name.trim();
                if (!name) {
                    this.$message.warning('请输入房间名称');
                    return;
                }
                fetch('/api/gomoku/rooms', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: name,
                        password: this.createForm.password || undefined
                    })
                })
                .then(function(response) { return response.json(); })
                .then(function(data) {
                    if (data.error) {
                        self.$message.error(data.error);
                        return;
                    }
                    self.showCreateDialog = false;
                    self.createForm = { name: '', password: '' };
                    self.roomId = data.room_id;
                    self.room = data;
                    self.messages = [];
                    self.resetGameState();
                    socket.emit('create_room', { room_id: data.room_id });
                })
                .catch(function(error) {
                    console.error('创建房间失败:', error);
                    self.$message.error('创建房间失败');
                });
            },
            onJoinRoomClick: function(roomItem) {
                if (roomItem.has_password) {
                    this.pendingRoom = roomItem;
                    this.joinPassword = '';
                    this.showPasswordDialog = true;
                } else {
                    this.joinRoom(roomItem);
                }
            },
            confirmJoinPassword: function() {
                if (this.pendingRoom) {
                    this.joinRoom(this.pendingRoom, this.joinPassword);
                }
                this.showPasswordDialog = false;
                this.pendingRoom = null;
                this.joinPassword = '';
            },
            joinRoom: function(roomItem, password) {
                var self = this;
                fetch('/api/gomoku/rooms/' + roomItem.room_id + '/join', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(password ? { password: password } : {})
                })
                .then(function(response) {
                    if (response.status === 401) {
                        self.$message.error('房间密码错误');
                        throw new Error('密码错误');
                    }
                    return response.json();
                })
                .then(function(data) {
                    if (data.error) {
                        self.$message.error(data.error);
                        return;
                    }
                    self.roomId = roomItem.room_id;
                    self.room = data;
                    self.messages = [];
                    self.resetGameState();
                    socket.emit('join_room', { room_id: roomItem.room_id });
                })
                .catch(function(error) {
                    if (error.message !== '密码错误') {
                        console.error('加入房间失败:', error);
                        self.$message.error('加入房间失败');
                    }
                });
            },
            goBack: function() {
                if (this.inRoom && this.roomId) {
                    socket.emit('leave_room', { room_id: this.roomId });
                }
                this.resetRoomState();
                this.inRoom = false;
                this.roomId = '';
                this.loadRooms();
            },
            resetRoomState: function() {
                this.room = {};
                this.gameState = {};
                this.mySeat = -1;
                this.myColor = null;
                this.board = [];
                this.messages = [];
                this.showGameOver = false;
                this.gameOverTitle = '';
                this.gameOverText = '';
                this.drawOffered = false;
                this.drawOfferedBy = null;
                this.lastMove = null;
                this.chatOpen = false;
            },
            resetGameState: function() {
                this.gameState = {};
                this.board = [];
                this.lastMove = null;
                this.showGameOver = false;
                this.gameOverTitle = '';
                this.gameOverText = '';
                this.drawOffered = false;
                this.drawOfferedBy = null;
            },
            loadRoomDetail: function() {
                if (!this.roomId) return;
                var self = this;
                fetch('/api/gomoku/rooms/' + this.roomId)
                    .then(function(response) { return response.json(); })
                    .then(function(data) {
                        if (data.error) {
                            console.error('获取房间详情失败:', data.error);
                            return;
                        }
                        self.room = data;
                        self.gameState = data.game_state || {};
                        self.messages = data.messages || [];
                        if (self.mySeat === -1 && data.players) {
                            for (var i = 0; i < data.players.length; i++) {
                                if (data.players[i] && data.players[i].user_id === currentUserId) {
                                    self.mySeat = i;
                                    break;
                                }
                            }
                        }
                        if (self.gameState.board) {
                            self.board = self.gameState.board;
                        }
                    })
                    .catch(function(error) {
                        console.error('获取房间详情失败:', error);
                    });
            },

            // ===== Game Actions =====
            toggleReady: function() {
                if (!this.roomId || this.mySeat === -1) return;
                socket.emit('ready', { room_id: this.roomId, ready: !this.isReady });
            },
            startGame: function() {
                if (!this.roomId || !this.isCreator) return;
                socket.emit('start_game', { room_id: this.roomId });
            },
            offerDraw: function() {
                if (!this.roomId || !this.isPlayer) return;
                socket.emit('offer_draw', { room_id: this.roomId });
            },
            acceptDraw: function() {
                if (!this.roomId) return;
                this.drawOffered = false;
                socket.emit('accept_draw', { room_id: this.roomId });
            },
            declineDraw: function() {
                if (!this.roomId) return;
                this.drawOffered = false;
                socket.emit('decline_draw', { room_id: this.roomId });
            },
            confirmResign: function() {
                var self = this;
                this.$confirm('确定要认输吗？', '提示', {
                    confirmButtonText: '确定',
                    cancelButtonText: '取消',
                    type: 'warning'
                }).then(function() {
                    self.resign();
                }).catch(function() {});
            },
            resign: function() {
                if (!this.roomId || !this.isPlayer) return;
                socket.emit('resign', { room_id: this.roomId });
            },
            playAgain: function() {
                if (!this.roomId || !this.isCreator) return;
                socket.emit('play_again', { room_id: this.roomId });
            },
            sendMessage: function() {
                var msg = this.chatInput.trim();
                if (!msg || !this.roomId) return;
                this.chatInput = '';
                socket.emit('send_message', { room_id: this.roomId, message: msg });
            },

            // ===== Helpers =====
            isCurrentTurn: function(seat) {
                if (!this.gameState || !this.gameState.current_turn) return false;
                var color = this.getPlayerRole(seat);
                if (color === 'black') return this.gameState.current_turn === 1;
                if (color === 'white') return this.gameState.current_turn === 2;
                return false;
            },
            getPlayerRole: function(seat) {
                if (!this.gameState) return 'unknown';
                if (this.gameState.black_player === seat) return 'black';
                if (this.gameState.white_player === seat) return 'white';
                return 'unknown';
            },
            formatTime: function(isoString) {
                if (!isoString) return '';
                var d = new Date(isoString);
                if (isNaN(d.getTime())) return isoString;
                return d.toLocaleString('zh-CN', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit'
                });
            },
            scrollToBottom: function() {
                var container = this.$refs.chatMessages;
                if (container) {
                    this.$nextTick(function() {
                        container.scrollTop = container.scrollHeight;
                    });
                }
            },
            onResize: function() {
                this.$nextTick(this.drawBoard);
            },

            // ===== Canvas Drawing =====
            drawBoard: function() {
                var canvas = this.$refs.gomokuCanvas;
                if (!canvas) return;
                var ctx = canvas.getContext('2d');

                // Clear
                ctx.fillStyle = '#deb887';
                ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

                // Draw grid
                ctx.strokeStyle = '#5c3a1e';
                ctx.lineWidth = 1;

                for (var i = 0; i < BOARD_SIZE; i++) {
                    var pos = PADDING + i * CELL_SIZE;
                    // Vertical
                    ctx.beginPath();
                    ctx.moveTo(pos, PADDING);
                    ctx.lineTo(pos, PADDING + (BOARD_SIZE - 1) * CELL_SIZE);
                    ctx.stroke();
                    // Horizontal
                    ctx.beginPath();
                    ctx.moveTo(PADDING, pos);
                    ctx.lineTo(PADDING + (BOARD_SIZE - 1) * CELL_SIZE, pos);
                    ctx.stroke();
                }

                // Draw star points (天元及四星)
                var starPoints = [
                    [3, 3], [3, 7], [3, 11],
                    [7, 3], [7, 7], [7, 11],
                    [11, 3], [11, 7], [11, 11]
                ];
                ctx.fillStyle = '#5c3a1e';
                for (var s = 0; s < starPoints.length; s++) {
                    var sx = starPoints[s][0];
                    var sy = starPoints[s][1];
                    var cx = PADDING + sx * CELL_SIZE;
                    var cy = PADDING + sy * CELL_SIZE;
                    ctx.beginPath();
                    ctx.arc(cx, cy, 3, 0, 2 * Math.PI);
                    ctx.fill();
                }

                // Draw stones
                if (!this.board || this.board.length === 0) return;
                for (var x = 0; x < BOARD_SIZE; x++) {
                    for (var y = 0; y < BOARD_SIZE; y++) {
                        var stone = this.board[x][y];
                        if (stone !== 0) {
                            this.drawStone(ctx, x, y, stone);
                        }
                    }
                }

                // Highlight last move
                if (this.lastMove) {
                    var lx = this.lastMove.x;
                    var ly = this.lastMove.y;
                    var lcx = PADDING + ly * CELL_SIZE;
                    var lcy = PADDING + lx * CELL_SIZE;
                    ctx.fillStyle = '#ff0000';
                    ctx.beginPath();
                    ctx.arc(lcx, lcy, 4, 0, 2 * Math.PI);
                    ctx.fill();
                }

                // Highlight winning line
                if (this.gameState.winning_line && this.gameState.winning_line.length > 0) {
                    ctx.strokeStyle = '#ff0000';
                    ctx.lineWidth = 3;
                    for (var w = 0; w < this.gameState.winning_line.length; w++) {
                        var wx = this.gameState.winning_line[w][0];
                        var wy = this.gameState.winning_line[w][1];
                        var wcx = PADDING + wy * CELL_SIZE;
                        var wcy = PADDING + wx * CELL_SIZE;
                        ctx.beginPath();
                        ctx.arc(wcx, wcy, STONE_RADIUS + 4, 0, 2 * Math.PI);
                        ctx.stroke();
                    }
                }
            },

            drawStone: function(ctx, x, y, stone) {
                var cx = PADDING + y * CELL_SIZE;
                var cy = PADDING + x * CELL_SIZE;
                var isBlack = stone === 1;

                // Shadow
                ctx.shadowColor = 'rgba(0,0,0,0.3)';
                ctx.shadowBlur = 4;
                ctx.shadowOffsetX = 2;
                ctx.shadowOffsetY = 2;

                ctx.beginPath();
                ctx.arc(cx, cy, STONE_RADIUS, 0, 2 * Math.PI);
                if (isBlack) {
                    ctx.fillStyle = '#1a1a1a';
                    ctx.fill();
                } else {
                    ctx.fillStyle = '#f5f5f5';
                    ctx.fill();
                }

                // Reset shadow
                ctx.shadowColor = 'transparent';
                ctx.shadowBlur = 0;
                ctx.shadowOffsetX = 0;
                ctx.shadowOffsetY = 0;

                // White stone border
                if (!isBlack) {
                    ctx.beginPath();
                    ctx.arc(cx, cy, STONE_RADIUS, 0, 2 * Math.PI);
                    ctx.strokeStyle = '#333';
                    ctx.lineWidth = 1.5;
                    ctx.stroke();
                }
            },

            // ===== Canvas Click Handling =====
            onCanvasClick: function(e) {
                if (!this.isPlayer || this.room.status !== 'playing') return;
                if (this.myColor !== this.gameState.current_turn) return;
                if (this.showGameOver) return;

                var canvas = this.$refs.gomokuCanvas;
                var rect = canvas.getBoundingClientRect();
                var scaleX = canvas.width / rect.width;
                var scaleY = canvas.height / rect.height;
                var clickX = (e.clientX - rect.left) * scaleX;
                var clickY = (e.clientY - rect.top) * scaleY;

                // Find nearest intersection
                var boardY = Math.round((clickX - PADDING) / CELL_SIZE);
                var boardX = Math.round((clickY - PADDING) / CELL_SIZE);

                if (boardX < 0 || boardX >= BOARD_SIZE || boardY < 0 || boardY >= BOARD_SIZE) return;

                if (this.board[boardX][boardY] !== 0) return;

                // Send move
                socket.emit('move', {
                    room_id: this.roomId,
                    x: boardX,
                    y: boardY
                });
            },

            // ===== Socket Event Binding =====
            bindSocketEvents: function() {
                var self = this;

                socket.on('room_created', function(data) {
                    console.log('Room created:', data);
                    self.inRoom = true;
                    self.mySeat = data.seat || 0;
                    self.loadRoomDetail();
                });

                socket.on('room_joined', function(data) {
                    console.log('Room joined:', data);
                    self.inRoom = true;
                    self.mySeat = data.seat;
                    if (data.room) {
                        self.room = data.room;
                    }
                    self.loadRoomDetail();
                });

                socket.on('player_joined', function(data) {
                    console.log('Player joined:', data);
                    if (data.players) {
                        self.room.players = data.players;
                    }
                    self.$message.info(data.username + ' 加入了房间');
                });

                socket.on('player_left', function(data) {
                    console.log('Player left:', data);
                    if (self.room && self.room.players && data.seat !== undefined) {
                        self.room.players[data.seat] = null;
                    }
                    self.$message.info(data.username + ' 离开了房间');
                });

                socket.on('player_ready', function(data) {
                    console.log('Player ready:', data);
                    if (self.room && self.room.players && data.seat !== undefined) {
                        var p = self.room.players[data.seat];
                        if (p) p.ready = data.ready;
                    }
                });

                socket.on('game_started', function(data) {
                    console.log('Game started:', data);
                    self.room.status = 'playing';
                    self.gameState = {
                        current_turn: data.current_turn,
                        black_player: data.black_player,
                        white_player: data.white_player,
                        winner: null,
                        winning_line: []
                    };
                    if (data.board) {
                        self.board = data.board;
                    }
                    self.lastMove = null;
                    self.drawOffered = false;
                    self.drawOfferedBy = null;
                    self.$message.success('游戏开始！黑方先行');

                    // Update roles
                    if (data.players) {
                        self.room.players = data.players;
                        for (var i = 0; i < data.players.length; i++) {
                            if (data.players[i] && data.players[i].user_id === currentUserId) {
                                self.mySeat = i;
                                break;
                            }
                        }
                    }
                    if (self.mySeat === data.black_player) {
                        self.myColor = 1;
                    } else if (self.mySeat === data.white_player) {
                        self.myColor = 2;
                    }

                    self.$nextTick(self.drawBoard);
                });

                socket.on('move_result', function(data) {
                    console.log('Move result:', data);
                    if (data.board) {
                        self.board = data.board;
                    } else {
                        // Update board locally
                        self.board[data.x][data.y] = data.player;
                        // Force reactivity update
                        self.board = self.board.slice();
                    }
                    self.gameState.current_turn = data.next_turn;
                    self.lastMove = { x: data.x, y: data.y };
                    var playerName = data.player === 1 ? '黑方' : '白方';
                    self.$message.info(playerName + ' 落子');
                    self.$nextTick(self.drawBoard);
                });

                socket.on('five_in_row', function(data) {
                    self.gameState.winner = data.winner;
                    self.gameState.winning_line = data.winning_line;
                    self.showGameOver = true;
                    self.gameOverTitle = '五子连珠！';
                    var winnerName = self.room.players[data.winner] ? (self.room.players[data.winner].nickname || self.room.players[data.winner].username) : '';
                    var winnerColor = data.player === 1 ? '黑方' : '白方';
                    self.gameOverText = winnerName + ' (' + winnerColor + ') 获胜';
                    self.$nextTick(self.drawBoard);
                });

                socket.on('board_full', function(data) {
                    self.gameState.winner = [];
                    self.showGameOver = true;
                    self.gameOverTitle = '平局';
                    self.gameOverText = '棋盘已满，双方和棋';
                });

                socket.on('draw_offered', function(data) {
                    if (data.seat !== self.mySeat) {
                        self.drawOffered = true;
                        self.drawOfferedBy = data.seat;
                        self.$message.info(data.username + ' 请求和棋');
                    }
                });

                socket.on('draw_accepted', function(data) {
                    self.drawOffered = false;
                    self.gameState.winner = [];
                    self.showGameOver = true;
                    self.gameOverTitle = '和棋';
                    self.gameOverText = '双方同意和棋';
                });

                socket.on('draw_declined', function(data) {
                    self.drawOffered = false;
                    self.drawOfferedBy = null;
                    self.$message.info(data.username + ' 拒绝了和棋请求');
                });

                socket.on('game_ended', function(data) {
                    self.room.status = 'ended';
                    self.gameState.winner = data.winners;
                    if (data.scores) {
                        self.scores = data.scores;
                    }
                    if (data.winners && data.winners.length > 0) {
                        self.showGameOver = true;
                        var winnerSeat = data.winners[0];
                        var winnerName = self.room.players[winnerSeat] ? (self.room.players[winnerSeat].nickname || self.room.players[winnerSeat].username) : '';
                        var winnerColor = winnerSeat === self.gameState.black_player ? '黑方' : '白方';
                        if (data.reason === 'resign') {
                            self.gameOverTitle = '认输';
                        } else {
                            self.gameOverTitle = '游戏结束';
                        }
                        self.gameOverText = winnerName + ' (' + winnerColor + ') 获胜';
                    } else if (data.reason === 'creator_left' || data.reason === 'player_left') {
                        self.$message.warning('房间已解散');
                        self.resetRoomState();
                        self.inRoom = false;
                        self.roomId = '';
                        self.loadRooms();
                    }
                });

                socket.on('room_disbanded', function(data) {
                    self.$message.warning('房间已解散');
                    self.resetRoomState();
                    self.inRoom = false;
                    self.roomId = '';
                    self.loadRooms();
                });

                socket.on('player_left_game', function(data) {
                    console.log('Player left game:', data);
                    if (self.room && self.room.players && data.seat !== undefined) {
                        self.room.players[data.seat] = null;
                    }
                    self.showGameOver = true;
                    if (data.reason === 'creator_left') {
                        self.gameOverTitle = '房主离开';
                        self.gameOverText = '房主已离开游戏';
                    } else {
                        self.gameOverTitle = '对手离开';
                        self.gameOverText = (data.username || '对手') + ' 已离开游戏';
                    }
                });

                socket.on('play_again_ok', function(data) {
                    console.log('Play again ok:', data);
                    self.room.status = 'waiting';
                    self.gameState = {};
                    self.board = [];
                    self.lastMove = null;
                    self.showGameOver = false;
                    self.drawOffered = false;
                    self.drawOfferedBy = null;
                    if (data.room) {
                        self.room = data.room;
                    }
                    if (data.room && data.room.scores) {
                        self.scores = data.room.scores;
                    }
                    self.$message.success('再来一局！请准备');
                });

                socket.on('new_message', function(data) {
                    self.messages.push(data);
                    if (self.messages.length > 200) {
                        self.messages = self.messages.slice(-200);
                    }
                    self.scrollToBottom();
                });

                socket.on('error', function(data) {
                    console.error('Socket error:', data);
                    self.$message.error(data.message || '发生错误');
                });
            }
        }
    });

    window.GomokuApp = app;
})();
