(function() {
    'use strict';

    var socket = io('/game-uno');
    socket.on('connect', function() { console.log('[UNO] Socket connected'); });
    socket.on('disconnect', function(reason) { console.log('[UNO] Socket disconnected:', reason); });

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
            selectedCard: null,
            showColorPicker: false,
            pendingCard: null,
            messages: [],
            chatInput: '',
            chatOpen: false,
            showCreateDialog: false,
            showPasswordDialog: false,
            joinPassword: '',
            pendingRoom: null,
            createForm: { name: '', password: '', maxPlayers: 8 },
            showGameOver: false,
            gameWinners: [],
            displayName: currentDisplayName,
            username: currentUsername,
            nickname: currentNickname,
            isAdmin: isAdminUser,
            userMenuVisible: false
        },
        computed: {
            otherPlayers: function() {
                if (!this.room || !this.room.players || this.mySeat === -1) return [];
                var result = [];
                for (var i = 0; i < this.room.players.length; i++) {
                    if (i !== this.mySeat && this.room.players[i]) {
                        result.push(this.room.players[i]);
                    }
                }
                return result;
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
            deckCount: function() {
                return this.gameState.deck_count || 0;
            },
            winnerNames: function() {
                if (!this.room || !this.room.players || !this.gameWinners) return [];
                var names = [];
                this.gameWinners.forEach(function(seat) {
                    var p = this.room.players[seat];
                    if (p) names.push(p.nickname || p.username);
                }.bind(this));
                return names;
            }
        },
        mounted: function() {
            this.loadRooms();
            this.bindSocketEvents();
            document.addEventListener('click', this.closeUserMenu);
        },
        beforeDestroy: function() {
            document.removeEventListener('click', this.closeUserMenu);
        },
        methods: {
            // Navigation
            toggleCollapse: function() { this.isCollapse = !this.isCollapse; },
            toggleUserMenu: function() { this.userMenuVisible = !this.userMenuVisible; },
            closeUserMenu: function(e) {
                if (!e.target.closest('.user-menu-container')) this.userMenuVisible = false;
            },
            openProfileDialog: function() { this.userMenuVisible = false; },
            confirmLogout: function() {
                this.userMenuVisible = false;
                this.$confirm('确定要退出登录吗？', '提示', {
                    confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
                }).then(function() { window.location.href = '/logout'; }).catch(function() {});
            },
            handleMenuClick: function(key) {
                this.userMenuVisible = false;
                if (this.inRoom && this.roomId) this.goBack();
                if (key === 'dashboard') window.location.href = '/board';
                else if (key === 'tools') window.location.href = '/board/tools';
                else if (key === 'games') window.location.href = '/board/games';
                else if (key === 'chat') window.location.href = '/board/chat';
                else if (key === 'users') window.location.href = '/board/users';
                else if (key === 'settings') window.location.href = '/board/settings';
            },

            // Room Management
            loadRooms: function() {
                var self = this;
                fetch('/api/uno/rooms')
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (Array.isArray(data)) self.rooms = data;
                        else if (data.error) self.$message.error(data.error);
                    })
                    .catch(function() { self.$message.error('加载房间列表失败'); });
            },
            createRoom: function() {
                var self = this;
                var name = this.createForm.name.trim();
                if (!name) { this.$message.warning('请输入房间名称'); return; }
                fetch('/api/uno/rooms', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name, password: this.createForm.password || undefined, max_players: this.createForm.maxPlayers })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.error) { self.$message.error(data.error); return; }
                    self.showCreateDialog = false;
                    self.createForm = { name: '', password: '', maxPlayers: 8 };
                    self.roomId = data.room_id;
                    self.room = data;
                    self.messages = [];
                    self.resetGameState();
                    socket.emit('create_room', { room_id: data.room_id });
                })
                .catch(function() { self.$message.error('创建房间失败'); });
            },
            onJoinRoomClick: function(roomItem) {
                if (roomItem.has_password) {
                    this.pendingRoom = roomItem; this.joinPassword = ''; this.showPasswordDialog = true;
                } else {
                    this.joinRoom(roomItem);
                }
            },
            confirmJoinPassword: function() {
                if (this.pendingRoom) this.joinRoom(this.pendingRoom, this.joinPassword);
                this.showPasswordDialog = false; this.pendingRoom = null; this.joinPassword = '';
            },
            joinRoom: function(roomItem, password) {
                var self = this;
                fetch('/api/uno/rooms/' + roomItem.room_id + '/join', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(password ? { password: password } : {})
                })
                .then(function(r) {
                    if (r.status === 401) { self.$message.error('房间密码错误'); throw new Error('密码错误'); }
                    return r.json();
                })
                .then(function(data) {
                    if (data.error) { self.$message.error(data.error); return; }
                    self.roomId = roomItem.room_id;
                    self.room = data;
                    self.messages = [];
                    self.resetGameState();
                    socket.emit('join_room', { room_id: roomItem.room_id });
                })
                .catch(function(e) { if (e.message !== '密码错误') self.$message.error('加入房间失败'); });
            },
            goBack: function() {
                if (this.inRoom && this.roomId) socket.emit('leave_room', { room_id: this.roomId });
                this.resetRoomState();
                this.inRoom = false;
                this.roomId = '';
                this.loadRooms();
            },
            resetRoomState: function() {
                this.room = {}; this.gameState = {}; this.mySeat = -1; this.myCards = [];
                this.selectedCard = null; this.showColorPicker = false; this.pendingCard = null;
                this.messages = []; this.showGameOver = false; this.gameWinners = []; this.chatOpen = false;
            },
            resetGameState: function() {
                this.gameState = {}; this.myCards = []; this.selectedCard = null;
                this.showGameOver = false; this.gameWinners = []; this.showColorPicker = false; this.pendingCard = null;
            },
            loadRoomDetail: function() {
                if (!this.roomId) return;
                var self = this;
                fetch('/api/uno/rooms/' + this.roomId)
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (data.error) return;
                        self.room = data;
                        self.gameState = data.game_state || {};
                        self.messages = data.messages || [];
                        if (self.mySeat === -1 && data.players) {
                            for (var i = 0; i < data.players.length; i++) {
                                if (data.players[i] && data.players[i].user_id === currentUserId) { self.mySeat = i; break; }
                            }
                        }
                        if (self.gameState.hands && self.gameState.hands[String(self.mySeat)]) {
                            self.myCards = self.gameState.hands[String(self.mySeat)];
                        }
                    })
                    .catch(function() {});
            },

            // Game Actions
            toggleReady: function() {
                if (!this.roomId || this.mySeat === -1) return;
                socket.emit('ready', { room_id: this.roomId, ready: !this.isReady });
            },
            startGame: function() {
                if (!this.roomId || !this.isCreator) return;
                socket.emit('start_game', { room_id: this.roomId });
            },
            selectCard: function(card) {
                if (!this.isMyTurn || this.gameState.phase !== 'playing') return;
                if (!this.canPlayCard(card)) return;
                this.selectedCard = (this.selectedCard === card) ? null : card;
            },
            playSelectedCard: function() {
                if (!this.selectedCard || !this.isMyTurn) return;
                if (this.selectedCard.startsWith('W')) {
                    this.pendingCard = this.selectedCard;
                    this.showColorPicker = true;
                    return;
                }
                socket.emit('play_card', { room_id: this.roomId, card: this.selectedCard });
                this.selectedCard = null;
            },
            confirmColor: function(color) {
                if (!this.pendingCard) return;
                socket.emit('play_card', { room_id: this.roomId, card: this.pendingCard, chosen_color: color });
                this.pendingCard = null;
                this.showColorPicker = false;
                this.selectedCard = null;
            },
            drawCard: function() {
                if (!this.roomId || !this.isMyTurn) return;
                socket.emit('draw_card', { room_id: this.roomId });
            },
            sendMessage: function() {
                var msg = this.chatInput.trim();
                if (!msg || !this.roomId) return;
                this.chatInput = '';
                socket.emit('send_message', { room_id: this.roomId, message: msg });
            },

            // Helpers
            isCurrentTurn: function(player) {
                if (!player) return false;
                return this.gameState.current_turn === player.seat;
            },
            getHandCount: function(seat) {
                if (this.gameState.hands_count) {
                    var count = this.gameState.hands_count[String(seat)];
                    if (count !== undefined) return count;
                }
                if (seat === this.mySeat) return this.myCards.length;
                return 0;
            },
            canPlayCard: function(card) {
                if (!this.gameState.top_card) return true;
                if (card.startsWith('W')) return true;
                var topColor = this.gameState.top_color;
                var topValue = this.gameState.top_card.substring(1);
                var cardColor = card[0];
                var cardValue = card.substring(1);
                if (cardColor === topColor) return true;
                if (cardValue === topValue && !this.gameState.top_card.startsWith('W')) return true;
                return false;
            },
            cardColorClass: function(card) {
                if (card.startsWith('W')) return 'wild';
                return card[0];
            },
            cardText: function(card) {
                if (card.startsWith('W+4')) return '+4';
                if (card.startsWith('W+6')) return '+6';
                if (card.startsWith('W+10')) return '+10';
                if (card.startsWith('W')) return 'W';
                var val = card.substring(1);
                if (val === 'skip') return '禁';
                if (val === 'reverse') return '转';
                if (val === '+2') return '+2';
                if (val === '+6') return '+6';
                if (val === '+10') return '+10';
                return val;
            },
            cardColorIcon: function(card) {
                if (card.startsWith('W')) return '★';
                var c = card[0];
                if (c === 'R') return '●';
                if (c === 'Y') return '●';
                if (c === 'G') return '●';
                if (c === 'B') return '●';
                return '';
            },
            scrollToBottom: function() {
                var container = this.$refs.chatMessages;
                if (container) {
                    this.$nextTick(function() { container.scrollTop = container.scrollHeight; });
                }
            },
            formatTime: function(isoString) {
                if (!isoString) return '';
                var d = new Date(isoString);
                if (isNaN(d.getTime())) return isoString;
                return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
            },

            // Socket Events
            bindSocketEvents: function() {
                var self = this;
                socket.on('room_created', function(data) {
                    self.inRoom = true; self.mySeat = data.seat || 0; self.loadRoomDetail();
                });
                socket.on('room_joined', function(data) {
                    self.inRoom = true; self.mySeat = data.seat;
                    if (data.room) self.room = data.room;
                    self.loadRoomDetail();
                });
                socket.on('player_joined', function(data) {
                    if (data.players) self.room.players = data.players;
                    self.$message.info(data.username + ' 加入了房间');
                });
                socket.on('player_left', function(data) {
                    if (self.room && self.room.players && data.seat !== undefined) self.room.players[data.seat] = null;
                    self.$message.info(data.username + ' 离开了房间');
                });
                socket.on('player_ready', function(data) {
                    if (self.room && self.room.players && data.seat !== undefined) {
                        var p = self.room.players[data.seat];
                        if (p) p.ready = data.ready;
                    }
                });
                socket.on('game_started', function(data) {
                    self.room.status = 'playing';
                    self.gameState = {
                        phase: data.phase, current_turn: data.current_turn,
                        top_card: data.top_card, top_color: data.top_color,
                        direction: data.direction, hands_count: {}
                    };
                    if (data.hands) {
                        self.myCards = data.hands[String(self.mySeat)] || [];
                        for (var s in data.hands) self.gameState.hands_count[s] = data.hands[s].length;
                    }
                    self.selectedCard = null;
                    self.$message.success('游戏开始！');
                });
                socket.on('turn_changed', function(data) {
                    self.gameState.current_turn = data.seat;
                    self.selectedCard = null;
                });
                socket.on('card_played', function(data) {
                    self.gameState.top_card = data.top_card;
                    self.gameState.top_color = data.top_color;
                    if (self.gameState.hands_count) self.gameState.hands_count[String(data.seat)] = data.remaining;
                    if (data.seat === self.mySeat) {
                        var idx = self.myCards.indexOf(data.card);
                        if (idx !== -1) self.myCards.splice(idx, 1);
                        self.selectedCard = null;
                    }
                    var player = self.room.players[data.seat];
                    var name = player ? (player.nickname || player.username) : '玩家';
                    self.$message.info(name + ' 打出了一张牌');
                });
                socket.on('player_drew', function(data) {
                    if (data.seat === self.mySeat) {
                        if (data.cards) data.cards.forEach(function(c) { self.myCards.push(c); });
                    }
                    if (self.gameState.hands_count && data.seat !== undefined) {
                        var prev = self.gameState.hands_count[String(data.seat)] || 0;
                        self.gameState.hands_count[String(data.seat)] = prev + (data.count || 0);
                    }
                    var player = self.room.players[data.seat];
                    var name = player ? (player.nickname || player.username) : '玩家';
                    if (data.reason === 'penalty') self.$message.info(name + ' 被惩罚抽了 ' + data.count + ' 张牌');
                    else self.$message.info(name + ' 抽了 ' + data.count + ' 张牌');
                });
                socket.on('game_ended', function(data) {
                    self.room.status = 'ended';
                    self.gameState.phase = 'ended';
                    self.gameWinners = data.winners || [];
                    self.showGameOver = true;
                    if (data.game_state && data.game_state.hands) {
                        self.gameState.hands = data.game_state.hands;
                        if (self.mySeat !== -1 && data.game_state.hands[String(self.mySeat)]) {
                            self.myCards = data.game_state.hands[String(self.mySeat)];
                        }
                    }
                });
                socket.on('room_disbanded', function(data) {
                    self.$message.warning('房间已解散');
                    self.resetRoomState(); self.inRoom = false; self.roomId = ''; self.loadRooms();
                });
                socket.on('new_message', function(data) {
                    self.messages.push(data);
                    if (self.messages.length > 200) self.messages = self.messages.slice(-200);
                    self.scrollToBottom();
                });
                socket.on('error', function(data) {
                    console.error('Socket error:', data);
                    self.$message.error(data.message || '发生错误');
                });
            }
        }
    });

    window.UnoApp = app;
})();
