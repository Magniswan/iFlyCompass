(function() {
    'use strict';

    // ===== Card Helpers =====
    function cardText(card) {
        if (card.startsWith('joker')) {
            var rank = parseInt(card.substring(5));
            return rank === 16 ? '小王' : '大王';
        }
        var rank = parseInt(card.substring(1));
        if (rank >= 3 && rank <= 10) return String(rank);
        if (rank === 11) return 'J';
        if (rank === 12) return 'Q';
        if (rank === 13) return 'K';
        if (rank === 14) return 'A';
        if (rank === 15) return '2';
        return '?';
    }

    function cardSuit(card) {
        if (card.startsWith('joker')) return '★';
        var suit = card.charAt(0);
        if (suit === 's') return '♠';
        if (suit === 'h') return '♥';
        if (suit === 'd') return '♦';
        if (suit === 'c') return '♣';
        return '';
    }

    function cardColorClass(card) {
        if (card.startsWith('joker')) {
            var rank = parseInt(card.substring(5));
            return rank === 16 ? 'joker-small' : 'joker-big';
        }
        var suit = card.charAt(0);
        return (suit === 'h' || suit === 'd') ? 'red' : 'black';
    }

    function cardJokerClass(card) {
        if (!card.startsWith('joker')) return '';
        var rank = parseInt(card.substring(5));
        return rank === 16 ? 'joker-small' : 'joker-big';
    }

    // ===== Socket =====
    var socket = io('/game-doudizhu');

    socket.on('connect', function() {
        console.log('[Doudizhu] Socket connected');
    });

    socket.on('disconnect', function(reason) {
        console.log('[Doudizhu] Socket disconnected:', reason);
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
            myCards: [],
            selectedCards: [],
            messages: [],
            chatInput: '',
            chatOpen: false,
            showCreateDialog: false,
            showPasswordDialog: false,
            joinPassword: '',
            pendingRoom: null,
            createForm: { name: '', password: '' },
            showGameOver: false,
            gameWinners: [],
            gameOverReason: '',
            scores: {0: 0, 1: 0, 2: 0},
            scoreChange: {},
            displayName: currentDisplayName,
            username: currentUsername,
            nickname: currentNickname,
            isAdmin: isAdminUser,
            isSuperAdmin: isSuperAdminUser,
            userMenuVisible: false
        },
        computed: {
            otherPlayers: function() {
                if (!this.room || !this.room.players || this.mySeat === -1) return [null, null];
                var leftSeat = (this.mySeat + 2) % 3;
                var rightSeat = (this.mySeat + 1) % 3;
                return [
                    this.room.players[leftSeat] || null,
                    this.room.players[rightSeat] || null
                ];
            },
            currentTurnPlayer: function() {
                if (this.gameState.current_turn === undefined || this.gameState.current_turn === null) return null;
                if (!this.room || !this.room.players) return null;
                return this.room.players[this.gameState.current_turn];
            },
            isMyTurn: function() {
                return this.mySeat !== -1 && this.gameState.current_turn === this.mySeat;
            },
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
                return active.length >= 3 && active.every(function(p) { return p.ready; });
            },
            getReadyCount: function() {
                if (!this.room || !this.room.players) return 0;
                return this.room.players.filter(function(p) { return p && p.ready; }).length;
            },
            getPlayerCount: function() {
                if (!this.room || !this.room.players) return 0;
                return this.room.players.filter(function(p) { return p !== null; }).length;
            },
            lastPlay: function() {
                return this.gameState.last_play || null;
            },
            lastPlayPlayer: function() {
                if (!this.lastPlay || !this.room || !this.room.players) return null;
                return this.room.players[this.lastPlay.seat];
            },
            bottomCards: function() {
                return this.gameState.bottom_cards || [];
            },
            winnerNames: function() {
                if (!this.room || !this.room.players || !this.gameWinners) return [];
                var names = [];
                this.gameWinners.forEach(function(seat) {
                    var p = this.room.players[seat];
                    if (p) names.push(p.nickname || p.username);
                }.bind(this));
                return names;
            },
            mustPlay: function() {
                if (!this.lastPlay) return true;
                return this.lastPlay.seat === this.mySeat;
            },
            scoreDisplay: function() {
                var result = {};
                if (!this.room || !this.room.players) return result;
                for (var i = 0; i < 3; i++) {
                    var p = this.room.players[i];
                    if (p) {
                        result[i] = {
                            name: p.nickname || p.username,
                            score: this.scores[i] || 0,
                            change: this.scoreChange[i] || 0
                        };
                    }
                }
                return result;
            }
        },
        mounted: function() {
            this.loadRooms();
            this.bindSocketEvents();
            document.addEventListener('click', this.closeUserMenu);
            // 从URL参数自动加入房间
            var urlParams = new URLSearchParams(window.location.search);
            var rid = urlParams.get('room_id');
            if (rid) {
                this.roomId = rid;
                this.messages = [];
                this.resetGameState();
                socket.emit('join_room', { room_id: rid });
                // 清除URL参数，避免刷新时重复加入
                window.history.replaceState({}, '', window.location.pathname);
            }
        },
        beforeDestroy: function() {
            document.removeEventListener('click', this.closeUserMenu);
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
                fetch('/api/doudizhu/rooms')
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
                fetch('/api/doudizhu/rooms', {
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
                fetch('/api/doudizhu/rooms/' + roomItem.room_id + '/join', {
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
                this.myCards = [];
                this.selectedCards = [];
                this.messages = [];
                this.showGameOver = false;
                this.gameWinners = [];
                this.gameOverReason = '';
                this.scores = {0: 0, 1: 0, 2: 0};
                this.scoreChange = {};
                this.chatOpen = false;
            },
            resetGameState: function() {
                this.gameState = {};
                this.myCards = [];
                this.selectedCards = [];
                this.showGameOver = false;
                this.gameWinners = [];
                this.gameOverReason = '';
                this.scoreChange = {};
            },
            loadRoomDetail: function() {
                if (!this.roomId) return;
                var self = this;
                fetch('/api/doudizhu/rooms/' + this.roomId)
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
                        if (self.gameState.hands && self.gameState.hands[String(self.mySeat)]) {
                            self.myCards = self.gameState.hands[String(self.mySeat)];
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
            bid: function(score) {
                if (!this.roomId || this.mySeat === -1) return;
                socket.emit('bid', { room_id: this.roomId, seat: this.mySeat, score: score });
            },
            toggleCard: function(index) {
                var idx = this.selectedCards.indexOf(index);
                if (idx !== -1) {
                    this.selectedCards.splice(idx, 1);
                } else {
                    this.selectedCards.push(index);
                }
            },
            playCards: function() {
                if (this.selectedCards.length === 0) return;
                var selectedSet = {};
                this.selectedCards.forEach(function(idx) { selectedSet[idx] = true; });
                var cards = this.myCards.filter(function(_, idx) { return selectedSet[idx]; });
                // 等待服务端确认后再移除手牌，避免验证失败时牌被吞
                socket.emit('play_cards', { room_id: this.roomId, cards: cards });
            },
            passTurn: function() {
                if (!this.roomId) return;
                socket.emit('pass', { room_id: this.roomId });
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
            isCurrentTurn: function(player) {
                if (!player) return false;
                return this.gameState.current_turn === player.seat;
            },
            getHandCount: function(seat) {
                if (this.gameState.hands_count) {
                    var count = this.gameState.hands_count[String(seat)];
                    if (count !== undefined) return count;
                }
                if (seat === this.mySeat) {
                    return this.myCards.length;
                }
                if (this.gameState.hands && this.gameState.hands[String(seat)] !== undefined) {
                    return this.gameState.hands[String(seat)].length;
                }
                return 0;
            },
            cardText: cardText,
            cardSuit: cardSuit,
            cardColorClass: cardColorClass,
            cardJokerClass: cardJokerClass,
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
                        phase: data.phase,
                        current_turn: data.current_turn,
                        last_play: null,
                        consecutive_passes: 0
                    };
                    if (data.hands) {
                        self.myCards = data.hands[String(self.mySeat)] || [];
                        self.gameState.hands_count = {};
                        for (var s in data.hands) {
                            self.gameState.hands_count[s] = data.hands[s].length;
                        }
                    }
                    self.selectedCards = [];
                    self.$message.success('游戏开始！');
                });

                socket.on('bidding_turn', function(data) {
                    self.gameState.current_turn = data.seat;
                    self.gameState.current_bid = data.current_bid;
                    self.gameState.phase = 'bidding';
                });

                socket.on('bid_result', function(data) {
                    self.gameState.current_bid = data.current_bid;
                    if (self.gameState.bids === undefined) self.gameState.bids = {};
                    self.gameState.bids[data.seat] = data.score;
                    var player = self.room.players[data.seat];
                    var name = player ? (player.nickname || player.username) : '玩家';
                    var scoreText = data.score === 0 ? '不叫' : data.score + '分';
                    self.$message.info(name + ' 叫了 ' + scoreText);
                });

                socket.on('landlord_decided', function(data) {
                    self.gameState.landlord = data.landlord;
                    self.gameState.bottom_cards = data.bottom_cards;
                    self.gameState.phase = 'playing';
                    self.gameState.current_turn = data.landlord;
                    self.gameState.last_play = null;
                    self.gameState.consecutive_passes = 0;
                    if (data.hands) {
                        self.myCards = data.hands[String(self.mySeat)] || [];
                        self.gameState.hands_count = {};
                        for (var s in data.hands) {
                            self.gameState.hands_count[s] = data.hands[s].length;
                        }
                    }
                    if (self.room && self.room.players) {
                        self.room.players.forEach(function(p, i) {
                            if (p) p.role = (i === data.landlord) ? 'landlord' : 'peasant';
                        });
                    }
                    var landlordPlayer = self.room.players[data.landlord];
                    var name = landlordPlayer ? (landlordPlayer.nickname || landlordPlayer.username) : '玩家';
                    self.$message.success('地主是 ' + name + '，叫分 ' + data.bid_score + ' 分');
                });

                socket.on('play_turn', function(data) {
                    self.gameState.current_turn = data.seat;
                    self.gameState.must_play = data.must_play;
                    self.selectedCards = [];
                });

                socket.on('cards_played', function(data) {
                    self.gameState.last_play = {
                        seat: data.seat,
                        cards: data.cards,
                        card_type: data.card_type
                    };
                    self.gameState.consecutive_passes = 0;
                    if (self.gameState.hands_count) {
                        self.gameState.hands_count[String(data.seat)] = data.remaining;
                    }
                    // 服务端确认出牌成功，从自己的手牌中移除
                    if (data.seat === self.mySeat) {
                        var playedSet = {};
                        data.cards.forEach(function(card) { playedSet[card] = true; });
                        self.myCards = self.myCards.filter(function(card) { return !playedSet[card]; });
                        self.selectedCards = [];
                    }
                    var player = self.room.players[data.seat];
                    var name = player ? (player.nickname || player.username) : '玩家';
                    self.$message.info(name + ' 出了 ' + data.cards.length + ' 张牌');
                });

                socket.on('pass_turn', function(data) {
                    var player = self.room.players[data.seat];
                    var name = player ? (player.nickname || player.username) : '玩家';
                    self.$message.info(name + ' 过');
                });

                socket.on('game_ended', function(data) {
                    self.room.status = 'ended';
                    self.gameState.phase = 'ended';
                    self.gameWinners = data.winners || [];
                    self.showGameOver = true;
                    self.gameOverReason = data.reason || '';
                    if (data.score_change) {
                        self.scoreChange = data.score_change;
                    }
                    if (data.scores) {
                        self.scores = data.scores;
                    }
                    if (data.game_state && data.game_state.hands) {
                        self.gameState.hands = data.game_state.hands;
                        if (self.mySeat !== -1 && data.game_state.hands[String(self.mySeat)]) {
                            self.myCards = data.game_state.hands[String(self.mySeat)];
                        }
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
                    self.gameState.phase = 'ended';
                    self.showGameOver = true;
                    self.gameWinners = [];
                    if (data.reason === 'creator_left') {
                        self.gameOverReason = '房主离开';
                    } else {
                        self.gameOverReason = '玩家离开';
                    }
                });

                socket.on('play_again_ok', function(data) {
                    console.log('Play again ok:', data);
                    self.room.status = 'waiting';
                    self.gameState = {};
                    self.myCards = [];
                    self.selectedCards = [];
                    self.showGameOver = false;
                    self.gameWinners = [];
                    self.gameOverReason = '';
                    self.scoreChange = {};
                    if (data.room) {
                        self.room = data.room;
                    }
                    if (data.scores) {
                        self.scores = data.scores;
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

    window.DoudizhuApp = app;
})();
