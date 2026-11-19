"""检索结果侧栏的前端页面（内嵌 HTML，由 WebView2 渲染）。

之所以不用 Tk 控件堆列表：几十上百条来源会创建上千个 Tk 控件，展开/滚动/拖宽都卡。
这里一页 HTML 渲染，滚动、换行、hover 全交给浏览器，拖宽也只是重排文字。

协议（与 ui/search_panel.py）：
    Python → JS : {"type":"render","data":{"groups":[...],"cites":[...],"notes":[...]}}
                  {"type":"theme","data":{"dark":true/false}}
    JS → Python : {"type":"panel_ready"}   {"type":"open","data":"https://..."}
"""

from __future__ import annotations

PANEL_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
:root{
  --bg:#fafbfc; --text:#1a1c1f; --soft:#5a6068; --dim:#9aa0aa;
  --accent:#4d6bfe; --card:#f1f3f6; --border:#eceef2;
}
body.dark{
  --bg:#202227; --text:#e7e9ec; --soft:#a9afb8; --dim:#7c848e;
  --accent:#7c93ff; --card:#2a2d33; --border:#33363c;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;height:100%}
body{background:var(--bg);color:var(--text);font-family:"Microsoft YaHei UI","Microsoft YaHei","Segoe UI",Arial,sans-serif;font-size:13px;overflow-y:auto;overflow-x:hidden}
body::-webkit-scrollbar{width:9px}
body::-webkit-scrollbar-thumb{background:var(--border);border-radius:5px}
body::-webkit-scrollbar-thumb:hover{background:var(--dim)}
#list{padding:2px 0 18px}
.sec{font-size:12px;font-weight:600;color:var(--soft);padding:14px 14px 6px;line-height:1.5}
.row{display:grid;grid-template-columns:22px 1fr;column-gap:8px;margin:1px 8px;padding:5px 6px;border-radius:8px;cursor:pointer}
.row:hover{background:var(--card)}
.row .n{font-size:11px;color:var(--dim);text-align:right;line-height:1.55;padding-top:1px}
.row .t{color:var(--accent);line-height:1.55;word-break:break-word}
.row:hover .t{text-decoration:underline}
.row .h{color:var(--dim);font-size:11px;line-height:1.4;margin-top:2px;word-break:break-all}
.note{margin:2px 14px;padding:4px 0;color:var(--soft);font-size:12px;line-height:1.6}
.empty{color:var(--dim);padding:18px 14px;line-height:1.7}
</style>
</head>
<body>
<div id="list"></div>
<script>
"use strict";
var list = document.getElementById('list');

window.chrome.webview.addEventListener('message', function (e) {
  var msg;
  try { msg = typeof e.data === 'string' ? JSON.parse(e.data) : e.data; } catch (err) { return; }
  if (!msg || !msg.type) return;
  if (msg.type === 'render') render(msg.data || {});
  else if (msg.type === 'theme') document.body.classList.toggle('dark', !!(msg.data && msg.data.dark));
});

function post(obj){ try{ window.chrome.webview.postMessage(obj); }catch(e){} }

function host(url){
  try { var u = new URL(url); return u.hostname.replace(/^www\./, ''); }
  catch (e) { return ''; }
}

function section(title){
  var d = document.createElement('div');
  d.className = 'sec';
  d.textContent = title;
  return d;
}

function row(n, src){
  var url = (src && src.url) || '';
  var title = (src && src.title) || url;
  var wrap = document.createElement('div');
  wrap.className = 'row';
  var idx = document.createElement('div');
  idx.className = 'n';
  idx.textContent = n;
  var col = document.createElement('div');
  var t = document.createElement('div');
  t.className = 't';
  t.textContent = title;
  col.appendChild(t);
  var h = host(url);
  if (h && title.toLowerCase().indexOf(h) < 0) {
    var hd = document.createElement('div');
    hd.className = 'h';
    hd.textContent = h;
    col.appendChild(hd);
  }
  wrap.appendChild(idx);
  wrap.appendChild(col);
  wrap.title = title;
  wrap.onclick = function(){ if (url) post({type:'open', data:url}); };
  return wrap;
}

function render(d){
  list.innerHTML = '';
  var groups = (d.groups || []).filter(function(g){ return g && g.sources && g.sources.length; });
  var cites = (d.cites || []).filter(function(c){ return c && c.url; });
  var notes = (d.notes || []).filter(function(n){ return n && String(n).trim(); });

  if (!groups.length && !cites.length && !notes.length) {
    var e = document.createElement('div');
    e.className = 'empty';
    e.textContent = '这一轮没有可查看的联网内容。';
    list.appendChild(e);
    return;
  }

  var n = 0;
  // 引用排最前：编号 1..N 和正文里的上标序号一致
  if (cites.length) {
    list.appendChild(section('文中引用（对应正文序号）'));
    cites.forEach(function(c){ n += 1; list.appendChild(row(n, c)); });
  }
  groups.forEach(function(g){
    var title = String(g.query || '').trim();
    if (!title || title.indexOf('未命名') >= 0) title = '搜索来源';
    list.appendChild(section(title));
    (g.sources || []).forEach(function(s){ n += 1; list.appendChild(row(n, s)); });
  });
  if (notes.length && !n) {
    list.appendChild(section('联网动作（这一轮没有保存链接）'));
    notes.forEach(function(t){
      var d = document.createElement('div');
      d.className = 'note';
      d.textContent = t;
      list.appendChild(d);
    });
  }
}

post({type:'panel_ready'});
</script>
</body>
</html>
"""


def _split_doc(doc: str):
    css = doc.split("<style>", 1)[1].split("</style>", 1)[0]
    js = doc.split("<script>", 1)[1].split("</script>", 1)[0]
    return css, js


PANEL_CSS, PANEL_JS = _split_doc(PANEL_HTML)
