(function() {
    'use strict';

    var socket = io('/game-uno-nomer');
    socket.on('connect', function() { console.log('[UNO No Mercy] Connected'); });
    socket.on('disconnect', function(r) { console.log('[UNO No Mercy] Disconnected:', r); });

    var app = new Vue({
        el: '#app',
        delimiters: ['[[', ']]'],
        data: {
            isCollapse: true,
            activeMenu: 'games',
            inRoom: false, roomId: '', rooms: [], room: {}, gameState: {},
            mySeat: -1, myCards: [],
            selectedCard: null,
            showColorPicker: false, pendingCard: null,
            showTargetPicker: false, pendingCard7: null,
            showColorRoulette: false,
            messages: [], chatInput: '', chatOpen: false,
            showCreateDialog: false, showPasswordDialog: false,
            joinPassword: '', pendingRoom: null,
            createForm: { name: '', password: '', maxPlayers: 8 },
            showGameOver: false, gameWinners: [], gameRankings: [],
            displayName: currentDisplayName, username: currentUsername,
            nickname: currentNickname, isAdmin: isAdminUser,
            userMenuVisible: false, unoCalled: false,
            handCounts: {}
        },
        computed: {
            otherPlayers: function() {
                if (!this.room || !this.room.players || this.mySeat === -1) return [];
                var r = [];
                for (var i = 0; i < this.room.players.length; i++) {
                    if (i !== this.mySeat && this.room.players[i]) r.push(this.room.players[i]);
                }
                return r;
            },
            activeOtherPlayers: function() {
                return this.otherPlayers.filter(function(p) { return !p.eliminated; });
            },
            currentTurnPlayer: function() {
                if (this.gameState.current_turn == null) return null;
                if (!this.room || !this.room.players) return null;
                return this.room.players[this.gameState.current_turn];
            },
            isMyTurn: function() {
                return this.mySeat !== -1 && this.gameState.current_turn === this.mySeat;
            },
            isPlayer: function() { return this.mySeat !== -1; },
            isCreator: function() { return this.room && this.room.creator_id === currentUserId; },
            isReady: function() {
                if (this.mySeat === -1 || !this.room || !this.room.players) return false;
                var p = this.room.players[this.mySeat];
                return p && p.ready;
            },
            canStartGame: function() {
                if (!this.room || !this.room.players) return false;
                var a = this.room.players.filter(function(p) { return p !== null; });
                return a.length >= 2 && a.every(function(p) { return p.ready; });
            },
            getReadyCount: function() {
                if (!this.room || !this.room.players) return 0;
                return this.room.players.filter(function(p) { return p && p.ready; }).length;
            },
            getPlayerCount: function() {
                if (!this.room || !this.room.players) return 0;
                return this.room.players.filter(function(p) { return p !== null; }).length;
            },
            deckCount: function() { return this.gameState.deck_count || 0; },
            isEliminated: function() {
                if (this.mySeat === -1 || !this.room || !this.room.players) return false;
                var p = this.room.players[this.mySeat];
                return p && p.eliminated;
            },
            myHandSize: function() {
                return this.myCards.length;
            }
        },
        mounted: function() {
            this.loadRooms();
            this.bindAllEvents();
            document.addEventListener('click', this.closeUserMenu);
        },
        beforeDestroy: function() {
            document.removeEventListener('click', this.closeUserMenu);
        },
        methods: {
            toggleCollapse: function() { this.isCollapse = !this.isCollapse; },
            toggleUserMenu: function() { this.userMenuVisible = !this.userMenuVisible; },
            closeUserMenu: function(e) {
                if (!e.target.closest('.user-menu-container')) this.userMenuVisible = false;
            },
            openProfileDialog: function() { this.userMenuVisible = false; },
            confirmLogout: function() {
                this.userMenuVisible = false;
                this.$confirm('确定退出登录？', '提示', { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' })
                    .then(function() { window.location.href = '/logout'; }).catch(function() {});
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

            // ===== Room Management =====
            loadRooms: function() {
                var s = this;
                fetch('/api/uno-nomer/rooms')
                    .then(function(r) { return r.json(); })
                    .then(function(d) {
                        if (Array.isArray(d)) s.rooms = d;
                        else if (d.error) s.$message.error(d.error);
                    }).catch(function() { s.$message.error('加载房间列表失败'); });
            },
            createRoom: function() {
                var s = this, n = this.createForm.name.trim();
                if (!n) { this.$message.warning('请输入房间名称'); return; }
                fetch('/api/uno-nomer/rooms', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: n, password: this.createForm.password || undefined, max_players: this.createForm.maxPlayers })
                }).then(function(r) { return r.json(); })
                .then(function(d) {
                    if (d.error) { s.$message.error(d.error); return; }
                    s.showCreateDialog = false; s.createForm = { name: '', password: '', maxPlayers: 8 };
                    s.roomId = d.room_id; s.room = d; s.messages = []; s.resetGameState();
                    socket.emit('create_room', { room_id: d.room_id });
                }).catch(function() { s.$message.error('创建房间失败'); });
            },
            onJoinRoomClick: function(item) {
                if (item.has_password) { this.pendingRoom = item; this.joinPassword = ''; this.showPasswordDialog = true; }
                else this.joinRoom(item);
            },
            confirmJoinPassword: function() {
                if (this.pendingRoom) this.joinRoom(this.pendingRoom, this.joinPassword);
                this.showPasswordDialog = false; this.pendingRoom = null; this.joinPassword = '';
            },
            joinRoom: function(item, pw) {
                var s = this;
                fetch('/api/uno-nomer/rooms/' + item.room_id + '/join', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(pw ? { password: pw } : {})
                }).then(function(r) {
                    if (r.status === 401) { s.$message.error('密码错误'); throw new Error('pw'); }
                    return r.json();
                }).then(function(d) {
                    if (d.error) { s.$message.error(d.error); return; }
                    s.roomId = item.room_id; s.room = d; s.messages = []; s.resetGameState();
                    socket.emit('join_room', { room_id: item.room_id });
                }).catch(function(e) { if (e.message !== 'pw') s.$message.error('加入房间失败'); });
            },
            goBack: function() {
                if (this.inRoom && this.roomId) socket.emit('leave_room', { room_id: this.roomId });
                this.resetRoomState(); this.inRoom = false; this.roomId = ''; this.loadRooms();
            },
            resetRoomState: function() {
                this.room = {}; this.gameState = {}; this.mySeat = -1; this.myCards = [];
                this.selectedCard = null; this.showColorPicker = false; this.pendingCard = null;
                this.showTargetPicker = false; this.pendingCard7 = null; this.showColorRoulette = false;
                this.messages = []; this.showGameOver = false; this.gameWinners = []; this.gameRankings = [];
                this.chatOpen = false; this.unoCalled = false; this.handCounts = {};
            },
            resetGameState: function() {
                this.gameState = {}; this.myCards = []; this.selectedCard = null;
                this.showGameOver = false; this.gameWinners = []; this.gameRankings = [];
                this.showColorPicker = false; this.pendingCard = null;
                this.showTargetPicker = false; this.pendingCard7 = null; this.showColorRoulette = false;
                this.unoCalled = false; this.handCounts = {};
            },
            loadRoomDetail: function() {
                if (!this.roomId) return;
                var s = this;
                fetch('/api/uno-nomer/rooms/' + this.roomId)
                    .then(function(r) { return r.json(); })
                    .then(function(d) {
                        if (d.error) return;
                        s.room = d; s.gameState = d.game_state || {}; s.messages = d.messages || [];
                        if (s.mySeat === -1 && d.players) {
                            for (var i = 0; i < d.players.length; i++) {
                                if (d.players[i] && d.players[i].user_id === currentUserId) { s.mySeat = i; break; }
                            }
                        }
                    }).catch(function() {});
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
            selectCard: function(card) {
                if (!this.isMyTurn || this.gameState.phase !== 'playing' || this.isEliminated) return;
                if (!this.canPlayCard(card)) return;
                this.selectedCard = (this.selectedCard === card) ? null : card;
            },
            canPlayCard: function(card) {
                if (!this.gameState.top_card) return true;
                var ds = this.gameState.draw_stack || 0, cv = card.substring(1);
                if (ds > 0) {
                    var dv = 0;
                    if (cv === '+2') dv = 2;
                    else if (cv === '+4' || card === 'NR+4') dv = 4;
                    else if (cv === '+6') dv = 6;
                    else if (cv === '+10') dv = 10;
                    return dv >= ds;
                }
                if (card === 'W' || card === 'W+4' || card === 'SE' || card === 'N+4' || card === 'NR+4' || card === 'CR' || card === 'N+6' || card === 'N+10') return true;
                var tc = this.gameState.top_color, tv = this.gameState.top_card.substring(1);
                var cc = card[0];
                if (cc === tc) return true;
                if (cv === tv && this.gameState.top_card[0] !== 'W' && this.gameState.top_card !== 'SE' && this.gameState.top_card !== 'CR' && this.gameState.top_card.substring(0,2) !== 'N+' && this.gameState.top_card !== 'NR+4' && this.gameState.top_card !== 'W+4') return true;
                return false;
            },
            playSelectedCard: function() {
                if (!this.selectedCard || !this.isMyTurn) return;
                var card = this.selectedCard, cv = card.substring(1);
                if (cv === '7' && this.activeOtherPlayers.length > 0) {
                    this.pendingCard7 = card; this.showTargetPicker = true; return;
                }
                if (card === 'W' || card === 'W+4' || card === 'SE' || card === 'N+4' || card === 'NR+4' || card === 'CR' || card === 'N+6' || card === 'N+10') {
                    this.pendingCard = card; this.showColorPicker = true; return;
                }
                socket.emit('play_card', { room_id: this.roomId, card: card });
                this.selectedCard = null;
            },
            confirmColor: function(color) {
                if (!this.pendingCard) return;
                socket.emit('play_card', { room_id: this.roomId, card: this.pendingCard, chosen_color: color });
                this.pendingCard = null; this.showColorPicker = false; this.selectedCard = null;
            },
            confirmTarget: function(targetSeat) {
                if (!this.pendingCard7) return;
                socket.emit('play_card', { room_id: this.roomId, card: this.pendingCard7, target_seat: targetSeat });
                this.pendingCard7 = null; this.showTargetPicker = false; this.selectedCard = null;
            },
            pickColorRoulette: function(color) {
                socket.emit('color_roulette_pick', { room_id: this.roomId, color: color });
                this.showColorRoulette = false;
            },
            callUno: function() {
                if (!this.roomId || this.mySeat === -1) return;
                socket.emit('call_uno', { room_id: this.roomId });
                this.unoCalled = true;
                this.$message.success('UNO!');
            },
            catchUno: function(seat) {
                if (!this.roomId) return;
                socket.emit('catch_uno', { room_id: this.roomId, target_seat: seat });
            },
            drawCard: function() {
                if (!this.roomId || !this.isMyTurn || this.isEliminated) return;
                socket.emit('draw_card', { room_id: this.roomId });
            },
            sendMessage: function() {
                var m = this.chatInput.trim();
                if (!m || !this.roomId) return;
                this.chatInput = '';
                socket.emit('send_message', { room_id: this.roomId, message: m });
            },

            // ===== Display Helpers =====
            isCurrentTurn: function(p) { return p && this.gameState.current_turn === p.seat; },
            getHandCount: function(seat) {
                if (this.handCounts[String(seat)] !== undefined) {
                    return this.handCounts[String(seat)];
                }
                return 0;
            },
            getPlayerName: function(seat) {
                if (!this.room || !this.room.players || seat == null) return '未知';
                var p = this.room.players[seat];
                return p ? (p.nickname || p.username) : '未知';
            },
            sortCards: function() {
                var colorOrder = { R: 0, Y: 1, G: 2, B: 3 };
                this.myCards.sort(function(a, b) {
                    var ca = (a[0] === 'W' || a === 'SE' || a === 'CR' || a[0] === 'N') ? 'Z' : (a[0] || 'Z');
                    var cb = (b[0] === 'W' || b === 'SE' || b === 'CR' || b[0] === 'N') ? 'Z' : (b[0] || 'Z');
                    var oa = colorOrder[ca] !== undefined ? colorOrder[ca] : 99;
                    var ob = colorOrder[cb] !== undefined ? colorOrder[cb] : 99;
                    if (oa !== ob) return oa - ob;
                    var va = a.substring(1), vb = b.substring(1);
                    var na = parseInt(va), nb = parseInt(vb);
                    if (!isNaN(na) && !isNaN(nb)) return na - nb;
                    return va < vb ? -1 : va > vb ? 1 : 0;
                });
            },
            cardColorClass: function(card) {
                if (card === 'W' || card === 'W+4' || card === 'SE' || card === 'N+4' || card === 'NR+4' || card === 'CR' || card === 'N+6' || card === 'N+10') return 'wild';
                return card[0];
            },
            cardText: function(card) {
                var vals = {
                    'W': 'W', 'W+4': '+4', 'SE': '全跳', 'N+4': '+4', 'NR+4': '反+4',
                    'CR': '罚抽', 'N+6': '+6', 'N+10': '+10',
                    'skip': '禁', 'rev': '转', '+2': '+2', 'ac': '全弃'
                };
                var cv = card.substring(1);
                if (vals[cv]) return vals[cv];
                if (vals[card]) return vals[card];
                return cv;
            },
            cardTitle: function(card) {
                var names = {
                    'W': '变色', 'W+4': '+4', 'SE': '全场跳过', 'N+4': '+4',
                    'NR+4': '反转+4', 'CR': '罚抽颜色', 'N+6': '+6', 'N+10': '+10',
                    'skip': '禁止', 'rev': '反转', '+2': '+2', 'ac': '同色全弃'
                };
                var cv = card.substring(1);
                if (names[cv]) return names[cv];
                if (names[card]) return names[card];
                return card;
            },
            cardColorIcon: function(card) {
                if (card[0] === 'W' || card === 'SE' || card === 'N+4' || card === 'NR+4' || card === 'CR' || card === 'N+6' || card === 'N+10') return '\u2605';
                return '\u25cf';
            },
            scrollToBottom: function() {
                var c = this.$refs.chatMessages;
                if (c) this.$nextTick(function() { c.scrollTop = c.scrollHeight; });
            },

            // ===== Socket Events (organized by group) =====
            bindAllEvents: function() {
                this._bindRoomEvents();
                this._bindGameFlowEvents();
                this._bindCardEvents();
                this._bindSpecialEffects();
                this._bindChatEvents();
            },

            _bindRoomEvents: function() {
                var s = this;
                socket.on('room_created', function(d) { s.inRoom = true; s.mySeat = d.seat || 0; s.loadRoomDetail(); });
                socket.on('room_joined', function(d) { s.inRoom = true; s.mySeat = d.seat; if (d.room) s.room = d.room; s.loadRoomDetail(); });
                socket.on('player_joined', function(d) {
                    if (d.players) s.room.players = d.players;
                    s.$message.info(d.username + ' 加入了房间');
                });
                socket.on('player_left', function(d) {
                    if (s.room && s.room.players && d.seat != null) s.room.players[d.seat] = null;
                    s.$message.info(d.username + ' 离开了房间');
                });
                socket.on('player_ready', function(d) {
                    if (s.room && s.room.players && d.seat != null) {
                        var p = s.room.players[d.seat]; if (p) p.ready = d.ready;
                    }
                });
                socket.on('room_disbanded', function(d) {
                    s.$message.warning('房间已解散');
                    s.resetRoomState(); s.inRoom = false; s.roomId = ''; s.loadRooms();
                });
                socket.on('error', function(d) {
                    s.$message.error(d.message || '发生错误');
                });
            },

            _bindGameFlowEvents: function() {
                var s = this;
                socket.on('game_started', function(d) {
                    s.room.status = 'playing';
                    s.gameState = {
                        phase: d.phase, current_turn: d.current_turn,
                        top_card: d.top_card, top_color: d.top_color,
                        direction: d.direction, draw_stack: 0,
                        rankings: [], hands: d.hands || {}
                    };
                    if (d.hand_counts) s.handCounts = d.hand_counts;
                    if (d.hands) {
                        s.myCards = d.hands[String(s.mySeat)] || [];
                        s.sortCards();
                    }
                    s.selectedCard = null; s.unoCalled = false;
                    s.$message.success('UNO No Mercy 开始！');
                });
                socket.on('turn_changed', function(d) {
                    s.gameState.current_turn = d.seat;
                    if (d.draw_stack !== undefined) s.gameState.draw_stack = d.draw_stack;
                    s.selectedCard = null; s.unoCalled = false;
                });
                socket.on('game_ended', function(d) {
                    s.room.status = 'ended'; s.gameState.phase = 'ended';
                    s.gameRankings = d.rankings || []; s.showGameOver = true;
                });
            },

            _bindCardEvents: function() {
                var s = this;
                socket.on('card_played', function(d) {
                    s.$set(s.gameState, 'top_card', d.top_card);
                    s.$set(s.gameState, 'top_color', d.top_color);
                    if (d.draw_stack !== undefined) s.gameState.draw_stack = d.draw_stack;
                    if (d.hand_counts) s.handCounts = d.hand_counts;
                    if (d.seat === s.mySeat) {
                        var idx = s.myCards.indexOf(d.card);
                        if (idx !== -1) s.myCards.splice(idx, 1);
                        s.selectedCard = null;
                    }
                    if (d.effects && d.effects.length > 0) {
                        d.effects.forEach(function(eff) {
                            if (eff.startsWith('all_discard_')) {
                                var color = eff.split('_')[2];
                                s.myCards = s.myCards.filter(function(c) {
                                    return s.cardColorClass(c) !== color;
                                });
                            }
                        });
                    }
                    s.sortCards();
                    var p = s.room.players[d.seat], n = p ? (p.nickname || p.username) : '玩家';
                    var msg = n + ' 打出 ' + s.cardText(d.card);
                    if (d.auto_play) msg += ' (自动)';
                    if (d.effects && d.effects.length > 0) msg += ' [' + d.effects.join(',') + ']';
                    s.$message.info(msg);
                });

                socket.on('player_drew', function(d) {
                    if (d.seat === s.mySeat && d.cards) {
                        d.cards.forEach(function(c) { s.myCards.push(c); });
                        if (d.auto_played) {
                            var ai = s.myCards.indexOf(d.auto_played);
                            if (ai !== -1) s.myCards.splice(ai, 1);
                        }
                        s.sortCards();
                    }
                    if (d.hand_counts) s.handCounts = d.hand_counts;
                    var p = s.room.players[d.seat], n = p ? (p.nickname || p.username) : '玩家';
                    if (d.reason === 'stack_penalty') s.$message.error(n + ' 接受了惩罚，抽了 ' + d.count + ' 张牌！');
                    else if (d.reason === 'color_roulette') s.$message.warning(n + ' 被罚抽颜色，抽了 ' + d.count + ' 张');
                    else if (d.auto_played) s.$message.info(n + ' 抽了 ' + d.count + ' 张，自动打出 ' + s.cardText(d.auto_played));
                    else s.$message.info(n + ' 抽了 ' + d.count + ' 张');
                });

                socket.on('player_eliminated', function(d) {
                    if (s.room && s.room.players && d.seat != null) {
                        var p = s.room.players[d.seat];
                        if (p) p.eliminated = true;
                    }
                    if (s.gameState.rankings && d.seat != null) {
                        if (s.gameState.rankings.indexOf(d.seat) === -1) s.gameState.rankings.push(d.seat);
                    }
                    var p = s.room.players[d.seat], n = p ? (p.nickname || p.username) : '玩家';
                    if (d.reason === 'empty_hand') s.$message.success(n + ' 出完手牌，排名第' + (d.rank || '?') + '！');
                    else s.$message.error(n + ' 手牌≥25张被淘汰！排名第' + (d.rank || '?'));
                });
            },

            _bindSpecialEffects: function() {
                var s = this;
                socket.on('hands_swapped', function(d) {
                    if (d.hands) {
                        if (d.hands[String(s.mySeat)]) {
                            s.myCards = d.hands[String(s.mySeat)].slice();
                            s.sortCards();
                        }
                    }
                    if (d.seat1 === s.mySeat || d.seat2 === s.mySeat) {
                        s.$message.warning('手牌已交换！');
                    }
                });

                socket.on('hands_passed', function(d) {
                    if (d.hands) {
                        if (d.hands[String(s.mySeat)]) {
                            s.myCards = d.hands[String(s.mySeat)].slice();
                            s.sortCards();
                        }
                    }
                    s.$message.warning('手牌已传递！');
                });

                socket.on('hands_updated', function(d) {
                    if (d.hands_count) {
                        s.handCounts = d.hands_count;
                        if (d.hands_count[String(s.mySeat)] !== undefined) {
                            var expected = d.hands_count[String(s.mySeat)];
                            s.myCards = s.myCards.slice(0, expected);
                            s.sortCards();
                        }
                    }
                });

                socket.on('color_roulette', function(d) {
                    if (d.seat === s.mySeat) {
                        s.showColorRoulette = true;
                        s.$message.warning('请选择一种颜色来接受罚抽！');
                    }
                });

                socket.on('uno_called', function(d) {
                    s.$message.info((d.nickname || d.username) + ' 喊了 UNO！');
                });

                socket.on('uno_penalty', function(d) {
                    if (d.seat === s.mySeat) {
                        s.$message.error('你忘记喊UNO，被罚抽2张牌！');
                        s.unoCalled = false;
                    }
                });
            },

            _bindChatEvents: function() {
                var s = this;
                socket.on('new_message', function(d) {
                    s.messages.push(d);
                    if (s.messages.length > 200) s.messages = s.messages.slice(-200);
                    s.scrollToBottom();
                });
            }
        }
    });
    window.UnoNoMercyApp = app;
})();
