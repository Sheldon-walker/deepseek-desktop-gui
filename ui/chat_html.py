"""对话区前端：内嵌的 HTML/CSS/JS 字符串。

不依赖任何 CDN / 外部资源，离线可用。包含：
- 虚拟滚动懒加载（绝对定位 + ResizeObserver，恒定 DOM 节点数）
- 轻量 Markdown 渲染（表格 / 代码高亮 / 引用 / 列表 / 折叠思考）
- 与 Python 后端双向通信（window.chrome.webview.postMessage）
"""

from __future__ import annotations

from .assets import data_uri as _data_uri

CHAT_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{
  --bg:#ffffff; --surface:#ffffff; --surface-soft:#fafbfc; --card:#f6f7f9;
  --border:#e4e6ea; --border-soft:#eff0f3;
  --text:#1a1c1f; --text-soft:#5a6068; --text-dim:#9aa0aa;
  --accent:#4d6bfe; --accent-hover:#3b57e2; --accent-soft:#edf0ff;
  --user-bubble:#eef2ff; --user-bubble-border:#dee4ff;
  --code-bg:#f4f5f7; --code-border:#e6e8ec; --code-fg:#2b2f36;
  --code-inline:#b4442e; --warn-bg:#fff8e6; --warn-fg:#8a5a00;
  --thinking-bg:#fafafb; --thinking-text:#8b9199; --danger:#e5484d;
  --shadow:0 1px 3px rgba(0,0,0,0.06);
  /* 对话排版：由设置页「阅读排版」动态覆盖；默认值即「舒适阅读」预设 */
  --chat-pad-x:36px; --chat-lh:1.85; --chat-fs:16px;
  --chat-font:"Microsoft YaHei UI","Microsoft YaHei","Segoe UI","PingFang SC",Arial,sans-serif;
  --chat-para:.55em;
}
body.dark{
  --bg:#16181b; --surface:#1c1e22; --surface-soft:#202227; --card:#26282d;
  --border:#34373d; --border-soft:#2a2d32;
  --text:#e7e9ec; --text-soft:#a9afb8; --text-dim:#7c848e;
  --accent:#7c93ff; --accent-hover:#94a7ff; --accent-soft:#262c45;
  --user-bubble:#262c45; --user-bubble-border:#39446a;
  --code-bg:#23252a; --code-border:#34373d; --code-fg:#d7dbe0;
  --code-inline:#ff9d7a; --warn-bg:#33291a; --warn-fg:#e0a65c;
  --thinking-bg:#1e2024; --thinking-text:#9aa0aa; --danger:#f0716e;
  --shadow:0 1px 3px rgba(0,0,0,0.4);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;height:100%;overflow:hidden;background:var(--bg)}
body{font-family:"Microsoft YaHei UI","Microsoft YaHei","Segoe UI","PingFang SC",Arial,sans-serif;font-size:15px;color:var(--text);line-height:1.7}
/* 排版只作用于对话消息区，侧栏 / 顶栏 / 输入栏等 UI 保持原有尺寸不被放大 */
#viewport{height:100%;overflow-y:auto;overflow-x:hidden;position:relative;scrollbar-width:thin;scrollbar-color:var(--border) transparent;
  font-family:var(--chat-font);font-size:var(--chat-fs);line-height:var(--chat-lh)}
#viewport::-webkit-scrollbar{width:9px}
#viewport::-webkit-scrollbar-thumb{background:var(--border);border-radius:5px}
#viewport::-webkit-scrollbar-thumb:hover{background:var(--text-dim)}
#spacer{width:100%}
.msg{padding:10px var(--chat-pad-x)}

/* 用户消息 */
.user-row{display:flex;flex-direction:column;align-items:flex-end;gap:6px}
.user-bubble{max-width:78%;background:var(--user-bubble);border:1px solid var(--user-bubble-border);border-radius:14px;padding:10px 14px;white-space:pre-wrap;word-break:break-word}
.user-actions{display:flex;flex-direction:row;gap:6px;opacity:0;transition:opacity .15s}
.user-row:hover .user-actions{opacity:1}
.mini-btn{background:var(--bg);border:1px solid var(--border);color:var(--text-soft);font-size:12.5px;border-radius:10px;padding:4px 12px;cursor:pointer;line-height:1.5;transition:background .15s,border-color .15s,color .15s}
.mini-btn:hover{background:var(--surface-soft);border-color:var(--accent-soft);color:var(--accent)}
.user-files{margin-top:6px;font-size:12px;color:var(--text-soft)}
.user-files .f{display:block}
.user-quotes{margin:0 0 8px;padding:6px 10px;border-left:3px solid var(--accent);border-radius:6px;background:rgba(127,127,127,.10);font-size:12px;color:var(--text-soft);max-height:132px;overflow:auto}
.user-quotes .uq-item{margin:2px 0;white-space:pre-wrap;word-break:break-word;line-height:1.55}
.user-quotes .uq-item::before{content:'❝ ';color:var(--accent);font-weight:700}
.user-quotes .uq-role{color:var(--text-dim);font-size:11px;margin-right:4px}

/* 助手消息 */
.asst-head{display:flex;align-items:center;gap:8px;margin-bottom:4px;min-width:0}
.asst-avatar{width:30px;height:30px;object-fit:contain;flex-shrink:0;display:block}
body.dark .asst-avatar{background:rgba(255,255,255,.9);border-radius:50%;padding:2px;box-sizing:border-box}
.asst-meta{font-size:12px;color:var(--text-dim);min-width:0;overflow-wrap:anywhere;line-height:1.5}
.asst-actions{display:flex;gap:4px;margin-top:8px;opacity:0;transition:opacity .15s}
.msg:hover .asst-actions{opacity:1}
.ghost-btn{background:var(--bg);border:1px solid var(--border);color:var(--text-soft);font-size:12.5px;border-radius:10px;padding:4px 12px;cursor:pointer;line-height:1.5;transition:background .15s,border-color .15s,color .15s}
.ghost-btn:hover{background:var(--surface-soft);border-color:var(--accent-soft);color:var(--accent)}
.ghost-btn.active{color:var(--accent);border-color:var(--accent-soft);background:var(--accent-soft)}

