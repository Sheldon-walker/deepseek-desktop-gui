"""整窗外壳页面：侧边栏 + 顶栏 + 对话区 + 检索栏 + 输入栏，全部是一个 HTML 页面。

窗口缩放/拖拽时由浏览器重排，不再逐个 Tk 控件重绘画布（那是 Windows 上卡帧的根因）。
聊天消息渲染直接复用 ui/chat_html.py 里的 CSS/JS，检索栏复用 ui/panel_html.py 的样式。
"""

from __future__ import annotations

from .assets import data_uri as _data_uri
from .chat_html import CHAT_CSS, CHAT_JS_BARE
from .panel_html import PANEL_CSS


ICONS = {
    "@LOGO@": _data_uri("app-logo.png", 60, pad=True),
    "@MIC@": _data_uri("ui-icons_03-microphone-black.png", 36),
    "@CLIP@": _data_uri("ui-icons_04-paperclip-black.png", 36),
    "@THINK_ON@": _data_uri("ui-icons_01-deep-think-blue.png", 32),
    "@THINK_OFF@": _data_uri("ui-icons_06-deep-think-black.png", 32),
    "@WEB_ON@": _data_uri("ui-icons_02-smart-search-blue.png", 32),
    "@WEB_OFF@": _data_uri("ui-icons_07-smart-search-black.png", 32),
    "@SEND_ON@": _data_uri("ui-icons_08-send-active.png", 68),
    "@SEND_OFF@": _data_uri("ui-icons_05-send-disabled.png", 68),
    "@WHALE@": _data_uri("deepseek-whale-blue.png", 56, pad=True),
    "@SEARCH@": _data_uri("ui-icons_02-smart-search-blue.png", 30),
}

