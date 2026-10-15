/**
 * SmartAgents Widget embed loader (plugin)
 *
 * Host page usage (any web app):
 *   <script
 *     src="http://127.0.0.1:8000/embed.js"
 *     data-api-base="http://127.0.0.1:8000"
 *     data-title="SmartAgents"
 *     data-position="bottom-right"
 *     async
 *   ></script>
 *
 * Or:
 *   window.SMART_AGENTS_WIDGET = { url: 'http://127.0.0.1:8000', title: 'SmartAgents' };
 *   then load /embed.js
 *
 * Does not modify host app logic: injects a floating button + iframe only.
 */
(function () {
  'use strict';

  if (window.__SmartAgentsWidgetLoaded) return;
  window.__SmartAgentsWidgetLoaded = true;

  var script = document.currentScript;
  var cfg = window.SMART_AGENTS_WIDGET || {};
  var apiBase = (
    (script && script.getAttribute('data-api-base')) ||
    cfg.url ||
    cfg.apiBase ||
    'http://127.0.0.1:8000'
  ).replace(/\/$/, '');
  var title = (script && script.getAttribute('data-title')) || cfg.title || 'SmartAgents';
  var position = (script && script.getAttribute('data-position')) || cfg.position || 'bottom-right';
  var zIndex = String((script && script.getAttribute('data-z-index')) || cfg.zIndex || 2147483000);
  var openByDefault = String(
    (script && script.getAttribute('data-open')) || cfg.open || 'false'
  ).toLowerCase();
  var startOpen = openByDefault === '1' || openByDefault === 'true' || openByDefault === 'yes';

  var CSS = [
    '#sa-widget-root{all:initial;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}',
    '#sa-widget-root *{box-sizing:border-box}',
    '#sa-widget-btn{position:fixed;width:56px;height:56px;border:none;border-radius:50%;',
    'background:#00a1d6;color:#fff;font-size:22px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.18);',
    'z-index:' + zIndex + ';line-height:56px;text-align:center;padding:0}',
    '#sa-widget-btn:hover{filter:brightness(1.05)}',
    '#sa-widget-panel{position:fixed;width:min(400px,calc(100vw - 24px));height:min(560px,calc(100vh - 100px));',
    'background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 8px 28px rgba(0,0,0,.22);',
    'z-index:' + zIndex + ';display:none;border:1px solid rgba(0,0,0,.06)}',
    '#sa-widget-panel.sa-open{display:block}',
    '#sa-widget-frame{width:100%;height:100%;border:0;display:block;background:#fff}',
    '#sa-widget-root.sa-br #sa-widget-btn{right:20px;bottom:20px}',
    '#sa-widget-root.sa-br #sa-widget-panel{right:20px;bottom:88px}',
    '#sa-widget-root.sa-bl #sa-widget-btn{left:20px;bottom:20px}',
    '#sa-widget-root.sa-bl #sa-widget-panel{left:20px;bottom:88px}'
  ].join('');

  function posClass(p) {
    return p === 'bottom-left' ? 'sa-bl' : 'sa-br';
  }

  function ensureDom() {
    if (document.getElementById('sa-widget-root')) return;

    var style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);

    var root = document.createElement('div');
    root.id = 'sa-widget-root';
    root.className = posClass(position);
    root.setAttribute('data-smart-agents-widget', '1');

    var btn = document.createElement('button');
    btn.id = 'sa-widget-btn';
    btn.type = 'button';
    btn.title = title;
    btn.setAttribute('aria-label', title);
    btn.textContent = '\uD83D\uDCAC';

    var panel = document.createElement('div');
    panel.id = 'sa-widget-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', title);

    var iframe = document.createElement('iframe');
    iframe.id = 'sa-widget-frame';
    iframe.title = title;
    iframe.allow = 'clipboard-write';
    iframe.src = apiBase + '/?embed=1';

    panel.appendChild(iframe);
    root.appendChild(panel);
    root.appendChild(btn);
    document.body.appendChild(root);

    btn.addEventListener('click', function () {
      panel.classList.toggle('sa-open');
    });

    if (startOpen) panel.classList.add('sa-open');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ensureDom);
  } else {
    ensureDom();
  }
})();