/* 选中消息文本时浮出的工具条（朗读 / 引用） */
.sel-bar{position:fixed;z-index:60;display:flex;gap:2px;padding:4px;border-radius:12px;background:var(--surface);border:1px solid var(--border);box-shadow:0 6px 22px rgba(0,0,0,.16)}
.sel-bar button{display:inline-flex;align-items:center;gap:5px;height:30px;padding:0 11px;border:none;border-radius:8px;background:transparent;color:var(--text-soft);font-size:12.5px;cursor:pointer;white-space:nowrap}
.sel-bar button:hover{background:var(--accent-soft);color:var(--accent)}

/* 正文 */
.asst-body{word-break:break-word}
.asst-body.streaming{white-space:pre-wrap}
.asst-body h1{font-size:1.35em;margin:var(--chat-para) 0 .3em}
.asst-body h2{font-size:1.2em;margin:var(--chat-para) 0 .28em}
.asst-body h3{font-size:1.08em;margin:var(--chat-para) 0 .25em}
.asst-body p{margin:var(--chat-para) 0}
.asst-body ul,.asst-body ol{margin:var(--chat-para) 0;padding-left:1.6em}
.asst-body li{margin:calc(var(--chat-para) * .35) 0}
.asst-body blockquote{margin:.5em 0;padding:4px 14px;border-left:3px solid var(--border);color:var(--text-soft)}
.asst-body hr{border:none;border-top:1px solid var(--border);margin:.8em 0}
.asst-body a{color:var(--accent);text-decoration:none;cursor:pointer}
.asst-body a:hover{text-decoration:underline}
.asst-body code.inline{background:var(--code-bg);border:1px solid var(--code-border);color:var(--code-inline);border-radius:4px;padding:1px 5px;font-family:"Cascadia Mono",Consolas,"Courier New",monospace;font-size:.88em}
.asst-body pre{background:var(--code-bg);border:1px solid var(--code-border);border-radius:10px;padding:12px 14px;overflow-x:auto;margin:.5em 0}
.asst-body pre code{font-family:"Cascadia Mono",Consolas,"Courier New",monospace;font-size:.86em;line-height:1.55;color:var(--code-fg);white-space:pre}
.code-head{display:flex;justify-content:space-between;align-items:center;background:var(--code-bg);border:1px solid var(--code-border);border-bottom:none;border-radius:10px 10px 0 0;padding:6px 12px;font-size:12px;color:var(--text-dim)}
.code-head + pre{border-radius:0 0 10px 10px;margin-top:0}
.copy-code{background:transparent;border:none;color:var(--text-dim);font-size:12px;cursor:pointer}
.copy-code:hover{color:var(--text-soft)}
/* 语法高亮 */
.tok-kw{color:#7c3aed}.tok-str{color:#16a34a}.tok-num{color:#d97706}.tok-com{color:#9aa0aa;font-style:italic}.tok-fn{color:#2563eb}
body.dark .tok-kw{color:#c4a5ff}.tok-kw,body.dark .tok-kw{color:#a78bfa}.tok-str,body.dark .tok-str{color:#6ee7a0}.tok-num,body.dark .tok-num{color:#fbbf63}.tok-com,body.dark .tok-com{color:#7c848e}.tok-fn,body.dark .tok-fn{color:#7cb8ff}

/* 表格 */
.asst-body table{border-collapse:collapse;margin:.6em 0;font-size:.92em;display:block;overflow-x:auto}
.asst-body th,.asst-body td{border:1px solid var(--border);padding:6px 12px;text-align:left}
.asst-body th{background:var(--surface-soft);font-weight:600}
.asst-body tr:nth-child(even) td{background:var(--surface-soft)}

/* 正文里的来源索引（上标） */
sup.ref{display:inline;font-size:10px;font-weight:600;line-height:1;color:var(--accent);background:var(--accent-soft);border-radius:4px;padding:1px 3px;margin:0 1px;position:relative;top:-2px;cursor:pointer;transition:background .15s,color .15s}
sup.ref:hover{background:var(--accent);color:#fff}
sup.ref.plain{cursor:default;color:var(--text-dim);background:var(--surface-soft)}

/* 思考过程 */
.reason-wrap{margin:4px 0 8px}
.reason-toggle{background:transparent;border:none;color:var(--thinking-text);font-size:12.5px;cursor:pointer;padding:2px 0;display:flex;align-items:center;gap:4px}
.reason-toggle:hover{color:var(--text-soft)}
.reason-toggle .arrow{transition:transform .15s;display:inline-block}
.reason-box{background:var(--thinking-bg);border:1px solid var(--border-soft);border-radius:10px;padding:10px 14px;margin-top:4px;color:var(--thinking-text);font-size:13px;white-space:pre-wrap;word-break:break-word}
.reason-box.hidden{display:none}

/* 联网记录：一行小胶囊，点开在右侧看来源（长查询不再折成好几行） */
.notes{margin:8px 0 2px}
.note-chip{display:inline-flex;align-items:center;gap:7px;max-width:100%;background:var(--surface-soft);border:1px solid var(--border-soft);border-radius:999px;padding:4px 11px;font-size:12.5px;color:var(--text-soft);cursor:pointer;transition:background .15s,border-color .15s,color .15s}
.note-chip:hover{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
.note-chip .ic{display:flex;align-items:center;color:var(--accent);flex-shrink:0}
.note-chip .txt{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.note-chip .go{color:var(--text-dim);font-size:11px;flex-shrink:0}
.note-chip:hover .go{color:var(--accent)}

/* 费用徽标 */
.footer-bar{display:flex;justify-content:space-between;align-items:center;gap:10px;background:var(--accent-soft);border-radius:8px;padding:6px 12px;margin-top:8px;font-size:12px}
.footer-detail{color:var(--text-soft)}
.footer-cost{color:var(--accent);font-weight:700;white-space:nowrap}

/* 错误 */
.asst-body.error{color:var(--danger)}

/* 提示条 */
.notice{text-align:center;font-size:12.5px;color:var(--text-dim);padding:4px 0}
.notice.expand-btn{color:var(--accent);cursor:pointer;background:var(--surface-soft);border:1px solid var(--border);border-radius:8px;padding:6px 14px;display:inline-block}
.notice.expand-btn:hover{background:var(--card)}

/* 欢迎页 */
.welcome{display:flex;flex-direction:column;align-items:flex-start;justify-content:center;min-height:60vh;padding:20px var(--chat-pad-x)}
.welcome h1{font-size:28px;margin:0 0 8px}
.welcome p{color:var(--text-dim);margin:0}
</style>
</head>
<body>
<div id="viewport"><div id="spacer"></div></div>
<script>
"use strict";
var viewport = document.getElementById('viewport');
var spacer = document.getElementById('spacer');

// ---------------- 状态 ----------------
var items = [];          // {id, kind:'user'|'assistant'|'notice', data, el}
var stickBottom = true;

// ---------------- 通信 ----------------
function post(obj){
  try{ window.chrome.webview.postMessage(obj); }catch(e){}
}

window.chrome.webview.addEventListener('message', function(e){
  var msg;
  try{ msg = typeof e.data === 'string' ? JSON.parse(e.data) : e.data; }catch(err){ return; }
  handle(msg);
});

function handle(msg){
  try{
    switch(msg.type){
      case 'clear': clearAll(); break;
      case 'welcome': showWelcome(); break;
      case 'history': renderHistory(msg.data); break;
      case 'user': addUser(msg.data); break;
      case 'assistant_begin': beginAssistant(msg.data); break;
      case 'reasoning': appendReasoning(msg.data); break;
      case 'content': appendContent(msg.data); break;
      case 'note': appendNote(msg.data); break;
      case 'assistant_end': endAssistant(msg.data); break;
      case 'speak_state': setSpeakState(msg.data); break;
      case 'error': markError(msg.data); break;
      case 'scroll_end': scrollToEnd(); break;
      case 'theme': document.body.classList.toggle('dark', !!(msg.data && msg.data.dark)); break;
      case 'notice': addNotice(msg.data); break;
      default: break;
    }
  }catch(err){ /* 忽略单条渲染异常 */ }
}

// ---------------- 懒加载渲染（正常文档流 + 按需 prepend） ----------------
var renderStart = 0;   // 已渲染到的最早消息索引
var BATCH = 40;        // 每次向上加载的消息条数

function buildMsgEl(it){
  var el = document.createElement('div');
  el.className = 'msg';
  if(it.kind==='user' || it.kind==='assistant'){
    var d = it.data || {};
    if(d.index !== undefined && d.index !== null) el.setAttribute('data-index', d.index);
    el.setAttribute('data-role', it.kind);
  }
  if(it.kind==='user') el.appendChild(buildUser(it));
  else if(it.kind==='assistant') el.appendChild(buildAssistant(it));
  else el.appendChild(buildNotice(it.data));
  return el;
}

function clearAll(){
  items = [];
  spacer.innerHTML = '';
  renderStart = 0;
}

// 初始渲染：只渲染最近 BATCH 条（旧消息留待向上滚动时懒加载）
function initialRender(){
  var n = items.length;
  renderStart = Math.max(0, n - BATCH);
  for(var i=renderStart; i<n; i++){
    var el = buildMsgEl(items[i]);
    items[i].el = el;
    spacer.appendChild(el);
  }
}

// 向上滚动接近顶部时，prepend 更早的 BATCH 条，并补偿 scrollTop 保持视口稳定
function loadMore(){
  if(renderStart <= 0) return;
  var oldH = viewport.scrollHeight;
  var oldTop = viewport.scrollTop;
  var newStart = Math.max(0, renderStart - BATCH);
  var frag = document.createDocumentFragment();
  for(var i=newStart; i<renderStart; i++){
    var el = buildMsgEl(items[i]);
    items[i].el = el;
    frag.appendChild(el);
  }
  spacer.insertBefore(frag, spacer.firstChild);
  renderStart = newStart;
  viewport.scrollTop = oldTop + (viewport.scrollHeight - oldH);
}

// 追加一条新消息（流式/发送时用）
function addItem(it){
  items.push(it);
  var el = buildMsgEl(it);
  it.el = el;
  spacer.appendChild(el);
  if(stickBottom) scrollToEnd();
}

// ---------------- 滚动 ----------------
viewport.addEventListener('scroll', function(){
  stickBottom = (viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight) < 80;
  if(viewport.scrollTop < 1200){ loadMore(); }
});
function scrollToEnd(){
  stickBottom = true;
  requestAnimationFrame(function(){ viewport.scrollTop = viewport.scrollHeight; });
}

// ---------------- 消息构建 ----------------
var AVATAR_SRC = '__AVATAR__';

function buildUser(it){
  var d = it.data || {};
  var row = document.createElement('div');
  row.className = 'user-row';

  var actions = document.createElement('div');
  actions.className = 'user-actions';
  if(d.index!==undefined && d.index!==null){
    var editBtn = document.createElement('button');
    editBtn.className='mini-btn'; editBtn.textContent='编辑';
    editBtn.onclick=function(){ post({type:'edit_user', data:{index:d.index, text:d.text||''}}); };
    actions.appendChild(editBtn);
  }
  var copyBtn = document.createElement('button');
  copyBtn.className='mini-btn'; copyBtn.textContent='复制';
  copyBtn.onclick=function(){ post({type:'copy_user', data:d.text||''}); };
  actions.appendChild(copyBtn);
  if(d.index!==undefined && d.index!==null){
    var delBtn = document.createElement('button');
    delBtn.className='mini-btn'; delBtn.textContent='删除';
    delBtn.onclick=function(){ post({type:'delete_msg', data:{index:d.index}}); };
    actions.appendChild(delBtn);
  }
  var bubble = document.createElement('div');
  bubble.className='user-bubble';
  bubble.textContent = d.text || '';
  if(d.quotes && d.quotes.length){
    var qbox = document.createElement('div'); qbox.className='user-quotes';
    d.quotes.forEach(function(q){
      var t = (q && typeof q === 'object') ? (q.text || '') : String(q || '');
      if(!t) return;
      var item = document.createElement('div'); item.className='uq-item';
      if(q && q.role){ var r=document.createElement('span'); r.className='uq-role'; r.textContent=q.role+'：'; item.appendChild(r); }
      item.appendChild(document.createTextNode(t.slice(0, 600)));
      qbox.appendChild(item);
    });
    if(qbox.childNodes.length) bubble.insertBefore(qbox, bubble.firstChild);
  }
  if(d.files && d.files.length){
    var fs = document.createElement('div'); fs.className='user-files';
    d.files.forEach(function(f){ var s=document.createElement('span'); s.className='f'; s.textContent='📎 '+(f.name||f.file_id); fs.appendChild(s); });
    bubble.appendChild(fs);
  }
  row.appendChild(bubble);
  row.appendChild(actions);
  return row;
}

function buildAssistant(it){
  var d = it.data || {};
  var wrap = document.createElement('div');

  var head = document.createElement('div'); head.className='asst-head';
  var av = document.createElement('img'); av.className='asst-avatar'; av.src=AVATAR_SRC; av.alt='';
  var meta = document.createElement('span'); meta.className='asst-meta'; meta.textContent=(d.model||'')+(d.time?(' · '+d.time):'');

  head.appendChild(av); head.appendChild(meta);
  wrap.appendChild(head);

  // 思考过程
  if(d.reasoning){
    var reasonWrap = document.createElement('div'); reasonWrap.className='reason-wrap';
    var toggle = document.createElement('button'); toggle.className='reason-toggle';
    var arrow = document.createElement('span'); arrow.className='arrow'; arrow.textContent='▸';
    var tlabel = document.createElement('span'); tlabel.textContent=' 思考过程 · '+d.reasoning.length+' 字';
    toggle.appendChild(arrow); toggle.appendChild(tlabel);
    var box = document.createElement('div'); box.className='reason-box hidden'; box.textContent=d.reasoning;
    toggle.onclick=function(){
      if(box.classList.contains('hidden')){ box.classList.remove('hidden'); arrow.textContent='▾'; }
      else{ box.classList.add('hidden'); arrow.textContent='▸'; }
    };
    reasonWrap.appendChild(toggle); reasonWrap.appendChild(box);
    wrap.appendChild(reasonWrap);
    it._reasonBox = box;
  }

  // 正文
  var body = document.createElement('div'); body.className='asst-body';
  if(d.streaming){
    body.classList.add('streaming');
    body.textContent = d.content || '';
  }else if(d.error){
    body.classList.add('error');
    body.textContent = d.content || '';
  }else{
    var injected = injectRefs(d.content || '', d.citations);
    body.innerHTML = markdown(injected.text, !injected.indexed);
    bindLinks(body);
    bindCodeCopy(body);
    bindRefs(body, d);
  }
  wrap.appendChild(body);
  it._bodyEl = body;

  // 联网记录 / 来源 / 引用：正文里只留一个入口胶囊，明细全在右侧栏
  //（以前这里会把 30 多条搜索结果平铺在消息下面，又长又重复）
  var srcBox = document.createElement('div'); srcBox.className='notes';
  var chip = buildSourceChip(d);
  if(chip){ srcBox.appendChild(chip); wrap.appendChild(srcBox); it._notesEl = srcBox; }

  // 费用徽标
  if(d.footer || d.cost){
    var bar = document.createElement('div'); bar.className='footer-bar';
    var det = document.createElement('span'); det.className='footer-detail'; det.textContent=d.footer||'';
    var cost = document.createElement('span'); cost.className='footer-cost'; cost.textContent=d.cost||'';
    bar.appendChild(det); bar.appendChild(cost);
    wrap.appendChild(bar);
  }

  // 底部操作行：重新生成 / 朗读 / 复制 / 删除
  var actions = document.createElement('div'); actions.className='asst-actions';
  if(d.regen){
    var regenBtn = document.createElement('button'); regenBtn.className='ghost-btn'; regenBtn.textContent='重新生成';
    regenBtn.onclick=function(){ post({type:'regen'}); };
    actions.appendChild(regenBtn);
  }
  var speakBtn = document.createElement('button'); speakBtn.className='ghost-btn'; speakBtn.textContent='朗读';
  speakBtn.onclick=function(){ post({type:'speak', data:{id:it.id, state: it._speakState||'idle'}}); };
  actions.appendChild(speakBtn);
  var copyBtn = document.createElement('button'); copyBtn.className='ghost-btn'; copyBtn.textContent='复制';
  copyBtn.onclick=function(){ post({type:'copy', data:d.content||''}); };
  actions.appendChild(copyBtn);
  if(d.index!==undefined && d.index!==null){
    var delBtn = document.createElement('button'); delBtn.className='ghost-btn'; delBtn.textContent='删除';
    delBtn.onclick=function(){ post({type:'delete_msg', data:{index:d.index}}); };
    actions.appendChild(delBtn);
  }
  wrap.appendChild(actions);
  it._speakBtn = speakBtn;

  return wrap;
}

var ICON_LINK = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1"></path><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"></path></svg>';
var ICON_SEARCH = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"></circle><path d="M20.5 20.5l-3.8-3.8"></path></svg>';

// 把一堆原始联网记录（"联网搜索：xxx（3 条结果）"）压成一句话
function summarizeNotes(notes){
  var s=0, r=0, src=0, single='';
  for(var i=0;i<notes.length;i++){
    var n=String(notes[i]||'').trim();
    if(!n) continue;
    var m=n.match(/（(\d+)\s*条结果）/);
    if(n.indexOf('联网搜索')===0 || n.indexOf('图片搜索')===0){
      s++;
      if(m) src += parseInt(m[1],10);
      if(!single && n.indexOf('未命名')<0) single = n.replace(/（\d+\s*条结果）$/,'');
    } else if(n.indexOf('联网动作')!==0){
      r++;
    }
  }
  var label='';
  if(s===1 && r===0 && single){ label = single; }
  else {
    var bits=[];
    if(s) bits.push(s>1 ? ('联网搜索 '+s+' 次') : '联网搜索');
    if(r) bits.push('读取网页 '+r+' 个');
    label = bits.join(' · ');
  }
  if(src) label += ' · '+src+' 条来源';
  return label;
}

function renderNotes(it){
  if(!it.el) return;
  var chip = buildSourceChip(it.data);
  if(!chip) return;
  if(!it._notesEl){
    var wrap = it.el.firstChild; if(!wrap) return;
    var box = document.createElement('div'); box.className='notes';
    var actions = wrap.querySelector('.asst-actions');
    if(actions) wrap.insertBefore(box, actions); else wrap.appendChild(box);
    it._notesEl = box;
  }
  it._notesEl.innerHTML = '';
  it._notesEl.appendChild(chip);
}

function buildNotice(data){
  var d = data || {};
  var n = document.createElement('div'); n.className='notice';
  if(d.expand){
    var b = document.createElement('span'); b.className='expand-btn'; b.textContent=d.text||'展开更早的消息';
    b.onclick=function(){ post({type:'expand_history'}); };
    n.appendChild(b);
  }else{
    n.textContent = d.text || '';
  }
  return n;
}

function buildSourceChip(d){
  var notes = (d && d.notes) || [];
  var refCount = ((d && d.sources) ? d.sources.length : 0) + ((d && d.citations) ? d.citations.length : 0);
  var label = summarizeNotes(notes);
  var icon = ICON_SEARCH;
  if(!label){
    if(!refCount) return null;
    label = '参考来源 ' + refCount + ' 条';
    icon = ICON_LINK;
  }
  var chip = document.createElement('div');
  chip.className = 'note-chip';
  chip.title = notes.length ? notes.join('\n') : label;
  var ic = document.createElement('span'); ic.className='ic'; ic.innerHTML = icon;
  var tx = document.createElement('span'); tx.className='txt'; tx.textContent = label;
  var go = document.createElement('span'); go.className='go'; go.textContent = '查看来源 ›';
  chip.appendChild(ic); chip.appendChild(tx); chip.appendChild(go);
  chip.onclick = function(){
    post({type:'show_sources', data:{index:(d.index===undefined?null:d.index), note:(notes[0]||'')}});
  };
  return chip;
}

// ---------------- 操作 ----------------
function showWelcome(){
  clearAll();
  var it = {id:'welcome', kind:'notice', data:{}};
  items.push(it);
  var el = document.createElement('div'); el.className='msg';
  el.appendChild(buildWelcome());
  it.el = el;
  spacer.appendChild(el);
}
function buildWelcome(){
  var w = document.createElement('div'); w.className='welcome';
  var h = document.createElement('h1'); h.textContent='有什么可以帮你？';
  var p = document.createElement('p'); p.textContent='在下方输入框提问，开始与 DeepSeek 对话。';
  w.appendChild(h); w.appendChild(p);
  return w;
}

function renderHistory(data){
  clearAll();
  var msgs = (data && data.messages) || [];
  var lastAssistant = -1;
  msgs.forEach(function(m, idx){
    if(m.role==='user'){
      items.push({id:'h'+idx, kind:'user', data:{text:m.content||'', files:m.files||[], quotes:m.quotes||[], index:m.index!==undefined?m.index:null}});
    }else if(m.role==='assistant'){
      lastAssistant = items.length;
      items.push({id:'h'+idx, kind:'assistant', data:{
        model:m.model||'', time:m.time||'', content:m.content||'', reasoning:m.reasoning||'',
        notes:m.notes||[], citations:m.citations||[], sources:m.sources||[], footer:m.footer||'', cost:m.cost||'',
        index:(m.index!==undefined?m.index:null), regen:false
      }});
    }else{
      items.push({id:'h'+idx, kind:'notice', data:{text:m.text||''}});
    }
  });
  // 最后一条助手消息支持"重新生成"
  if(lastAssistant >= 0 && items[lastAssistant]){
    items[lastAssistant].data.regen = true;
  }
  initialRender();
  requestAnimationFrame(function(){ scrollToEnd(); });
}

function addNotice(data){
  addItem({id:'n'+items.length, kind:'notice', data:data||{}});
}

function addUser(d){
  dismissWelcome();
  addItem({id:d.id, kind:'user', data:d});
}

function dismissWelcome(){
  for(var i=0;i<items.length;i++){
    if(items[i].id==='welcome'){
      if(items[i].el) items[i].el.remove();
      items.splice(i,1);
      break;
    }
  }
}

function beginAssistant(d){
  dismissWelcome();
  // 新回复开始：清除上一条助手消息的"重新生成"标记
  for(var i=items.length-1;i>=0;i--){
    if(items[i].kind==='assistant' && items[i].data.regen){
      items[i].data.regen = false;
      if(items[i].el){ var ne=buildMsgEl(items[i]); items[i].el.replaceWith(ne); items[i].el=ne; }
      break;
    }
  }
  addItem({id:d.id, kind:'assistant', data:{
    model:d.model||'', time:d.time||'', content:'', reasoning:'', notes:[], citations:[],
    streaming:true, regen:false, index:(d.index!==undefined?d.index:null)
  }});
}

function appendReasoning(d){
  var it = findItem(d.id); if(!it) return;
  it.data.reasoning = (it.data.reasoning||'') + d.text;
  var el = it.el;
  if(!el) return;
  if(!it._reasonBox){
    // 流式中首次出现思考：动态创建折叠块，插在正文之前
    var wrap = document.createElement('div'); wrap.className='reason-wrap';
    var toggle = document.createElement('button'); toggle.className='reason-toggle';
    var arrow = document.createElement('span'); arrow.className='arrow'; arrow.textContent='▾';
    var tlabel = document.createElement('span'); tlabel.textContent=' 思考过程 · 0 字（进行中）';
    toggle.appendChild(arrow); toggle.appendChild(tlabel);
    var box = document.createElement('div'); box.className='reason-box'; box.textContent='';
    wrap.appendChild(toggle); wrap.appendChild(box);
    toggle.onclick=function(){
      if(box.classList.contains('hidden')){ box.classList.remove('hidden'); arrow.textContent='▾'; }
      else{ box.classList.add('hidden'); arrow.textContent='▸'; }
    };
    var head = el.querySelector('.asst-head');
    head.insertAdjacentElement('afterend', wrap);
    it._reasonBox = box; it._reasonLabel = tlabel; it._reasonArrow = arrow;
  }
  if(!it._reasonBox.classList.contains('hidden')) it._reasonBox.textContent = it.data.reasoning;
  it._reasonLabel.textContent = ' 思考过程 · '+it.data.reasoning.length+' 字（进行中）';
}
function appendContent(d){
  var it = findItem(d.id); if(!it) return;
  it.data.content = (it.data.content||'') + d.text;
  if(it._bodyEl) it._bodyEl.textContent = it.data.content;
}
function appendNote(d){
  var it = findItem(d.id); if(!it) return;
  it.data.notes = it.data.notes||[];
  it.data.notes.push(d.text);
  renderNotes(it);
}
function endAssistant(d){
  var it = findItem(d.id); if(!it) return;
  it.data.streaming = false;
  it.data.content = d.content || it.data.content || '';
  it.data.reasoning = d.reasoning || it.data.reasoning || '';
  it.data.notes = d.notes || it.data.notes || [];
  it.data.citations = d.citations || [];
  it.data.footer = d.footer || '';
  it.data.cost = d.cost || '';
  it.data.regen = d.regen !== false;
  it.data.error = !!d.error;
  // 重新构建该条消息（Markdown 渲染），原位替换
  var newEl = buildMsgEl(it);
  if(it.el){ it.el.replaceWith(newEl); }
  else { spacer.appendChild(newEl); }
  it.el = newEl;
  if(stickBottom) scrollToEnd();
}
function setSpeakState(d){
  var it = findItem(d.id); if(!it) return;
  it._speakState = d.state;
  if(it._speakBtn){
    if(d.state==='loading') it._speakBtn.textContent='合成中…';
    else if(d.state==='playing'){ it._speakBtn.textContent='■ 停止'; it._speakBtn.classList.add('active'); }
    else{ it._speakBtn.textContent='朗读'; it._speakBtn.classList.remove('active'); }
  }
}
function markError(d){
  var it = findItem(d.id); if(!it) return;
  it.data.error = true; it.data.streaming = false; it.data.content = d.text||it.data.content||'';
  var ne = buildMsgEl(it);
  if(it.el){ it.el.replaceWith(ne); }
  else { spacer.appendChild(ne); }
  it.el = ne;
}
function findItem(id){
  for(var i=0;i<items.length;i++){ if(items[i].id===id) return items[i]; }
  return null;
}

// ---------------- Markdown ----------------
function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function inlineMd(s, allowBracketRefs){
  s = esc(s);
  // 行内码
  s = s.replace(/`([^`\n]+)`/g, '<code class="inline">$1</code>');
  // 链接
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2">$1</a>');
  // 加粗
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // 接口给的 annotations 带位置时，用 \u0001n\u0002 标记插入（见 injectRefs）
  s = s.replace(/\u0001(\d{1,2})\u0002/g, function(_m, n){
    return '<sup class="ref" data-n="'+n+'">'+n+'</sup>';
  });
  if(allowBracketRefs === false) return s;
  // 模型自己在正文里写的 [1] / [1,2] / [1-3] 也转成上标索引，
  // 行内代码和链接里的方括号不处理
  var parts = s.split(/(<code[\s\S]*?<\/code>|<a\b[\s\S]*?<\/a>)/g);
  for(var i=0;i<parts.length;i++){
    if(i % 2) continue;
    parts[i] = parts[i].replace(/\[(\d{1,2}(?:\s*[,，\-–]\s*\d{1,2})*)\]/g, function(_m, nums){
      var out = [];
      String(nums).split(/\s*[,，]\s*/).forEach(function(seg){
        var range = seg.split(/\s*[\-–]\s*/);
        if(range.length === 2){
          var a = parseInt(range[0],10), b = parseInt(range[1],10);
          for(var k=a; k<=b && k<=99; k++) out.push(k);
        } else if(seg){
          out.push(parseInt(seg,10));
        }
      });
      return out.filter(function(n){ return n >= 1; })
                .map(function(n){ return '<sup class="ref" data-n="'+n+'">'+n+'</sup>'; })
                .join('');
    });
  }
  return parts.join('');
}

// 给上标索引挂上对应的来源：悬停看标题，点击直接打开
function bindRefs(root, d){
  var cites = (d && d.citations) || [];
  var srcs = (d && d.sources) || [];
  root.querySelectorAll('sup.ref').forEach(function(el){
    var n = parseInt(el.getAttribute('data-n'), 10);
    var cite = cites[n-1] || srcs[n-1];
    if(!cite || !cite.url){ el.className = 'ref plain'; return; }
    el.title = cite.title || cite.url;
    el.onclick = function(ev){ ev.stopPropagation(); post({type:'open_url', data:cite.url}); };
  });
}
// 把 annotations 的字符位置变成正文里的上标序号（官方那种"这句话用了搜索"）
function injectRefs(text, cites){
  var marks = {}, hit = false;
  (cites || []).forEach(function(c, i){
    var p = -1;
    if(c && typeof c.end_index === 'number') p = c.end_index;
    else if(c && typeof c.start_index === 'number') p = c.start_index;
    if(p < 0 || p > text.length) return;
    hit = true;
    (marks[p] = marks[p] || []).push(i + 1);
  });
  if(!hit) return {text: text, indexed: false};
  Object.keys(marks).map(Number).sort(function(a, b){ return b - a; }).forEach(function(p){
    var tag = marks[p].map(function(n){ return '\u0001' + n + '\u0002'; }).join('');
    text = text.slice(0, p) + tag + text.slice(p);
  });
  return {text: text, indexed: true};
}

function markdown(text, allowBracketRefs){
  if(!text) return '';
  var lines = text.replace(/\r\n/g,'\n').split('\n');
  var html = [], i = 0, listStack = [];
  function closeLists(){ while(listStack.length){ html.push('</'+listStack.pop()+'>'); } }
  function pushList(tag){ if(listStack.length && listStack[listStack.length-1]===tag) return; closeLists(); listStack.push(tag); html.push('<'+tag+'>'); }
  while(i < lines.length){
    var line = lines[i];
    var t = line.trim();
    // 代码块
    if(t.startsWith('```')){
      var lang = t.slice(3).trim();
      html.push('<div class="code-head"><span>'+(esc(lang)||'code')+'</span><button class="copy-code">复制</button></div><pre><code>');
      i++;
      var code = [];
      while(i < lines.length && !lines[i].trim().startsWith('```')){ code.push(lines[i]); i++; }
      html.push(highlight(code.join('\n'), lang));
      html.push('</code></pre>');
      i++;
      continue;
    }
    if(!t){
      closeLists(); html.push('');
      i++; continue;
    }
    // 标题
    var m = t.match(/^(#{1,6})\s+(.*)$/);
    if(m){ closeLists(); var lvl=m[1].length; if(lvl<=3) html.push('<h'+lvl+'>'+inlineMd(m[2], allowBracketRefs)+'</h'+lvl+'>'); else html.push('<p><strong>'+inlineMd(m[2], allowBracketRefs)+'</strong></p>'); i++; continue; }
    // 分隔线
    if(/^([-*_])\1{2,}$/.test(t)){ closeLists(); html.push('<hr>'); i++; continue; }
    // 引用
    var q = line.match(/^>\s?(.*)$/);
    if(q){ closeLists(); html.push('<blockquote>'+inlineMd(q[1], allowBracketRefs)+'</blockquote>'); i++; continue; }
    // 无序列表
    var ul = line.match(/^(\s*)[-*+]\s+(.*)$/);
    if(ul){ pushList('ul'); html.push('<li>'+inlineMd(ul[2], allowBracketRefs)+'</li>'); i++; continue; }
    // 有序列表
    var ol = line.match(/^(\s*)\d+[.)]\s+(.*)$/);
    if(ol){ pushList('ol'); html.push('<li>'+inlineMd(ol[2], allowBracketRefs)+'</li>'); i++; continue; }
    // 表格
    if(t.indexOf('|')>=0 && i+1<lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i+1]) && lines[i+1].indexOf('-')>=0){
      closeLists();
      var head = t.split('|').map(function(c){return c.trim();}).filter(function(c){return c!=='';});
      i += 2;
      var rows = [];
      while(i<lines.length && lines[i].indexOf('|')>=0){ rows.push(lines[i]); i++; }
      html.push('<table><thead><tr>'+head.map(function(c){return '<th>'+inlineMd(c, allowBracketRefs)+'</th>';}).join('')+'</tr></thead><tbody>');
      rows.forEach(function(r){
        var cells = r.split('|').map(function(c){return c.trim();}).filter(function(c){return c!=='';});
        html.push('<tr>'+cells.map(function(c){return '<td>'+inlineMd(c, allowBracketRefs)+'</td>';}).join('')+'</tr>');
      });
      html.push('</tbody></table>');
      continue;
    }
    closeLists();
    html.push('<p>'+inlineMd(t, allowBracketRefs)+'</p>');
    i++;
  }
  closeLists();
  return html.join('\n');
}

// ---------------- 代码高亮（轻量） ----------------
var KEYWORDS = ['def','return','if','else','elif','for','while','import','from','class','try','except','finally','with','as','in','not','and','or','None','True','False','lambda','yield','pass','break','continue','global','nonlocal','raise','assert','print','self','function','var','let','const','new','this','null','undefined','true','false','async','await','switch','case','default','do','public','private','static','void','int','float','double','char','bool','string','goto','sizeof','typedef','struct','enum','union','include','define','using','namespace','template','echo','cd','ls','rm','cp','mv','mkdir','sudo','apt','pip','git','npm'];
function highlight(code, lang){
  var out = '';
  var re = /(\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\/|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`|\b\d+(?:\.\d+)?\b|\b[A-Za-z_]\w*\b)/g;
  var last = 0, m;
  while((m = re.exec(code)) !== null){
    out += esc(code.slice(last, m.index));
    var tok = m[0];
    if(/^(\/\/|#|\/\*)/.test(tok)) out += '<span class="tok-com">'+esc(tok)+'</span>';
    else if(/^["'`]/.test(tok)) out += '<span class="tok-str">'+esc(tok)+'</span>';
    else if(/^\d/.test(tok)) out += '<span class="tok-num">'+esc(tok)+'</span>';
    else if(KEYWORDS.indexOf(tok)>=0) out += '<span class="tok-kw">'+esc(tok)+'</span>';
    else if(/^[A-Za-z_]/.test(tok) && /[A-Za-z_]\s*\(/.test(code.slice(m.index, m.index+tok.length+1))) out += '<span class="tok-fn">'+esc(tok)+'</span>';
    else out += esc(tok);
    last = m.index + tok.length;
  }
  out += esc(code.slice(last));
  return out.replace(/\u0001\d{1,2}\u0002/g, '');
}