SHELL_CSS = r"""
/* ---------- 外壳布局 ---------- */
/* 让原生控件（复选框、下拉箭头、滚动条）在深色下也走深色 */
body.dark{color-scheme:dark}
html,body{margin:0 !important;padding:0 !important;height:100%;overflow:hidden}
#app{display:flex;height:100%;overflow:hidden}
body.side-off #side,body.side-off #side-grip{display:none}
#side{width:var(--sidew,268px);flex-shrink:0;background:#f7f8fa;display:flex;flex-direction:column;border-right:1px solid var(--border-soft);position:relative}
#side-grip{position:absolute;top:0;right:-3px;bottom:0;width:6px;cursor:col-resize;z-index:20}
#side-grip:hover{background:var(--accent-soft)}
body.dark #side{background:#1b1d21}
#side .brand{height:56px;display:flex;align-items:center;gap:7px;padding:0 12px 0 14px;flex-shrink:0}
#side .brand-left{display:flex;align-items:center;gap:7px;flex:1;min-width:0;overflow:hidden}
#side .brand img{width:28px;height:28px;object-fit:contain;display:block;flex-shrink:0}
#side .brand .word{font-size:21px;font-weight:700;color:#0d2452;letter-spacing:-.4px;white-space:nowrap;overflow:hidden;min-width:0}
#side .brand .word.clipped{-webkit-mask-image:linear-gradient(to right,#000 calc(100% - 22px),transparent 100%);mask-image:linear-gradient(to right,#000 calc(100% - 22px),transparent 100%)}
body.dark #side .brand .word{color:#dfe4ff}
#side-tools{display:flex;align-items:center;justify-content:flex-end;gap:2px;flex-shrink:0}
.side-ico{width:30px;height:30px;border:none;border-radius:8px;background:transparent;color:var(--text-soft);cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0}
.side-ico:hover{background:var(--surface-soft);color:var(--text)}
.side-ico.on{background:var(--accent-soft);color:var(--accent)}
.side-ico svg{width:18px;height:18px;display:block}
#new{position:relative;margin:2px 14px 10px;height:40px;border-radius:12px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:14px;font-weight:600;cursor:pointer;display:flex;align-items:center;justify-content:center}
#new .n-txt{position:relative;display:inline-block}
#new .n-ico{position:absolute;right:calc(100% + 8px);top:50%;transform:translateY(-50%);font-size:15px;line-height:1;opacity:.7;font-style:normal}
#new:hover{background:var(--surface-soft);border-color:var(--accent-soft)}
#sessions{flex:1;overflow-y:auto;overflow-x:hidden;padding:0 14px 8px}
#sessions::-webkit-scrollbar{width:9px}
#sessions::-webkit-scrollbar-thumb{background:var(--border);border-radius:5px}
.s-item{position:relative;border-radius:8px;padding:8px 10px;margin-bottom:4px;cursor:pointer}
.s-item:hover{background:#eef0f4}
body.dark .s-item:hover{background:#26282d}
.s-item.active{background:var(--accent-soft)}
.s-item.active .s-title{color:var(--accent)}
.pin-dot{position:absolute;right:8px;bottom:6px;color:var(--accent);font-size:11px;line-height:1}
.s-title{font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.5}
.s-meta{font-size:11px;color:var(--text-dim);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.s-more{position:absolute;right:6px;top:50%;transform:translateY(-50%);width:22px;height:22px;border-radius:6px;border:none;background:transparent;color:var(--text-dim);cursor:pointer;opacity:0;font-size:14px;line-height:1}
.s-item:hover .s-more{opacity:1}
.s-more:hover{background:var(--card);color:var(--text)}
.s-menu{position:absolute;right:6px;top:28px;z-index:30;background:var(--bg);border:1px solid var(--border);border-radius:8px;box-shadow:0 6px 20px rgba(0,0,0,.12);padding:4px;min-width:100px}
.s-menu button{display:block;width:100%;text-align:left;border:none;background:transparent;color:var(--text);font-size:12.5px;padding:6px 10px;border-radius:6px;cursor:pointer}
.s-menu button:hover{background:var(--surface-soft)}
.s-menu button.danger{color:var(--danger)}
/* 多选模式 */
body.multi-mode .s-item{cursor:default}
.s-check{display:none;position:absolute;left:3px;top:50%;transform:translateY(-50%);width:17px;height:17px;accent-color:var(--accent);z-index:2}
body.multi-mode .s-check{display:block}
body.multi-mode .s-item{padding-left:38px}
body.multi-mode .s-more{display:none}
#multi-bar{display:none;align-items:center;gap:8px;padding:8px 14px;border-top:1px solid var(--border-soft);flex-shrink:0;overflow-x:auto;overflow-y:hidden;scrollbar-width:thin}
#multi-bar.on{display:flex}
#multi-bar::-webkit-scrollbar{height:6px}
#multi-bar::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
#multi-bar button{height:30px;padding:0 11px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text-soft);font-size:12px;cursor:pointer;white-space:nowrap;flex-shrink:0}
#multi-bar button:hover{background:var(--surface-soft);color:var(--text)}
#multi-bar button.danger{color:var(--danger);border-color:var(--danger)}
#multi-bar button.danger:hover{background:rgba(229,72,77,.1)}
/* 搜索浮层：整窗模糊背景 + 居中搜索框 */
#search-mask{position:fixed;inset:0;z-index:50;display:none;align-items:flex-start;justify-content:center;padding-top:16vh;background:rgba(120,124,132,.42);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}
#search-mask.on{display:flex}
#search-box{width:min(620px,86vw);display:flex;align-items:center;gap:10px;background:var(--bg);border-radius:16px;padding:10px 16px;box-shadow:0 12px 40px rgba(0,0,0,.24)}
#search-box img{width:18px;height:18px;object-fit:contain;opacity:.55;flex-shrink:0}
body.dark #search-box img{filter:invert(1) brightness(.9)}
#search-input{flex:1;min-width:0;border:none;outline:none;background:transparent;color:var(--text);font-size:15px;font-family:inherit}
#search-input::placeholder{color:var(--text-dim)}
#search-box .q-clear{border:none;background:transparent;color:var(--text-dim);font-size:18px;line-height:1;cursor:pointer;padding:0 2px}
#search-box .q-clear:hover{color:var(--text)}
.side-foot{padding:4px 6px 10px}
.side-foot .sep{height:1px;background:var(--border-soft);margin:0 6px 6px}
.foot{position:relative;display:flex;align-items:center;justify-content:center;height:40px;border-radius:10px;border:none;background:transparent;color:var(--text-soft);font-size:13px;cursor:pointer;width:100%}
.foot .txt{position:relative;display:inline-block}
.foot i{position:absolute;right:calc(100% + 9px);top:50%;transform:translateY(-50%);font-style:normal;color:var(--text-dim);line-height:1;display:flex;align-items:center}
.foot:hover{background:#eef0f4}
body.dark .foot:hover{background:#26282d}
.foot i{font-style:normal;color:var(--text-dim);width:16px;display:inline-flex;justify-content:center;flex-shrink:0}
.side-foot .foot-cap{text-align:center;font-size:10px;color:var(--text-dim);padding:8px 0 0}

#main{flex:1;min-width:0;display:flex;flex-direction:column;background:var(--bg);position:relative}
#head{height:60px;flex-shrink:0;display:flex;align-items:center;gap:8px;padding:0 14px 0 10px}
#burger-restore{display:none}
body.side-off #burger-restore{display:flex}
#title{flex:1;min-width:0;font-size:15px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#src{height:30px;padding:0 12px;border-radius:8px;border:1px solid var(--border);background:transparent;color:var(--text-soft);font-size:12px;cursor:pointer}
#src:hover{background:var(--surface-soft);color:var(--accent);border-color:var(--accent-soft)}
#notice{display:none;background:var(--warn-bg);color:var(--warn-fg);font-size:12px;padding:6px 22px}
#notice.on{display:flex;align-items:center;gap:10px}
#notice .n-text{flex:1;min-width:0}
#notice .n-close{flex-shrink:0;width:20px;height:20px;border:none;border-radius:5px;background:transparent;color:inherit;font-size:15px;line-height:1;cursor:pointer;opacity:.7}
#notice .n-close:hover{opacity:1;background:rgba(128,128,128,.18)}

#body{flex:1;min-height:0;display:flex;position:relative}
#chat{flex:1;min-width:0;position:relative}
#chat #viewport{height:100%}
#panel{position:absolute;top:0;right:0;bottom:0;width:var(--pw,340px);background:var(--surface-soft);border-left:1px solid var(--border-soft);display:none;flex-direction:column;min-width:0;z-index:6}
#panel.on{display:flex}
body.panel-open #head{padding-right:calc(var(--pw,340px) + 14px)}
body.panel-open #body{padding-right:var(--pw,340px)}
body.panel-open #st{padding-right:calc(var(--pw,340px) + 22px)}
body.panel-open #composer{padding-right:calc(var(--pw,340px) + 26px)}
#panel .p-head{height:60px;flex-shrink:0;display:flex;align-items:center;justify-content:space-between;padding:0 14px 0 18px}
#panel .p-title{font-size:14px;font-weight:700;color:var(--text)}
#panel .p-count{font-size:12px;color:var(--text-dim)}
#p-list{flex:1;overflow-y:auto;overflow-x:hidden;padding:0 0 18px}
#p-list::-webkit-scrollbar{width:9px}
#p-list::-webkit-scrollbar-thumb{background:var(--border);border-radius:5px}
#split{position:absolute;top:0;bottom:0;width:7px;cursor:col-resize;display:none;z-index:7}
#split.on{display:block}
#split::after{content:'';position:absolute;left:3px;top:0;bottom:0;width:1px;background:var(--border)}
#split:hover{background:var(--accent-soft)}
#split:hover::after{background:var(--accent)}

#bottom{flex-shrink:0;display:flex;flex-direction:column}
#hero img{width:34px;height:25px;object-fit:contain}
#hero{display:none;align-items:center;justify-content:center;gap:10px;font-size:22px;font-weight:700;color:var(--text);padding:0 0 18px}
body.empty #hero{display:flex}
body.empty #body{display:none}
body.empty #bottom{flex:1;justify-content:center;padding-bottom:60px}
#composer{flex-shrink:0;padding:0 26px 8px;width:100%}
body.empty #composer{max-width:880px;margin:0 auto;padding:0 30px 8px}
#attach-row{display:flex;flex-wrap:wrap;gap:6px;padding:0 0 6px}
#attach-row:empty{display:none}
#quote-row{display:flex;flex-wrap:wrap;gap:6px;padding:0 0 6px}
#quote-row:empty{display:none}
.quote-chip{display:flex;align-items:center;gap:7px;max-width:100%;background:var(--surface-soft);border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:8px;padding:5px 8px;font-size:12px;color:var(--text-soft)}
.quote-chip .q-mark{color:var(--accent);font-weight:700;flex-shrink:0}
.quote-chip .q-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:560px}
.quote-chip button{border:none;background:transparent;color:var(--text-dim);cursor:pointer;font-size:14px;line-height:1;padding:0;flex-shrink:0}
.quote-chip button:hover{color:var(--danger)}
.chip{display:flex;align-items:center;gap:6px;background:var(--surface-soft);border:1px solid var(--border);border-radius:8px;padding:4px 8px;font-size:12px;color:var(--text-soft)}
.chip b{font-weight:500}
.chip button{border:none;background:transparent;color:var(--text-dim);cursor:pointer;font-size:13px;line-height:1;padding:0}
.chip button:hover{color:var(--danger)}
.box{border:1px solid var(--border);border-radius:20px;background:var(--bg);padding:12px 16px 6px;box-shadow:0 2px 12px rgba(24,34,64,.05)}
.box:focus-within{border-color:#dfe4ff;box-shadow:0 0 0 3px var(--accent-soft),0 2px 12px rgba(24,34,64,.05)}
#input{display:block;width:100%;min-height:26px;border:none;outline:none;resize:none;background:transparent;color:var(--text);font-family:inherit;font-size:17px;line-height:1.55;max-height:220px;overflow-y:hidden;padding:0 2px 6px}
#input.grow{overflow-y:auto}
#input::placeholder{color:var(--text-dim)}
.bar-top{display:flex;align-items:center;gap:8px;padding:4px 0 10px;flex-wrap:wrap}
.bar-top .spacer{flex:1;min-width:0}
.bar-bottom{display:flex;align-items:center;gap:8px;padding:6px 0 4px;font-size:13px;color:var(--text-soft)}
.divider{height:1px;background:var(--border-soft);margin:0 -16px}
.cap img{width:15px;height:15px;object-fit:contain}
.cap{display:inline-flex;align-items:center;gap:7px;height:34px;padding:0 14px;border-radius:17px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:13.5px;cursor:pointer;white-space:nowrap}
.cap:hover{border-color:var(--text-dim)}
.cap.on{background:var(--accent-soft);border-color:#dde3ff;color:var(--accent)}
#b-model,#b-effort{border:none;background:transparent;color:var(--text-soft);font-size:13px;padding:2px 0;outline:none;cursor:pointer}
#b-effort:disabled{opacity:.42;cursor:default}
.chk{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--text-soft);cursor:pointer;white-space:nowrap;margin-left:auto}
.chk input{width:15px;height:15px;accent-color:var(--accent)}
body.narrow #b-rich{display:none}
body.narrow #hint{display:none}
body.narrow .cap{height:30px;padding:0 8px;font-size:12.5px;gap:5px}
body.narrow .cap span{display:none}
body.narrow .cap img{width:13px;height:13px}
body.narrow .bar-top{gap:6px}
body.narrow .icon{width:28px;height:28px}
body.narrow #b-send{width:32px;height:32px}
body.narrow #b-send img{width:32px;height:32px}
#hint{flex:1;min-width:0;font-size:12px;color:var(--text-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#cost{font-size:12px;color:var(--text-dim);white-space:nowrap}
.icon{width:32px;height:32px;border-radius:50%;border:none;background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center}
.icon:hover{background:var(--surface-soft)}
.icon.rec{background:var(--accent-soft)}
#b-send{width:38px;height:38px;border:none;background:transparent;cursor:pointer;padding:0;display:flex;align-items:center;justify-content:center;position:relative}
#b-send img{width:38px;height:38px;display:block}
#stop-ico{display:none;position:absolute;width:34px;height:34px;border-radius:50%;background:var(--accent);align-items:center;justify-content:center}
#stop-ico::after{content:'';width:12px;height:12px;background:#fff;border-radius:2px}
#b-send.busy #send-img{display:none}
#b-send.busy #stop-ico{display:flex}
body.dark #stop-ico{background:var(--accent)}
.icon img{width:16px;height:16px;object-fit:contain}
body.dark .icon img{filter:invert(1) brightness(.92)}
.icon{width:30px;height:30px;border-radius:50%;border:none;background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center}
#toast{position:absolute;left:50%;bottom:84px;transform:translateX(-50%);max-width:70%;padding:9px 16px;border-radius:10px;background:rgba(28,32,38,.94);color:#fff;font-size:13px;line-height:1.5;opacity:0;pointer-events:none;transition:opacity .2s;z-index:40;box-shadow:0 6px 24px rgba(0,0,0,.18)}
#toast.on{opacity:1}
#toast.err{background:#b3261e}
#st{height:24px;flex-shrink:0;display:flex;align-items:center;justify-content:space-between;padding:0 22px;font-size:11px;color:var(--text-dim);background:var(--surface-soft)}
"""

