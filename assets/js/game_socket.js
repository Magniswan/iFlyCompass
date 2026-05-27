(function() {
    'use strict';

    /**
     * GameSocket - Base Socket.IO helper for game modules
     * Provides auto-reconnection, event queuing, and connection state management
     */
    window.GameSocket = {
        socket: null,
        namespace: null,
        connected: false,
        reconnectAttempts: 0,
        maxReconnectAttempts: 5,
        reconnectDelay: 3000,
        eventQueue: [],
        listeners: {},

        connect: function(namespace, options) {
            var self = this;
            this.namespace = namespace || '/';
            options = options || {};

            if (this.socket) {
                this.socket.disconnect();
            }

            this.socket = io(namespace, {
                reconnection: true,
                reconnectionAttempts: this.maxReconnectAttempts,
                reconnectionDelay: this.reconnectDelay,
                transports: ['websocket', 'polling']
            });

            this.socket.on('connect', function() {
                console.log('[GameSocket] Connected to', namespace);
                self.connected = true;
                self.reconnectAttempts = 0;
                self._flushEventQueue();
            });

            this.socket.on('disconnect', function(reason) {
                console.log('[GameSocket] Disconnected:', reason);
                self.connected = false;
            });

            this.socket.on('connect_error', function(error) {
                console.error('[GameSocket] Connection error:', error);
                self.reconnectAttempts++;
                if (self.reconnectAttempts >= self.maxReconnectAttempts) {
                    console.error('[GameSocket] Max reconnect attempts reached');
                }
            });

            this.socket.on('error', function(data) {
                console.error('[GameSocket] Server error:', data);
                if (window.ELEMENT && window.ELEMENT.Message) {
                    window.ELEMENT.Message.error(data.message || '连接错误');
                }
            });

            return this.socket;
        },

        on: function(event, callback) {
            if (!this.socket) {
                console.warn('[GameSocket] Not connected, queueing listener for', event);
                if (!this.listeners[event]) {
                    this.listeners[event] = [];
                }
                this.listeners[event].push(callback);
                return;
            }
            this.socket.on(event, callback);
            if (!this.listeners[event]) {
                this.listeners[event] = [];
            }
            this.listeners[event].push(callback);
        },

        off: function(event, callback) {
            if (this.socket) {
                this.socket.off(event, callback);
            }
            if (this.listeners[event]) {
                var idx = this.listeners[event].indexOf(callback);
                if (idx !== -1) {
                    this.listeners[event].splice(idx, 1);
                }
            }
        },

        emit: function(event, data) {
            if (!this.socket || !this.connected) {
                console.warn('[GameSocket] Not connected, queueing event:', event);
                this.eventQueue.push({ event: event, data: data });
                return false;
            }
            this.socket.emit(event, data);
            return true;
        },

        disconnect: function() {
            if (this.socket) {
                this.socket.disconnect();
                this.socket = null;
            }
            this.connected = false;
            this.eventQueue = [];
        },

        _flushEventQueue: function() {
            while (this.eventQueue.length > 0) {
                var item = this.eventQueue.shift();
                console.log('[GameSocket] Flushing queued event:', item.event);
                this.socket.emit(item.event, item.data);
            }
        },

        _bindQueuedListeners: function() {
            for (var event in this.listeners) {
                if (this.listeners.hasOwnProperty(event)) {
                    this.listeners[event].forEach(function(callback) {
                        this.socket.on(event, callback);
                    }.bind(this));
                }
            }
        }
    };
})();
