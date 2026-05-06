const PROXY_BASE = self.__PROXY_BASE__ || '';
const PROXY_TOKEN = self.__PROXY_TOKEN__ || '';

let fakeOrigin = '';
let baseScheme = 'https';
let baseHost = '';

function parseOrigin() {
    try {
        const url = new URL(location.href);
        let path = url.pathname || '/';
        if (path.startsWith('/')) path = path.substring(1);

        const schemeIdx = path.indexOf('://');
        if (schemeIdx > 0) {
            baseScheme = path.substring(0, schemeIdx);
            const rest = path.substring(schemeIdx + 3);
            const hostIdx = rest.indexOf('/');
            baseHost = hostIdx < 0 ? rest : rest.substring(0, hostIdx);
            fakeOrigin = `${baseScheme}://${baseHost}`;
        }
    } catch (e) {}
}

parseOrigin();

function rewriteUrl(url) {
    if (!url || typeof url !== 'string') return url;
    if (url.startsWith('data:') || url.startsWith('javascript:') ||
        url.startsWith('mailto:') || url.startsWith('blob:') ||
        url.startsWith('#') || url.startsWith('about:')) return url;
    if (url.includes(PROXY_BASE.replace(/^https?:\/\//, ''))) return url;

    let absoluteUrl;
    if (url.startsWith('//')) {
        absoluteUrl = `${baseScheme}:${url}`;
    } else if (url.startsWith('/')) {
        if (!fakeOrigin) return url;
        absoluteUrl = `${fakeOrigin}${url}`;
    } else if (!url.startsWith('http://') && !url.startsWith('https://')) {
        try {
            absoluteUrl = new URL(url, fakeOrigin || location.href).href;
        } catch (e) { return url; }
    } else {
        absoluteUrl = url;
    }

    try {
        const parsed = new URL(absoluteUrl);
        if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
            return `${PROXY_BASE}/${parsed.protocol.replace(':', '')}/${parsed.host}${parsed.pathname}${parsed.search}${parsed.hash}`;
        }
    } catch (e) {}

    return url;
}

function addProxyHeaders(headers) {
    if (!headers) headers = {};
    if (headers instanceof Headers) {
        headers.set('X-Proxy-Token', PROXY_TOKEN);
        headers.set('X-Proxy-Base', fakeOrigin);
    } else if (typeof headers === 'object') {
        headers['X-Proxy-Token'] = PROXY_TOKEN;
        headers['X-Proxy-Base'] = fakeOrigin;
    }
    return headers;
}

if ('serviceWorker' in navigator) {
    try {
        const swCode = `
            const PB = '${PROXY_BASE}';
            const PT = '${PROXY_TOKEN}';
            let FO = '${fakeOrigin}';
            let BS = '${baseScheme}';

            self.addEventListener('fetch', (event) => {
                const request = event.request;
                if (!PB || !FO) return;
                if (request.url.includes(PB.replace(/^https?:\/\//, ''))) return;

                let absoluteUrl;
                if (request.url.startsWith('//')) {
                    absoluteUrl = BS + ':' + request.url;
                } else if (request.url.startsWith('/')) {
                    absoluteUrl = FO + request.url;
                } else if (!request.url.startsWith('http://') && !request.url.startsWith('https://')) {
                    try { absoluteUrl = new URL(request.url, FO).href; } catch(e) { return; }
                } else {
                    absoluteUrl = request.url;
                }

                try {
                    const p = new URL(absoluteUrl);
                    if (p.protocol === 'http:' || p.protocol === 'https:') {
                        const newUrl = PB + '/' + p.protocol.replace(':', '') + '/' + p.host + p.pathname + p.search + p.hash;
                        const newRequest = new Request(newUrl, {
                            method: request.method,
                            headers: request.headers,
                            body: request.body,
                            mode: request.mode,
                            credentials: request.credentials,
                            cache: request.cache,
                            redirect: request.redirect
                        });
                        newRequest.headers.set('X-Proxy-Token', PT);
                        newRequest.headers.set('X-Proxy-Base', FO);
                        event.respondWith(fetch(newRequest).then(r => r).catch(() => fetch(request)));
                    }
                } catch(e) {}
            });
        `;

        const blob = new Blob([swCode], { type: 'application/javascript' });
        const swUrl = URL.createObjectURL(blob);

        navigator.serviceWorker.register(swUrl, { scope: PROXY_BASE + '/' }).then(reg => {
            console.log('[WebProxy] Service Worker 注册成功');
        }).catch(err => {
            console.log('[WebProxy] Service Worker 注册失败，使用 Hook 模式');
            initHookMode();
        });
    } catch (e) {
        initHookMode();
    }
} else {
    initHookMode();
}

function initHookMode() {
    var _origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {
        arguments[1] = rewriteUrl(url);
        return _origOpen.apply(this, arguments);
    };
    var _origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
    var _origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function(body) {
        addProxyHeaders(this._ph || {});
        _origSetHeader.call(this, 'X-Proxy-Token', PROXY_TOKEN);
        _origSetHeader.call(this, 'X-Proxy-Base', fakeOrigin);
        return _origSend.call(this, body);
    };

    if (window.fetch) {
        var _origFetch = window.fetch;
        window.fetch = function(input, init) {
            if (typeof input === 'string') {
                input = rewriteUrl(input); init = init || {};
            } else if (input instanceof Request) {
                input = new Request(rewriteUrl(input.url), input); init = init || {};
            } else {
                init = init || {};
            }
            init.headers = addProxyHeaders(init.headers) || new Headers();
            return _origFetch.call(this, input, init);
        };
    }

    var _origOpenWin = window.open;
    window.open = function(url) {
        if (url) arguments[0] = rewriteUrl(url);
        return _origOpenWin.apply(this, arguments);
    };

    if (window.history) {
        var _pushState = history.pushState;
        var _replaceState = history.replaceState;
        history.pushState = function(state, title, url) {
            if (url) arguments[2] = rewriteUrl(url);
            return _pushState.apply(this, arguments);
        };
        history.replaceState = function(state, title, url) {
            if (url) arguments[2] = rewriteUrl(url);
            return _replaceState.apply(this, arguments);
        };
    }

    if (window.EventSource) {
        var _ES = window.EventSource;
        window.EventSource = function(url, config) {
            if (url) url = rewriteUrl(url);
            return new _ES(url, config);
        };
        window.EventSource.prototype = _ES.prototype;
    }

    if (window.Image) {
        var _OrigImage = Image;
        window.Image = function() {
            var img = new (Function.prototype.bind.apply(_OrigImage, [null].concat(Array.from(arguments))))();
            var _src = Object.getOwnPropertyDescriptor(_OrigImage.prototype, 'src');
            Object.defineProperty(img, 'src', {
                get: function() { return img.getAttribute('src'); },
                set: function(v) { img.setAttribute('src', v); }
            });
            return img;
        };
        window.Image.prototype = _OrigImage.prototype;
    }

    var _srcDesc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
    if (_srcDesc && _srcDesc.set) {
        var _origSrcSet = _srcDesc.set;
        Object.defineProperty(HTMLImageElement.prototype, 'src', {
            get: function() { return this.getAttribute('src'); },
            set: function(v) {
                _origSrcSet.call(this, rewriteUrl(v));
            },
            configurable: true
        });
    }

    var _createEl = document.createElement.bind(document);
    document.createElement = function(tag) {
        var el = _createEl(tag);
        if (tag && ['script', 'img', 'link', 'iframe', 'source', 'video', 'audio'].indexOf(tag) >= 0) {
            var _setAttr = el.setAttribute.bind(el);
            el.setAttribute = function(k, v) {
                if ((k === 'src' || k === 'href' || k === 'data-src' || k === 'data-href' || k === 'poster' || k === 'background') && v) {
                    arguments[1] = rewriteUrl(v);
                }
                return _setAttr.apply(this, arguments);
            };
        }
        if (tag && tag.toLowerCase() === 'style') {
            var _cssTextDesc = Object.getOwnPropertyDescriptor(CSSStyleDeclaration.prototype, 'cssText');
            if (_cssTextDesc && _cssTextDesc.set) {
                var _origCssTextSet = _cssTextDesc.set;
                Object.defineProperty(el.style, 'cssText', {
                    set: function(v) {
                        _origCssTextSet.call(this, v.replace(/url\(\s*['"]?([^'"'\)]+)['"]?\s*\)/gi, function(m, u) {
                            return 'url(' + rewriteUrl(u) + ')';
                        }));
                    },
                    get: function() { return el.style.cssText; },
                    configurable: true
                });
            }
        }
        return el;
    };

    function rewriteAttrs(el) {
        if (!el || !el.getAttribute) return;
        var tag = el.tagName && el.tagName.toLowerCase();
        var attrs = ['href', 'src', 'action', 'data-src', 'data-href', 'poster', 'background'];
        for (var i = 0; i < attrs.length; i++) {
            var v = el.getAttribute(attrs[i]);
            if (v) el.setAttribute(attrs[i], rewriteUrl(v));
        }

        var ss = el.getAttribute('srcset');
        if (ss) {
            var parts = ss.split(',').map(function(p) {
                p = p.trim();
                var lastSpace = p.lastIndexOf(' ');
                if (lastSpace > 0) {
                    return rewriteUrl(p.substring(0, lastSpace).trim()) + ' ' + p.substring(lastSpace + 1);
                }
                return rewriteUrl(p);
            });
            el.setAttribute('srcset', parts.join(', '));
        }

        var st = el.getAttribute('style');
        if (st && st.indexOf('url(') >= 0) {
            st = st.replace(/url\(\s*['"]?([^'"'\)]+)['"]?\s*\)/gi, function(m, u) {
                return 'url(' + rewriteUrl(u) + ')';
            });
            el.setAttribute('style', st);
        }

        for (var c = el.children, j = 0; j < c.length; j++) {
            rewriteAttrs(c[j]);
        }
    }

    var _observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(m) {
            m.addedNodes.forEach(function(n) {
                if (n.nodeType === 1) rewriteAttrs(n);
            });
        });
    });

    if (document.documentElement) {
        _observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['src', 'href', 'style'] });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { rewriteAttrs(document.body); });
    } else {
        rewriteAttrs(document.body);
    }

    console.log('[WebProxy] Hook 模式已启动');
}

console.log('[WebProxy] 初始化完成');