SHELL_BODY = r"""
<div id="app">
  <aside id="side">
    <div class="brand">
      <div class="brand-left"><img src="@WHALE@" alt=""><span class="word">DeepSeek</span></div>
      <div id="side-tools">
        <button class="side-ico" id="q-open" title="搜索对话"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><line x1="15.5" y1="15.5" x2="21" y2="21"/></svg></button>
        <button class="side-ico" id="multi-toggle" title="多选会话"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><line x1="9" y1="6" x2="20" y2="6"/><circle cx="4.5" cy="6" r="1.4" fill="currentColor"/><line x1="9" y1="12" x2="20" y2="12"/><circle cx="4.5" cy="12" r="1.4" fill="currentColor"/><line x1="9" y1="18" x2="20" y2="18"/><circle cx="4.5" cy="18" r="1.4" fill="currentColor"/></svg></button>
        <button class="side-ico" id="burger" title="收起侧栏"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="4" width="18" height="16" rx="2.5"/><line x1="9" y1="4" x2="9" y2="20"/></svg></button>
      </div>
    </div>
    <button id="new"><span class="n-txt"><i class="n-ico">⊕</i>新建对话</span></button>
    <div id="sessions"></div>
    <div id="multi-bar">
      <button id="multi-pin">置顶</button>
      <button id="multi-export">导出</button>
      <button class="danger" id="multi-del">删除</button>
      <button id="multi-cancel">取消</button>
    </div>
    <div class="side-foot">
      <div class="sep"></div>
      <button class="foot" id="go-import"><span class="txt"><i>⤓</i>导入会话</span></button>
      <button class="foot" id="go-settings"><span class="txt"><i>⚙</i>设置</span></button>
      <div class="foot-cap">绿色便携版 · 数据存在 data 目录</div>
    </div>
    <div id="side-grip"></div>
  </aside>
  <section id="main">
    <header id="head">
      <button class="side-ico" id="burger-restore" title="展开侧栏"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="4" width="18" height="16" rx="2.5"/><line x1="9" y1="4" x2="9" y2="20"/></svg></button>
      <div id="title">新对话</div>
      <button id="src">来源</button>
    </header>
    <div id="notice"></div>
    <div id="body">
      <div id="chat"><div id="viewport"><div id="spacer"></div></div></div>
    </div>
    <div id="split"></div>
    <aside id="panel">
      <div class="p-head"><span class="p-title">检索结果</span><span class="p-count" id="p-count"></span></div>
      <div id="p-list"></div>
    </aside>
    <div id="bottom">
      <div id="hero"><img src="@LOGO@" alt="">欢迎回来，想从哪里开始？</div>
      <div id="composer">
      <div id="quote-row"></div>
      <div id="attach-row"></div>
      <div class="box">
        <textarea id="input" rows="1" placeholder="给 DeepSeek 发送消息"></textarea>
        <div class="bar-top">
          <button class="cap" id="b-think" title="深度思考"><img src="@THINK_ON@" alt=""><span>深度思考</span></button>
          <button class="cap" id="b-web" title="联网"><img src="@WEB_OFF@" alt=""><span>联网</span></button>
          <span class="spacer"></span>
          <button class="icon" id="b-mic" title="按住说话"><img src="@MIC@" alt=""></button>
          <button class="icon" id="b-clip" title="添加附件"><img src="@CLIP@" alt=""></button>
          <button id="b-send" class="off" title="发送"><img id="send-img" src="@SEND_OFF@" alt=""><span id="stop-ico" title="停止生成"></span></button>
        </div>
        <div class="divider"></div>
        <div class="bar-bottom">
          <select id="b-model"></select>
          <select id="b-effort" title="思考强度"></select>
          <span id="hint"></span>
          <span id="cost"></span>
          <label class="chk" id="b-rich"><input type="checkbox" id="rich-box"> 含图表识别</label>
        </div>
      </div>
      </div>
    </div>
    <div id="st"><span id="st-left"></span><span id="st-right"></span></div>
    <div id="toast"></div>
  </section>
</div>
<div id="search-mask">
  <div id="search-box">
    <img src="@SEARCH@" alt="">
    <input id="search-input" placeholder="搜索对话内容..." autocomplete="off">
    <button class="q-clear" id="q-clear" title="关闭">×</button>
  </div>
</div>
"""

