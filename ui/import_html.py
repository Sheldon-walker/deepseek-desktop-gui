"""导入会话页面的 HTML（WebView2 渲染）。

列表可能有上千条，用「分批 append」渲染，勾选状态存在 JS 数组里，
点导入时把选中的索引回传给 ui/import_web.py，由 Python 侧写本地会话。
"""

from __future__ import annotations

IMPORT_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
:root{
  --bg:#ffffff; --surface:#ffffff; --surface-soft:#fafbfc; --card:#f5f6f8;
  --border:#e4e6ea; --border-soft:#eff0f3;
  --text:#1a1c1f; --text-soft:#5a6068; --text-dim:#9aa0aa;
  --accent:#4d6bfe; --accent-hover:#3b57e2; --accent-soft:#edf0ff; --danger:#e5484d; --ok:#1a7f37;
}
body.dark{
  --bg:#16181b; --surface:#1c1e22; --surface-soft:#202227; --card:#26282d;
  --border:#34373d; --border-soft:#2a2d32;
  --text:#e7e9ec; --text-soft:#a9afb8; --text-dim:#7c848e;
  --accent:#7c93ff; --accent-hover:#94a7ff; --accent-soft:#262c45; --danger:#f0716e; --ok:#4ade80;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;height:100%;overflow:hidden;background:var(--bg)}
body.dark{color-scheme:dark}
body{font-family:"Microsoft YaHei UI","Microsoft YaHei","Segoe UI",Arial,sans-serif;font-size:13.5px;color:var(--text)}
#app{display:flex;flex-direction:column;height:100%}
#head{padding:18px 24px 2px;flex-shrink:0}
#head h1{margin:0;font-size:20px}
#head p{margin:5px 0 0;font-size:12px;color:var(--text-dim);line-height:1.7}
#picker{display:flex;align-items:center;gap:12px;padding:12px 24px 4px;flex-shrink:0}
#path{flex:1;min-width:0;font-size:12.5px;color:var(--text-soft);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#search{display:block;width:calc(100% - 48px);margin:8px 24px 4px;height:32px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);font-size:12.5px;font-family:inherit;padding:0 12px;outline:none;flex-shrink:0}
#search::placeholder{color:var(--text-dim)}
#search:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
#search:disabled{opacity:.5;cursor:default}
.btn{height:34px;padding:0 14px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text-soft);font-size:12.5px;cursor:pointer;white-space:nowrap}
.btn:hover{background:var(--surface-soft);color:var(--text)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.btn.primary:hover{filter:brightness(1.06)}
.btn.primary:disabled{opacity:.45;cursor:default}
#list{flex:1;min-height:0;margin:0 24px;border:1px solid var(--border);border-radius:10px;background:var(--surface-soft);overflow-y:auto;padding:4px}
#list::-webkit-scrollbar{width:10px}
#list::-webkit-scrollbar-thumb{background:var(--border);border-radius:5px}
.row{display:flex;align-items:flex-start;gap:10px;padding:9px 10px;border-radius:8px}
.row:hover{background:var(--card)}
.row input[type=checkbox]{width:17px;height:17px;margin-top:3px;accent-color:var(--accent);flex-shrink:0;cursor:pointer}
.row input[type=checkbox]:disabled{cursor:default}
.row .meta{min-width:0;flex:1}
.row .t{font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row.done .t{color:var(--text-dim)}
.row .s{font-size:11.5px;color:var(--text-dim);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#empty{padding:30px;text-align:center;color:var(--text-dim);font-size:12.5px}
#foot{flex-shrink:0;display:flex;align-items:center;gap:10px;padding:12px 24px;border-top:1px solid var(--border-soft);background:var(--surface-soft)}
#status{flex:1;min-width:0;font-size:12px;color:var(--text-dim)}
#status.err{color:var(--danger)} #status.ok{color:var(--ok)}
#toast{position:fixed;left:50%;bottom:70px;transform:translateX(-50%);background:rgba(28,32,38,.94);color:#fff;padding:8px 14px;border-radius:8px;font-size:12.5px;opacity:0;pointer-events:none;transition:opacity .2s;z-index:20}
#toast.on{opacity:1}
</style>
</head>
<body>
<div id="app">
  <div id="head">
    <h1>导入会话</h1>
    <p>支持两种文件：① 本软件导出的备份 .json；② DeepSeek 官网导出的数据（.zip 或解压后的 conversations.json）。<br>导入只把历史消息读进本地查看，不会重新发给模型，不产生 token 与工具费用。</p>
  </div>
  <div id="picker">
    <div id="path">尚未选择文件</div>
    <button class="btn" id="pick">选择文件…</button>
  </div>
  <input id="search" type="text" placeholder="搜索会话标题…" disabled autocomplete="off">
  <div id="list"><div id="empty">选择文件后，这里会列出可导入的会话</div></div>
  <div id="foot">
    <button class="btn" id="all">全选</button>
    <button class="btn" id="none">全不选</button>
    <div id="status"></div>
    <button class="btn" id="cancel">取消</button>
    <button class="btn primary" id="do" disabled>导入</button>
  </div>
</div>
<div id="toast"></div>
<script>
function $(id){ return document.getElementById(id); }
function post(o){ try{ window.chrome.webview.postMessage(o); }catch(e){} }
window.onerror = function(m, s, l){ post({type:'js_error', data:String(m)+' @'+l}); return false; };
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }

var S = {items:[], checked:new Set(), total:0};

function toast(t){
  var el=$('toast'); el.textContent=t||''; el.classList.add('on');
  clearTimeout(S._tt); S._tt=setTimeout(function(){ el.classList.remove('on'); }, 1800);
}
function setStatus(text, kind){
  var el=$('status'); el.textContent=text||'';
  el.className = kind || '';
}
function visibleIndices(){
  var kw = ($('search').value || '').trim().toLowerCase();
  var out = [];
  for(var i=0;i<S.items.length;i++){
    var it = S.items[i];
    if(!kw || (it.title||'').toLowerCase().indexOf(kw) >= 0 || (it.meta||'').toLowerCase().indexOf(kw) >= 0){
      out.push(i);
    }
  }
  return out;
}
function renderList(items){
  S.items = items; S.checked = new Set();
  items.forEach(function(it, i){ if(!it.already) S.checked.add(i); });
  $('search').disabled = !items.length;
  renderVisible();
}
function renderVisible(){
  var box = $('list'); box.innerHTML = '';
  var gen = (S._gen || 0) + 1; S._gen = gen;  // 渲染代号：搜索变化时让旧批次停下
  S.visible = visibleIndices();
  if(!S.items.length){ box.innerHTML = '<div id="empty">没有可导入的会话</div>'; updateCount(); return; }
  if(!S.visible.length){ box.innerHTML = '<div id="empty">没有匹配的会话</div>'; updateCount(); return; }
  // 分批渲染，避免上千条一次 append 卡住
  var BATCH = 120, pos = 0, vis = S.visible;
  function chunk(){
    if(gen !== S._gen) return;  // 已有新的搜索结果在渲染，放弃旧批次
    var frag = document.createDocumentFragment();
    var end = Math.min(pos + BATCH, vis.length);
    for(; pos < end; pos++){
      var idx = vis[pos], it = S.items[idx];
      var row = document.createElement('div');
      row.className = 'row' + (it.already ? ' done' : '');
      var cb = '<input type="checkbox" data-i="'+idx+'"'+(S.checked.has(idx)?' checked':'')+(it.already?' disabled':'')+'>';
      row.innerHTML = cb + '<div class="meta"><div class="t">'+esc(it.title||'未命名')+'</div>'+
                      '<div class="s">'+esc(it.meta||'')+(it.already?' · 已导入过':'')+'</div></div>';
      frag.appendChild(row);
    }
    box.appendChild(frag);
    if(pos < vis.length) requestAnimationFrame(chunk);
  }
  chunk();
  updateCount();
}
function bindChecks(){
  $('list').addEventListener('change', function(e){
    var t = e.target;
    if(!t || t.tagName !== 'INPUT' || t.disabled) return;
    var i = parseInt(t.getAttribute('data-i'), 10);
    if(isNaN(i)) return;
    if(t.checked) S.checked.add(i); else S.checked.delete(i);
    updateCount();
  });
}
function toggleAll(on){
  var boxes = $('list').querySelectorAll('input[type=checkbox]:not(:disabled)');
  for(var k=0;k<boxes.length;k++){
    boxes[k].checked = on;
    var i = parseInt(boxes[k].getAttribute('data-i'), 10);
    if(on) S.checked.add(i); else S.checked.delete(i);
  }
  updateCount();
}
function updateCount(){
  var n = S.checked.size, total = S.items.length, shown = S.visible ? S.visible.length : total;
  var kw = ($('search').value || '').trim();
  var status = '已选 '+n+' / '+total+' 个会话';
  if(kw) status += '（匹配 '+shown+' 个）';
  setStatus(status);
  var b = $('do');
  b.disabled = !n;
  b.textContent = '导入 '+n+' 个';
}
var searchTimer = null;
$('search').addEventListener('input', function(){
  var v = this.value;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(renderVisible, 100);
});
$('pick').onclick = function(){ post({type:'pick'}); };
$('all').onclick = function(){ toggleAll(true); };
$('none').onclick = function(){ toggleAll(false); };
$('cancel').onclick = function(){ post({type:'cancel'}); };
$('do').onclick = function(){
  var idxs = Array.from(S.checked).sort(function(a,b){ return a-b; });
  if(!idxs.length) return;
  post({type:'do_import', data:idxs});
};

window.chrome.webview.addEventListener('message', function(e){
  var m;
  try{ m = typeof e.data === 'string' ? JSON.parse(e.data) : e.data; }catch(err){ return; }
  if(!m || !m.type) return;
  switch(m.type){
    case 'init':
      if(m.dark) document.body.classList.add('dark');
      break;
    case 'path':
      $('path').textContent = m.data || '尚未选择文件';
      $('path').title = m.data || '';
      $('search').disabled = true;
      $('search').value = '';
      setStatus('正在解析…');
      $('do').disabled = true;
      break;
    case 'items':
      renderList(m.data || []);
      break;
    case 'error':
      $('path').textContent = m.data || '解析失败';
      $('search').disabled = true;
      setStatus(m.data || '解析失败', 'err');
      $('list').innerHTML = '<div id="empty">解析失败，换个文件试试</div>';
      $('do').disabled = true;
      break;
    case 'loading':
      $('search').disabled = true;
      setStatus(m.data || '正在解析…');
      $('do').disabled = true;
      break;
    case 'done':
      setStatus(m.data || '导入完成', 'ok');
      toast(m.data || '导入完成');
      $('do').disabled = true;
      break;
    case 'toast':
      toast(m.data);
      break;
  }
});
bindChecks();
post({type:'ready'});
</script>
</body>
</html>
"""
