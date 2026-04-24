(function() {
  'use strict';

  var _reqId = 0;
  var _pending = {};
  var _ready = false;
  var _capabilities = {};
  var _theme = {};
  var _onToolResult = null;
  var _onThemeChanged = null;
  var _onReady = null;

  function _nextId() { return ++_reqId; }

  function _sendRpc(method, params, id) {
    var msg = { jsonrpc: '2.0', method: method };
    if (params !== undefined) msg.params = params;
    if (id !== undefined) msg.id = id;
    window.parent.postMessage(msg, '*');
    return msg;
  }

  function _request(method, params) {
    return new Promise(function(resolve, reject) {
      var id = _nextId();
      _pending[id] = { resolve: resolve, reject: reject };
      _sendRpc(method, params, id);
      setTimeout(function() {
        if (_pending[id]) {
          _pending[id].reject(new Error('Timeout: ' + method));
          delete _pending[id];
        }
      }, 300000);
    });
  }

  window.addEventListener('message', function(e) {
    var d = e.data;
    if (!d || typeof d !== 'object') return;

    if (d.jsonrpc === '2.0') {
      if (d.id !== undefined && _pending[d.id]) {
        if (d.error) {
          _pending[d.id].reject(new Error(d.error.message || 'RPC error'));
        } else {
          _pending[d.id].resolve(d.result);
        }
        delete _pending[d.id];
        return;
      }

      if (d.method === 'ui/notifications/tool-result') {
        if (_onToolResult) _onToolResult(d.params);
      } else if (d.method === 'ui/notifications/themeChanged') {
        _theme = d.params || {};
        if (_onThemeChanged) _onThemeChanged(_theme);
        _applyTheme(_theme);
      } else if (d.method === 'ui/notifications/requestTeardown') {
        _ready = false;
      }
      return;
    }

    if (d.type === 'artifact_command') {
      if (d.action === 'refresh') window.location.reload();
      if (window.onArtifactCommand) window.onArtifactCommand(d);
    }
  });

  function _applyTheme(theme) {
    if (!theme.cssVariables) return;
    var root = document.documentElement;
    Object.keys(theme.cssVariables).forEach(function(k) {
      root.style.setProperty(k, theme.cssVariables[k]);
    });
  }

  function _initialize() {
    return _request('ui/initialize', {
      name: document.title || 'Artifact',
      version: '1.0.0',
      capabilities: { tools: true, messages: true }
    }).then(function(result) {
      _capabilities = result || {};
      _theme = _capabilities.theme || {};
      _ready = true;
      if (_theme.cssVariables) _applyTheme(_theme);
      if (_onReady) _onReady(_capabilities);
      return _capabilities;
    }).catch(function() {
      _ready = true;
      if (_onReady) _onReady({});
    });
  }

  var app = {
    callTool: function(name, args) {
      return _request('tools/call', { name: name, arguments: args || {} });
    },

    message: function(text) {
      return _request('ui/requests/message', { text: text });
    },

    setDisplayMode: function(mode) {
      return _request('ui/requests/setDisplayMode', { mode: mode });
    },

    openLink: function(url) {
      return _request('ui/requests/openLink', { url: url });
    },

    get ready() { return _ready; },
    get capabilities() { return _capabilities; },
    get theme() { return _theme; },

    set ontoolresult(fn) { _onToolResult = fn; },
    set onthemechanged(fn) { _onThemeChanged = fn; },
    set onready(fn) { _onReady = fn; },
  };

  window.app = app;

  window.artifactMessage = function(text) {
    if (_ready) {
      app.message(text);
    } else {
      window.parent.postMessage({
        type: 'artifact', action: 'chat_message', payload: { text: text }
      }, '*');
    }
  };

  _initialize();
})();