SHELL_JS = r"""
// ---------------- 外壳 ----------------
var S = { busy:false, panel:false, panelWidth:340, items:[], active:null };

var ICONS = {
  think_on:'@THINK_ON@', think_off:'@THINK_OFF@',
  web_on:'@WEB_ON@', web_off:'@WEB_OFF@',
  send_on:'@SEND_ON@', send_off:'@SEND_OFF@'
};

function $(id){ return document.getElementById(id); }
window.onerror = function(m, src, line){
  try{ post({type:'js_error', data: String(m) + ' @' + line}); }catch(e){}
  return false;
};
function post(o){ try{ window.chrome.webview.postMessage(o); }catch(e){} }

var CHAT_TYPES = {clear:1, welcome:1, history:1, user:1, assistant_begin:1, reasoning:1,
                  content:1, note:1, assistant_end:1, speak_state:1, error:1, scroll_end:1,
                  notice:1};

window.chrome.webview.addEventListener('message', function(e){
  var msg;
  try{ msg = typeof e.data === 'string' ? JSON.parse(e.data) : e.data; }catch(err){ return; }
  if(!msg || !msg.type) return;
  if(CHAT_TYPES[msg.type]){
    if(msg.type === 'welcome') document.body.classList.add('empty');
    else if(msg.type === 'history' || msg.type === 'user') document.body.classList.remove('empty');
    handle(msg);
    return;
  }
  switch(msg.type){
    case 'init': onInit(msg.data); break;
    case 'sessions': renderSessions(msg.data.items || [], msg.data.active); break;
    case 'title': $('title').textContent = msg.data || '新对话'; break;
    case 'status': $('st-left').textContent = msg.data || ''; break;
    case 'status_right': $('st-right').textContent = msg.data || ''; break;
    case 'hint': $('hint').textContent = msg.data || ''; break;
    case 'cost': $('cost').textContent = msg.data || ''; break;
    case 'busy': setBusy(!!msg.data); break;
    case 'attachments': renderAttachments(msg.data || []); break;
    case 'quotes': renderQuotes(msg.data || []); break;
    case 'notice_bar': setNoticeBar(msg.data || ''); break;
    case 'panel': renderPanel(msg.data || {}); break;
    case 'panel_open': setPanel(!!msg.data); break;
    case 'theme': document.body.classList.toggle('dark', !!(msg.data && msg.data.dark)); break;
    case 'input_set': ShellUI.setText(msg.data || ''); break;
    case 'input_clear': ShellUI.clear(); break;
    case 'input_focus': ShellUI.focus(); break;
    case 'recording': ShellUI.setRecording(!!msg.data); break;
    case 'set_rich': ShellUI.setRich(!!msg.data); break;
    case 'set_model': ShellUI.setModel(msg.data); break;
    case 'set_toggle': setToggle(msg.data.key === 'thinking' ? 'b-think' : 'b-web', !!msg.data.value); break;
    case 'zoom': document.body.style.zoom = (msg.data && msg.data.zoom) || 1; break;
    case 'notice_show': $('notice').classList.toggle('on', !!msg.data); break;
    case 'source_btn': $('src').textContent = msg.data || '来源'; break;
    case 'toast': showToast(msg.data || {}); break;
    default: break;
  }
});

function onInit(d){
  if(d.theme === 'dark') document.body.classList.add('dark');
  $('st-right').textContent = d.data_dir || '';
  $('b-model').innerHTML = (d.models || []).map(function(m){
    return '<option value="'+m+'">'+m+'</option>';
  }).join('');
  $('b-model').value = d.model;
  $('b-effort').innerHTML = (d.efforts || ['low','medium','high']).map(function(v){
    return '<option value="'+v+'">'+v+'</option>';
  }).join('');
  $('b-effort').value = d.effort || 'high';
  $('b-effort').disabled = !d.thinking;
  setToggle('b-think', !!d.thinking);
  setToggle('b-web', !!d.web);
  $('rich-box').checked = !!d.rich;
  renderSessions(d.sessions || [], d.active);
  $('title').textContent = d.title || '新对话';
  if(d.notice) setNoticeBar(d.notice);
  if(d.side_width) document.documentElement.style.setProperty('--sidew', d.side_width + 'px');
  requestAnimationFrame(updateBrandFade);
  if(d.panel_width) applyPanelWidth(d.panel_width);
  if(d.zoom) document.body.style.zoom = d.zoom;
  setBusy(false);
  requestAnimationFrame(function(){ autoGrow(); fitComposer(); });
  $('input').focus();
}

// ---------------- 会话列表 ----------------
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }

var M = {on:false, chosen:new Set()};
function renderSessions(items, active){
  S.items = items; S.active = active;
  var box = $('sessions');
  box.innerHTML = '';
  if(!items.length){
    box.innerHTML = '<div style="color:var(--text-dim);font-size:12.5px;line-height:1.8;padding:8px 4px">还没有对话<br>点上面「新建对话」开始</div>';
    return;
  }
  // 置顶优先，其余按最后对话时间；每条会话自身已标日期，不再分组
  var sorted = items.slice().sort(function(a,b){
    if(!!a.pinned !== !!b.pinned) return a.pinned ? -1 : 1;
    return (b.ts||0) - (a.ts||0);
  });
  sorted.forEach(function(it){
    var d = document.createElement('div');
    d.className = 's-item' + (it.id === active ? ' active' : '');
    d.setAttribute('data-id', it.id);
    d.innerHTML = (it.pinned?'<span class="pin-dot" title="已置顶">★</span>':'')+
                  '<input type="checkbox" class="s-check"'+(M.chosen.has(it.id)?' checked':'')+'>'+
                  '<div class="s-title">'+esc(it.title || '新对话')+'</div>'+
                  '<div class="s-meta">'+esc(it.meta || '')+'</div>'+
                  '<button class="s-more" title="更多">⋯</button>';
    var cb = d.querySelector('.s-check');
    cb.onclick = function(ev){ ev.stopPropagation(); };
    cb.onchange = function(){ if(cb.checked) M.chosen.add(it.id); else M.chosen.delete(it.id); updateMulti(); };
    d.onclick = function(){
      if(M.on){ cb.checked = !cb.checked; if(cb.checked) M.chosen.add(it.id); else M.chosen.delete(it.id); updateMulti(); return; }
      post({type:'open_session', data:it.id});
    };
    var more = d.querySelector('.s-more');
    more.onclick = function(ev){ ev.stopPropagation(); openMenu(d, it); };
    box.appendChild(d);
  });
  updateMulti();
}
function setMulti(on){
  M.on = !!on;
  if(!M.on) M.chosen.clear();
  document.body.classList.toggle('multi-mode', M.on);
  $('multi-bar').classList.toggle('on', M.on);
  $('multi-toggle').classList.toggle('on', M.on);
  $('multi-toggle').title = M.on ? '退出多选' : '多选会话';
  // 重新渲染以同步复选框显示
  renderSessions(S.items, S.active);
}
function updateMulti(){ /* 多选栏已去掉计数，保留占位供调用点使用 */ }
$('multi-toggle').onclick = function(){ setMulti(!M.on); };  // 再点一次退出多选
$('multi-cancel').onclick = function(){ setMulti(false); };
$('multi-del').onclick = function(){ post({type:'multi_delete', data:Array.from(M.chosen)}); setMulti(false); };
$('multi-export').onclick = function(){ post({type:'multi_export', data:Array.from(M.chosen)}); };
$('multi-pin').onclick = function(){ post({type:'multi_pin', data:Array.from(M.chosen)}); setMulti(false); };

function openMenu(host, it){
  closeMenu();
  var m = document.createElement('div');
  m.className = 's-menu';
  m.id = 'smenu';
  m.innerHTML = '<button data-a="rename">重命名</button>'+
                '<button data-a="pin">'+(it.pinned?'取消置顶':'置顶')+'</button>'+
                '<button data-a="export">导出</button>'+
                '<button data-a="delete" class="danger">删除</button>';
  m.onclick = function(ev){
    var a = ev.target.getAttribute('data-a');
    if(!a) return;
    ev.stopPropagation();
    post({type:'session_action', data:{id:it.id, action:a}});
    closeMenu();
  };
  host.appendChild(m);
}
function closeMenu(){ var m = $('smenu'); if(m) m.remove(); }
document.addEventListener('click', function(){ closeMenu(); });

// ---------------- 顶栏 / 检索栏 ----------------
function toggleSide(){ document.body.classList.toggle('side-off'); }
$('burger').onclick = toggleSide;
$('burger-restore').onclick = toggleSide;
$('src').onclick = function(){ post({type:'panel_toggle'}); };

function setPanel(on){
  S.panel = !!on;
  document.body.classList.toggle('panel-open', S.panel);
  $('panel').classList.toggle('on', S.panel);
  $('split').classList.toggle('on', S.panel);
  applyPanelWidth(S.panelWidth);
  requestAnimationFrame(fitComposer);
}
function fitComposer(){
  var box = document.querySelector('#composer .box');
  if(!box) return;
  var w = box.getBoundingClientRect().width;
  if(w < 40) return;   // 布局还没算出来，别误判成窄屏
  // 用输入框本身的可视宽度判断，而不是外层容器（外层还含 padding）
  document.body.classList.toggle('narrow', w < 470);
}
window.addEventListener('resize', fitComposer);

function applyPanelWidth(w){
  S.panelWidth = w;
  document.documentElement.style.setProperty('--pw', w + 'px');
  $('panel').style.width = w + 'px';
  $('split').style.right = w + 'px';
}
function layoutSplit(){ applyPanelWidth(S.panelWidth); }
window.addEventListener('resize', layoutSplit);

(function(){
  var dragging = false;
  var split = $('split');
  split.addEventListener('mousedown', function(e){
    dragging = true; e.preventDefault();
    document.body.style.cursor = 'col-resize';
    try{ split.setPointerCapture(e.pointerId); }catch(err){}
  });
  window.addEventListener('mousemove', function(e){
    if(!dragging) return;
    var w = Math.min(720, Math.max(260, window.innerWidth - e.clientX));
    applyPanelWidth(w);
    fitComposer();
  });
  window.addEventListener('mouseup', function(){
    if(!dragging) return;
    dragging = false;
    document.body.style.cursor = '';
    fitComposer();
    post({type:'panel_width', data:S.panelWidth});
  });
})();

var pCount = 0;
function renderPanel(d){
  var list = $('p-list');
  list.innerHTML = '';
  var groups = (d.groups || []).filter(function(g){ return g && g.sources && g.sources.length; });
  var cites = (d.cites || []).filter(function(c){ return c && c.url; });
  var notes = (d.notes || []).filter(function(n){ return n && String(n).trim(); });
  var total = 0;
  groups.forEach(function(g){ total += (g.sources || []).length; });
  total += cites.length;
  $('p-count').textContent = total ? (total + ' 条') : '';
  if(!groups.length && !cites.length && !notes.length){
    list.innerHTML = '<div class="empty">这一轮没有可查看的联网内容。</div>';
    return;
  }
  var n = 0;
  function sec(t){
    var d = document.createElement('div'); d.className = 'sec'; d.textContent = t; list.appendChild(d);
  }
  function row(src){
    n += 1;
    var url = src.url || '', title = src.title || url;
    var d = document.createElement('div');
    d.className = 'row';
    var host = '';
    try{ host = new URL(url).hostname.replace(/^www\./,''); }catch(err){}
    d.innerHTML = '<div class="n">'+n+'</div><div><div class="t">'+esc(title)+'</div>'+
                  (host && title.toLowerCase().indexOf(host) < 0 ? '<div class="h">'+esc(host)+'</div>' : '')+'</div>';
    d.onclick = function(){ if(url) post({type:'open_url', data:url}); };
    list.appendChild(d);
  }
  if(cites.length){ sec('文中引用（对应正文序号）'); cites.forEach(row); }
  groups.forEach(function(g){
    var t = String(g.query || '').trim();
    if(!t || t.indexOf('未命名') >= 0) t = '搜索来源';
    sec(t);
    (g.sources || []).forEach(row);
  });
  if(notes.length && !total){
    sec('联网动作（这一轮没有保存链接）');
    notes.forEach(function(t){
      var d = document.createElement('div'); d.className = 'note'; d.textContent = t; list.appendChild(d);
    });
  }
}

// ---------------- 附件 / 提示条 ----------------
function renderAttachments(items){
  var box = $('attach-row');
  box.innerHTML = '';
  items.forEach(function(a){
    var c = document.createElement('div');
    c.className = 'chip';
    c.innerHTML = '<b>'+esc(a.name || a.file_id)+'</b><button title="移除">×</button>';
    c.querySelector('button').onclick = function(){ post({type:'remove_attachment', data:a.file_id}); };
    box.appendChild(c);
  });
}
function renderQuotes(items){
  var box = $('quote-row');
  box.innerHTML = '';
  items.forEach(function(q, i){
    var c = document.createElement('div');
    c.className = 'quote-chip';
    c.innerHTML = '<span class="q-mark">❝</span><span class="q-text"></span><button title="移除引用">×</button>';
    c.querySelector('.q-text').textContent = q.text || '';
    c.querySelector('button').onclick = function(){ post({type:'quote_remove', data:i}); };
    c.title = (q.role ? q.role + '：' : '') + (q.text || '');
    box.appendChild(c);
  });
}
var toastTimer = null;
function showToast(d){
  var t = $('toast');
  t.textContent = d.text || '';
  t.className = 'on' + (d.kind === 'error' ? ' err' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function(){ t.className = ''; }, d.ms || 4200);
}

function setNoticeBar(text){
  var n = $('notice');
  n.innerHTML = '<span class="n-text"></span><button class="n-close" title="关闭提示">×</button>';
  n.querySelector('.n-text').textContent = text || '';
  n.querySelector('.n-close').onclick = function(){
    n.classList.remove('on');
    post({type:'notice_close'});
  };
  n.classList.toggle('on', !!text);
}

// ---------------- 输入栏 ----------------
var ta = $('input');

function autoGrow(){
  ta.style.height = 'auto';
  var h = ta.scrollHeight;
  ta.style.height = Math.min(220, h) + 'px';
  ta.classList.toggle('grow', h > 220);
}
ta.addEventListener('input', function(){ autoGrow(); syncSend(); });
ta.addEventListener('paste', function(e){
  var items = (e.clipboardData && e.clipboardData.items) || [];
  var files = [];
  for(var i=0;i<items.length;i++){
    if(items[i].kind === 'file' && items[i].type.indexOf('image/') === 0){
      var f = items[i].getAsFile();
      if(f) files.push(f);
    }
  }
  if(!files.length) return;      // 纯文本就直接走默认粘贴
  e.preventDefault();
  files.forEach(function(f){
    var reader = new FileReader();
    reader.onload = function(){
      var s = String(reader.result || '');
      var b64 = s.indexOf(',') >= 0 ? s.split(',')[1] : '';
      if(b64) post({type:'paste_image', data:{name: f.name || 'image.png', b64: b64}});
    };
    reader.readAsDataURL(f);
  });
});
ta.addEventListener('keydown', function(e){
  if(e.key === 'Enter' && !e.shiftKey && !e.isComposing){
    e.preventDefault();
    submit();
    return;
  }
  if(e.key === 'Enter' && (e.ctrlKey || e.metaKey)){ e.preventDefault(); submit(); }
  if((e.ctrlKey || e.metaKey) && (e.key === '0' || e.key === ')')){ e.preventDefault(); post({type:'zoom_reset'}); }
});
function submit(){
  if(S.busy) return;
  var text = ta.value.trim();
  if(!text) return;
  post({type:'send', data:{text:text}});
}
$('b-send').onclick = function(){ if(S.busy) post({type:'stop'}); else submit(); };

function syncSend(){
  var has = !!ta.value.trim();
  var busy = !!S.busy;
  var active = has || busy;
  var btn = $('b-send');
  btn.classList.toggle('off', !active && !busy);
  btn.classList.toggle('busy', busy);
  btn.title = busy ? '停止生成' : '发送';
  var img = $('send-img');
  if(img && !busy) img.src = active ? ICONS.send_on : ICONS.send_off;
}
function setBusy(on){
  S.busy = !!on;
  syncSend();
  $('b-mic').disabled = !!on;
}
function setToggle(id, on){
  var el = $(id);
  if(id === 'b-think'){ try{ $('b-effort').disabled = !on; }catch(e){} }
  el.classList.toggle('on', !!on);
  var img = el.querySelector('img');
  if(img){
    var k = (id === 'b-think' ? 'think' : 'web') + (on ? '_on' : '_off');
    img.src = ICONS[k];
  }
}

$('b-think').onclick = function(){
  var on = !this.classList.contains('on'); setToggle('b-think', on);
  post({type:'toggle', data:{key:'thinking', value:on}});
};
$('b-web').onclick = function(){
  var on = !this.classList.contains('on'); setToggle('b-web', on);
  post({type:'toggle', data:{key:'web', value:on}});
};
$('b-model').onchange = function(){ post({type:'model', data:this.value}); };
$('b-effort').onchange = function(){ post({type:'effort', data:this.value}); };
$('rich-box').onchange = function(){ post({type:'toggle', data:{key:'rich', value:this.checked}}); };
$('b-clip').onclick = function(){ post({type:'attach'}); };

var micDown = false;
$('b-mic').addEventListener('mousedown', function(e){ e.preventDefault(); micDown = true; post({type:'mic_start'}); });
$('b-mic').addEventListener('mouseup', function(){ if(micDown){ micDown = false; post({type:'mic_stop'}); } });
$('b-mic').addEventListener('mouseleave', function(){ if(micDown){ micDown = false; post({type:'mic_stop'}); } });

// 品牌文字只在真的放不下（被裁切）时才渐隐，空间足够时保持清晰
function updateBrandFade(){
  var w = document.querySelector('#side .brand .word');
  if(!w) return;
  if(w.scrollWidth > w.clientWidth + 1) w.classList.add('clipped');
  else w.classList.remove('clipped');
}
window.addEventListener('resize', updateBrandFade);

// ---------------- 侧栏可拖拽 ----------------
(function(){
  var grip = $('side-grip'), dragging = false;
  if(!grip) return;
  grip.addEventListener('mousedown', function(e){ dragging = true; e.preventDefault(); document.body.style.cursor = 'col-resize'; });
  window.addEventListener('mousemove', function(e){
    if(!dragging) return;
    var w = Math.min(420, Math.max(200, e.clientX));
    document.documentElement.style.setProperty('--sidew', w + 'px');
    S.sideWidth = w;
    updateBrandFade();
  });
  window.addEventListener('mouseup', function(){
    if(!dragging) return;
    dragging = false; document.body.style.cursor = '';
    post({type:'sidebar_width', data:S.sideWidth});
  });
})();

$('new').onclick = function(){ post({type:'new_chat'}); };
// 搜索浮层：点放大镜打开，输入防抖过滤，Esc / 关闭按钮收起
function openSearch(){
  $('search-mask').classList.add('on');
  $('search-input').value = '';
  $('search-input').focus();
}
function closeSearch(){
  $('search-mask').classList.remove('on');
  if(S.searchText){ S.searchText = ''; post({type:'search', data:''}); }
}
$('q-open').onclick = openSearch;
$('q-clear').onclick = closeSearch;
$('search-mask').onclick = function(e){ if(e.target === this) closeSearch(); };
var qTimer = null;
$('search-input').addEventListener('input', function(){
  var v = this.value;
  S.searchText = v;
  clearTimeout(qTimer);
  qTimer = setTimeout(function(){ post({type:'search', data:v}); }, 120);
});
$('search-input').addEventListener('keydown', function(e){ if(e.key === 'Escape'){ e.preventDefault(); closeSearch(); } });
$('go-import').onclick = function(){ post({type:'import'}); };
$('go-settings').onclick = function(){ post({type:'settings'}); };
window.addEventListener('contextmenu', function(e){ e.preventDefault(); });

// Ctrl + 滚轮缩放整个页面（WebView 会吞掉 Tk 的滚轮绑定，必须在页面里处理）
var zoomTimer = null;
window.addEventListener('wheel', function(e){
  if(!e.ctrlKey && !e.metaKey) return;
  e.preventDefault();
  var dir = e.deltaY < 0 ? 1 : -1;
  // 连续滚动合并成一次 post，避免刷屏、卡顿
  S._zoomPending = (S._zoomPending || 0) + dir;
  if(zoomTimer) return;
  zoomTimer = setTimeout(function(){
    zoomTimer = null;
    var d = S._zoomPending || 0; S._zoomPending = 0;
    if(d) post({type:'zoom_wheel', data:d});
  }, 40);
}, {passive:false});

// 输入栏 API（给 Python 侧调用）
window.ShellUI = {
  setText: function(t){ ta.value = t || ''; autoGrow(); syncSend(); ta.focus(); },
  getText: function(){ return ta.value; },
  clear: function(){ ta.value = ''; autoGrow(); syncSend(); },
  focus: function(){ ta.focus(); },
  setRecording: function(on){ $('b-mic').classList.toggle('rec', !!on); },
  setHint: function(t){ $('hint').textContent = t || ''; },
  setCost: function(t){ $('cost').textContent = t || ''; },
  setRich: function(v){ $('rich-box').checked = !!v; },
  setModel: function(v){ $('b-model').value = v; },
  setToggle: setToggle
};
autoGrow(); syncSend();
requestAnimationFrame(function(){ autoGrow(); fitComposer(); });
post({type:'shell_ready'});

"""


def _apply_icons(text: str) -> str:
    for token, uri in ICONS.items():
        text = text.replace(token, uri)
    return text


def build_shell_html() -> str:
    panel_css = PANEL_CSS.split(":root{", 1)[0] + PANEL_CSS.split("}", 1)[1] if ":root{" in PANEL_CSS else PANEL_CSS
    # 去掉 panel 自己的 :root/body 配色，统一用聊天页的变量，避免两套颜色打架
    if ":root{" in panel_css:
        head, tail = panel_css.split(":root{", 1)
        panel_css = head + tail.split("}", 1)[1]
    panel_css = panel_css.replace("html,body{margin:0;padding:0;height:100%}", "")
    panel_css = panel_css.replace("body{background:var(--bg);color:var(--text);", "body{")
    return _apply_icons(f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
{CHAT_CSS}
{panel_css}
{SHELL_CSS}
</style>
</head>
<body>
{SHELL_BODY}
<script>
{CHAT_JS_BARE}
{SHELL_JS}
</script>
</body>
</html>
""")


SHELL_HTML = build_shell_html()