// ---------------- 链接与代码复制 ----------------
function bindLinks(root){
  root.querySelectorAll('a[href]').forEach(function(a){
    a.onclick = function(ev){ ev.preventDefault(); post({type:'open_url', data:a.getAttribute('href')}); };
  });
}
function bindCodeCopy(root){
  root.querySelectorAll('.copy-code').forEach(function(btn){
    btn.onclick = function(){
      var code = btn.closest('div').nextElementSibling.querySelector('code');
      var text = code ? code.innerText : '';
      post({type:'copy', data:text});
      btn.textContent = '已复制';
      setTimeout(function(){ btn.textContent='复制'; }, 1200);
    };
  });
}

// ---------------- 选中文本：朗读 / 引用 ----------------
var selBar = null;
function hideSelBar(){
  if(selBar){ selBar.remove(); selBar = null; }
}
function msgText(el){
  if(!el) return '';
  var b = el.querySelector('.user-bubble, .asst-body');
  return b ? (b.innerText || '').trim() : '';
}
// 收集引用上下文：选中消息本身 + 前后各一条（只取角色与摘要，避免太长）
function quoteContext(el, picked){
  var ctx = [];
  var all = Array.prototype.slice.call(document.querySelectorAll('#spacer > .msg[data-role]'));
  var pos = all.indexOf(el);
  function brief(node){
    if(!node) return null;
    var role = node.getAttribute('data-role') === 'user' ? '用户' : '助手';
    var t = msgText(node).replace(/\s+/g, ' ').slice(0, 220);
    return t ? {role:role, text:t} : null;
  }
  var prev = pos > 0 ? brief(all[pos-1]) : null;
  var self = {role: el.getAttribute('data-role') === 'user' ? '用户' : '助手', text: msgText(el).slice(0, 1200)};
  var next = pos >= 0 && pos < all.length-1 ? brief(all[pos+1]) : null;
  if(prev) ctx.push(prev);
  ctx.push(self);
  if(next) ctx.push(next);
  return {index: el.getAttribute('data-index'), picked: picked, context: ctx};
}
function showSelBar(rect, data){
  hideSelBar();
  selBar = document.createElement('div');
  selBar.className = 'sel-bar';
  selBar.innerHTML = '<button data-a="speak" title="朗读选中的文字">🔊 朗读</button>'+
                     '<button data-a="quote" title="引用这段文字继续提问">❝ 引用</button>';
  document.body.appendChild(selBar);
  var w = selBar.offsetWidth || 168;
  var left = Math.max(6, Math.min(rect.left + rect.width/2 - w/2, window.innerWidth - w - 6));
  var top = rect.top - 44;
  if(top < 6) top = rect.bottom + 8;
  selBar.style.left = left + 'px';
  selBar.style.top = top + 'px';
  // 防止按下按钮时选区被清掉
  selBar.addEventListener('mousedown', function(e){ e.preventDefault(); });
  selBar.onclick = function(e){
    var btn = e.target.closest('button[data-a]');
    if(!btn) return;
    var a = btn.getAttribute('data-a');
    if(a === 'speak') post({type:'speak_selection', data:{text:data.picked}});
    else post({type:'quote_selection', data:data});
    hideSelBar();
    try{ window.getSelection().removeAllRanges(); }catch(err){}
  };
}
document.addEventListener('mouseup', function(e){
  if(selBar && selBar.contains(e.target)) return;
  setTimeout(function(){
    var sel = window.getSelection();
    var picked = sel ? String(sel).trim() : '';
    if(!picked || !sel || !sel.rangeCount){ hideSelBar(); return; }
    var range = sel.getRangeAt(0);
    var node = range.commonAncestorContainer;
    var el = node && node.nodeType === 3 ? node.parentElement : node;
    var owner = el && el.closest ? el.closest('.msg[data-role]') : null;
    if(!owner){ hideSelBar(); return; }
    showSelBar(range.getBoundingClientRect(), quoteContext(owner, picked.slice(0, 2000)));
  }, 10);
});
document.addEventListener('mousedown', function(e){
  if(selBar && !selBar.contains(e.target)) hideSelBar();
});
document.addEventListener('keydown', function(e){ if(e.key === 'Escape') hideSelBar(); });
viewport.addEventListener('scroll', hideSelBar);

// ---------------- 初始化 ----------------
post({type:'web_ready'});
</script>
</body>
</html>
"""


CHAT_HTML = CHAT_HTML.replace("__AVATAR__", _data_uri("deepseek-whale.png", 48))


def _split_doc(doc: str):
    css = doc.split("<style>", 1)[1].split("</style>", 1)[0]
    body = doc.split("<body>", 1)[1].split("<script>", 1)[0]
    js = doc.split("<script>", 1)[1].split("</script>", 1)[0]
    return css, body, js


CHAT_CSS, CHAT_BODY, CHAT_JS = _split_doc(CHAT_HTML)

# 外壳版页面里由外壳统一分发消息，去掉聊天自己的 message 监听
CHAT_JS_BARE = CHAT_JS.replace(
    """window.chrome.webview.addEventListener('message', function(e){
  var msg;
  try{ msg = typeof e.data === 'string' ? JSON.parse(e.data) : e.data; }catch(err){ return; }
  handle(msg);
});
""",
    "",
).replace("post({type:'web_ready'});", "")
