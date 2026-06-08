(function() {
    'use strict';

    // ===== Constants =====
    var CANVAS_W = 500;
    var CANVAS_H = 550;
    var PADDING = 50;
    var CELL_SIZE = 50;
    var PIECE_RADIUS = 20;

    var PIECE_CHARS = {
        'r_king': '帅',
        'r_guard': '仕',
        'r_elephant': '相',
        'r_knight': '马',
        'r_rook': '车',
        'r_cannon': '炮',
        'r_pawn': '兵',
        'b_king': '将',
        'b_guard': '士',
        'b_elephant': '象',
        'b_knight': '马',
        'b_rook': '车',
        'b_cannon': '炮',
        'b_pawn': '卒'
    };

    // ===== Socket =====
    var socket = io('/game-chess');

    socket.on('connect', function() {
        console.log('[Chess] Socket connected');
    });

    socket.on('disconnect', function(reason) {
        console.log('[Chess] Socket disconnected:', reason);
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
            selectedPiece: null,
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
                return isMyTurn ? '轮到您 (' + (turn === 'red' ? '红方' : '黑方') + ')' : '轮到 ' + (turn === 'red' ? '红方' : '黑方');
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
            selectedPiece: function() {
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
                fetch('/api/chess/rooms')
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
                fetch('/api/chess/rooms', {
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
                fetch('/api/chess/rooms/' + roomItem.room_id + '/join', {
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
                this.selectedPiece = null;
                this.chatOpen = false;
            },
            resetGameState: function() {
                this.gameState = {};
                this.board = [];
                this.selectedPiece = null;
                this.showGameOver = false;
                this.gameOverTitle = '';
                this.gameOverText = '';
                this.drawOffered = false;
                this.drawOfferedBy = null;
            },
            loadRoomDetail: function() {
                if (!this.roomId) return;
                var self = this;
                fetch('/api/chess/rooms/' + this.roomId)
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
                return color === this.gameState.current_turn;
            },
            getPlayerRole: function(seat) {
                if (!this.gameState) return 'unknown';
                if (this.gameState.red_player === seat) return 'red';
                if (this.gameState.black_player === seat) return 'black';
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
                var canvas = this.$refs.chessCanvas;
                if (!canvas) return;
                var ctx = canvas.getContext('2d');

                // Clear
                ctx.fillStyle = '#f0d9a3';
                ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

                // Draw grid
                ctx.strokeStyle = '#5c3a1e';
                ctx.lineWidth = 1.5;

                // Vertical lines
                for (var y = 0; y < 9; y++) {
                    var x1 = PADDING + y * CELL_SIZE;
                    var y1 = PADDING;
                    var y2 = PADDING + 9 * CELL_SIZE;
                    ctx.beginPath();
                    ctx.moveTo(x1, y1);
                    ctx.lineTo(x1, y2);
                    ctx.stroke();
                }

                // Horizontal lines (split by river)
                for (var x = 0; x < 10; x++) {
                    var y1 = PADDING + x * CELL_SIZE;
                    var x1 = PADDING;
                    var x2 = PADDING + 8 * CELL_SIZE;
                    ctx.beginPath();
                    ctx.moveTo(x1, y1);
                    ctx.lineTo(x2, y1);
                    ctx.stroke();
                }

                // Palace diagonals
                ctx.lineWidth = 1.2;
                // Black palace
                ctx.beginPath();
                ctx.moveTo(PADDING + 3 * CELL_SIZE, PADDING + 0 * CELL_SIZE);
                ctx.lineTo(PADDING + 5 * CELL_SIZE, PADDING + 2 * CELL_SIZE);
                ctx.stroke();
                ctx.beginPath();
                ctx.moveTo(PADDING + 5 * CELL_SIZE, PADDING + 0 * CELL_SIZE);
                ctx.lineTo(PADDING + 3 * CELL_SIZE, PADDING + 2 * CELL_SIZE);
                ctx.stroke();
                // Red palace
                ctx.beginPath();
                ctx.moveTo(PADDING + 3 * CELL_SIZE, PADDING + 7 * CELL_SIZE);
                ctx.lineTo(PADDING + 5 * CELL_SIZE, PADDING + 9 * CELL_SIZE);
                ctx.stroke();
                ctx.beginPath();
                ctx.moveTo(PADDING + 5 * CELL_SIZE, PADDING + 7 * CELL_SIZE);
                ctx.lineTo(PADDING + 3 * CELL_SIZE, PADDING + 9 * CELL_SIZE);
                ctx.stroke();

                // River text
                ctx.fillStyle = '#5c3a1e';
                ctx.font = 'bold 18px "Microsoft YaHei", sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText('楚', PADDING + 1 * CELL_SIZE, PADDING + 4.5 * CELL_SIZE);
                ctx.fillText('河', PADDING + 2 * CELL_SIZE, PADDING + 4.5 * CELL_SIZE);
                ctx.fillText('汉', PADDING + 6 * CELL_SIZE, PADDING + 4.5 * CELL_SIZE);
                ctx.fillText('界', PADDING + 7 * CELL_SIZE, PADDING + 4.5 * CELL_SIZE);

                // Draw pieces
                if (!this.board || this.board.length === 0) return;
                for (var x = 0; x < 10; x++) {
                    for (var y = 0; y < 9; y++) {
                        var piece = this.board[x][y];
                        if (piece) {
                            this.drawPiece(ctx, x, y, piece);
                        }
                    }
                }

                // Draw selection highlight
                if (this.selectedPiece) {
                    var sx = this.selectedPiece.x;
                    var sy = this.selectedPiece.y;
                    ctx.strokeStyle = '#e4393c';
                    ctx.lineWidth = 3;
                    ctx.beginPath();
                    ctx.arc(PADDING + sy * CELL_SIZE, PADDING + sx * CELL_SIZE, PIECE_RADIUS + 3, 0, 2 * Math.PI);
                    ctx.stroke();
                }
            },

            drawPiece: function(ctx, x, y, piece) {
                var cx = PADDING + y * CELL_SIZE;
                var cy = PADDING + x * CELL_SIZE;
                var isRed = piece.startsWith('r_');
                var char = PIECE_CHARS[piece] || '?';

                // Shadow
                ctx.shadowColor = 'rgba(0,0,0,0.3)';
                ctx.shadowBlur = 4;
                ctx.shadowOffsetX = 2;
                ctx.shadowOffsetY = 2;

                // Piece circle background
                ctx.beginPath();
                ctx.arc(cx, cy, PIECE_RADIUS, 0, 2 * Math.PI);
                ctx.fillStyle = '#f5e6c8';
                ctx.fill();

                // Reset shadow
                ctx.shadowColor = 'transparent';
                ctx.shadowBlur = 0;
                ctx.shadowOffsetX = 0;
                ctx.shadowOffsetY = 0;

                // Border
                ctx.beginPath();
                ctx.arc(cx, cy, PIECE_RADIUS, 0, 2 * Math.PI);
                ctx.strokeStyle = isRed ? '#c41e24' : '#2c2c2c';
                ctx.lineWidth = 2.5;
                ctx.stroke();

                // Inner border
                ctx.beginPath();
                ctx.arc(cx, cy, PIECE_RADIUS - 4, 0, 2 * Math.PI);
                ctx.strokeStyle = isRed ? '#e4393c' : '#444';
                ctx.lineWidth = 1;
                ctx.stroke();

                // Text
                ctx.fillStyle = isRed ? '#c41e24' : '#1a1a1a';
                ctx.font = 'bold 18px "Microsoft YaHei", "SimHei", sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(char, cx, cy + 1);
            },

            // ===== Canvas Click Handling =====
            onCanvasClick: function(e) {
                if (!this.isPlayer || this.room.status !== 'playing') return;
                if (this.myColor !== this.gameState.current_turn) return;
                if (this.showGameOver) return;

                var canvas = this.$refs.chessCanvas;
                var rect = canvas.getBoundingClientRect();
                var scaleX = canvas.width / rect.width;
                var scaleY = canvas.height / rect.height;
                var clickX = (e.clientX - rect.left) * scaleX;
                var clickY = (e.clientY - rect.top) * scaleY;

                // Find nearest intersection
                var boardY = Math.round((clickX - PADDING) / CELL_SIZE);
                var boardX = Math.round((clickY - PADDING) / CELL_SIZE);

                if (boardX < 0 || boardX >= 10 || boardY < 0 || boardY >= 9) return;

                var piece = this.board[boardX][boardY];

                if (this.selectedPiece) {
                    var sx = this.selectedPiece.x;
                    var sy = this.selectedPiece.y;
                    if (sx === boardX && sy === boardY) {
                        // Deselect
                        this.selectedPiece = null;
                        return;
                    }
                    if (piece && ((this.myColor === 'red' && piece.startsWith('r_')) || (this.myColor === 'black' && piece.startsWith('b_')))) {
                        // Reselect own piece
                        this.selectedPiece = { x: boardX, y: boardY };
                        return;
                    }
                    // Try to move
                    socket.emit('move', {
                        room_id: this.roomId,
                        from_x: sx,
                        from_y: sy,
                        to_x: boardX,
                        to_y: boardY
                    });
                    this.selectedPiece = null;
                } else {
                    if (piece && ((this.myColor === 'red' && piece.startsWith('r_')) || (this.myColor === 'black' && piece.startsWith('b_')))) {
                        this.selectedPiece = { x: boardX, y: boardY };
                    }
                }
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
                        red_player: data.red_player,
                        black_player: data.black_player,
                        check_status: false,
                        winner: null
                    };
                    if (data.board) {
                        self.board = data.board;
                    }
                    self.selectedPiece = null;
                    self.drawOffered = false;
                    self.drawOfferedBy = null;
                    self.$message.success('游戏开始！红方先行');

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
                    if (self.mySeat === data.red_player) {
                        self.myColor = 'red';
                    } else if (self.mySeat === data.black_player) {
                        self.myColor = 'black';
                    }

                    self.$nextTick(self.drawBoard);
                });

                socket.on('move_result', function(data) {
                    console.log('Move result:', data);
                    if (data.board) {
                        self.board = data.board;
                    } else {
                        // Update board locally
                        var piece = self.board[data.from_x][data.from_y];
                        self.board[data.from_x][data.from_y] = null;
                        self.board[data.to_x][data.to_y] = piece;
                        // Force reactivity update
                        self.board = self.board.slice();
                    }
                    self.gameState.current_turn = data.next_turn;
                    self.selectedPiece = null;
                    self.$message.info((data.color === 'red' ? '红方' : '黑方') + ' 走棋');
                    self.$nextTick(self.drawBoard);
                });

                socket.on('check', function(data) {
                    self.gameState.check_status = true;
                    self.$message.warning('将军！');
                });

                socket.on('checkmate', function(data) {
                    self.gameState.check_status = true;
                    self.gameState.winner = data.winner;
                    self.showGameOver = true;
                    self.gameOverTitle = '将死！';
                    var winnerName = self.room.players[data.winner] ? (self.room.players[data.winner].nickname || self.room.players[data.winner].username) : '';
                    self.gameOverText = winnerName + ' (' + (data.winner === self.gameState.red_player ? '红方' : '黑方') + ') 获胜';
                });

                socket.on('stalemate', function(data) {
                    self.gameState.check_status = false;
                    self.gameState.winner = [];
                    self.showGameOver = true;
                    self.gameOverTitle = '逼和';
                    self.gameOverText = '双方和棋';
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
                        var winnerColor = winnerSeat === self.gameState.red_player ? '红方' : '黑方';
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
                    self.selectedPiece = null;
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

    window.ChessApp = app;
})();
