"""设置页面的 HTML（WebView2 渲染）。

整体风格跟主界面一致；表单值由 ui/settings_web.py 用 init 消息灌入，
点保存/测试时把整份表单 postMessage 回 Python。
"""

from __future__ import annotations

SETTINGS_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
:root{
  --bg:#ffffff; --surface:#ffffff; --surface-soft:#fafbfc; --card:#f5f6f8;
  --border:#e4e6ea; --border-soft:#eff0f3;
  --text:#1a1c1f; --text-soft:#5a6068; --text-dim:#9aa0aa;
  --accent:#4d6bfe; --accent-soft:#edf0ff; --danger:#e5484d; --ok:#1a7f37;
}
body.dark{
  --bg:#16181b; --surface:#1c1e22; --surface-soft:#202227; --card:#26282d;
  --border:#34373d; --border-soft:#2a2d32;
  --text:#e7e9ec; --text-soft:#a9afb8; --text-dim:#7c848e;
  --accent:#7c93ff; --accent-soft:#262c45; --danger:#f0716e; --ok:#4ade80;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;height:100%;overflow:hidden;background:var(--bg)}
body{font-family:"Microsoft YaHei UI","Microsoft YaHei","Segoe UI",Arial,sans-serif;font-size:13.5px;color:var(--text)}
#app{display:flex;flex-direction:column;height:100%}
#head{padding:18px 24px 10px;flex-shrink:0}
#head h1{margin:0;font-size:19px}
#head p{margin:4px 0 0;font-size:12px;color:var(--text-dim)}
#form{flex:1;overflow-y:auto;padding:0 24px 12px}
#form::-webkit-scrollbar{width:10px}
#form::-webkit-scrollbar-thumb{background:var(--border);border-radius:5px}
.sec{font-size:12.5px;font-weight:700;color:var(--accent);margin:18px 0 8px}
.row{display:flex;align-items:center;gap:12px;margin-bottom:10px}
.row > label.k{width:96px;flex-shrink:0;color:var(--text-soft);font-size:13px}
.row .ctl{flex:1;min-width:0;display:flex;align-items:center;gap:8px}
input[type=text],input[type=password],input[type=number],select,textarea{
  width:100%;border:1px solid var(--border);background:var(--surface);color:var(--text);
  border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none;
}
input:focus,select:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
input:disabled,select:disabled{opacity:.5;cursor:not-allowed}
textarea{resize:vertical;line-height:1.6}
.hint{font-size:11.5px;color:var(--text-dim);margin:-4px 0 10px 108px;line-height:1.6}
.sw{display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none}
.sw input{width:16px;height:16px;accent-color:var(--accent)}
.small{width:110px !important;flex-shrink:0}
.btn{height:32px;padding:0 14px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text-soft);font-size:12.5px;cursor:pointer}
.btn:hover{background:var(--surface-soft);color:var(--text)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.btn.primary:hover{filter:brightness(1.06)}
.btn.solid{background:var(--text);border-color:var(--text);color:var(--bg);font-weight:600}
.btn.solid:hover{filter:brightness(1.15)}
.btn:disabled{opacity:.45;cursor:not-allowed}
#foot{flex-shrink:0;display:flex;align-items:center;gap:10px;padding:12px 24px;border-top:1px solid var(--border-soft);background:var(--surface-soft)}
#test{font-size:12px;color:var(--text-dim);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#test.ok{color:var(--ok)} #test.bad{color:var(--danger)}
.dir{font-size:11.5px;color:var(--text-dim);word-break:break-all}
.upd-card{border:1px solid var(--border);border-radius:10px;padding:14px 16px;background:var(--surface-soft);margin-bottom:10px}
/* ---------- 阅读排版 ---------- */
.typo-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 18px;margin:2px 0 10px}
.typo-item{display:flex;align-items:center;gap:8px;min-width:0}
.typo-item .k2{width:62px;flex-shrink:0;font-size:12px;color:var(--text-soft)}
.typo-item input[type=range]{flex:1;min-width:0;accent-color:var(--accent);height:18px}
.typo-item .v{width:48px;flex-shrink:0;text-align:right;font-size:12px;color:var(--text-dim);font-variant-numeric:tabular-nums}
.typo-preview{border:1px solid var(--border);border-radius:10px;background:var(--surface);padding:14px var(--tp-pad,36px);margin-bottom:10px;
  font-size:var(--tp-fs,16px);line-height:var(--tp-lh,1.85);font-family:var(--tp-font,inherit);color:var(--text);
  max-height:190px;overflow:auto}
.typo-preview h4{margin:0 0 .5em;font-size:1.12em}
.typo-preview p{margin:var(--tp-para,.55em) 0}
.typo-preview ul{margin:var(--tp-para,.55em) 0;padding-left:1.5em}
.typo-preview code{background:var(--card);border-radius:4px;padding:1px 5px;font-size:.88em}
.typo-preview .tp-note{font-size:11px;color:var(--text-dim)}
.typo-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}
.typo-bar .btn{height:28px;padding:0 11px;font-size:12px}
#font_status{font-size:11.5px;color:var(--text-dim)}
.upd-top{display:flex;justify-content:space-between;align-items:center;gap:12px;font-size:12.5px;color:var(--text-soft)}
.upd-top b{color:var(--text);font-weight:600}
.upd-msg{margin:10px 0 12px;font-size:13px;color:var(--text);line-height:1.5}
.upd-msg.ok{color:var(--ok)} .upd-msg.bad{color:var(--danger)}
.upd-msg.new{color:var(--accent);font-weight:700}
.upd-msg.pre{color:var(--text-soft)}
.upd-tag{display:inline-block;margin-left:6px;padding:1px 6px;border-radius:5px;background:var(--accent-soft);color:var(--accent);font-size:11px;font-weight:600;vertical-align:middle}
.upd-btns{display:flex;gap:8px;flex-wrap:wrap}
.upd-notes{display:none;margin-top:12px;padding:10px 12px;border:1px solid var(--border-soft);border-radius:8px;background:var(--surface);font-size:12px;line-height:1.7;white-space:pre-wrap;word-break:break-word;max-height:190px;overflow:auto;color:var(--text-soft)}
.upd-notes.show{display:block}
</style>
</head>
<body>
<div id="app">
  <div id="head">
    <h1>设置</h1>
    <p>改完点「保存」生效；带 * 的项需要重启后完全生效。</p>
  </div>
  <div id="form">
    <div class="sec">账户</div>
    <div class="row"><label class="k">API Key</label><div class="ctl">
      <input type="password" id="api_key" placeholder="sk-...">
      <button class="btn" id="btn-test" style="flex-shrink:0">测试连接</button>
    </div></div>
    <div class="row"><label class="k">接口地址</label><div class="ctl"><input type="text" id="base_url" disabled></div></div>

    <div class="sec">外观</div>
    <div class="row"><label class="k">主题</label><div class="ctl">
      <select id="theme"><option value="light">浅色</option><option value="dark">深色</option></select>
    </div></div>

    <div class="sec">阅读排版</div>
    <div class="typo-grid">
      <div class="typo-item"><span class="k2">左右留白</span><input type="range" id="chat_pad_x" min="8" max="120" step="2"><span class="v" id="v_pad_x">36 px</span></div>
      <div class="typo-item"><span class="k2">行间距</span><input type="range" id="chat_line_height" min="1.2" max="2.6" step="0.05"><span class="v" id="v_lh">1.85</span></div>
      <div class="typo-item"><span class="k2">正文字号</span><input type="range" id="chat_font_size" min="12" max="24" step="1"><span class="v" id="v_fs">16 px</span></div>
      <div class="typo-item"><span class="k2">字体</span><select id="chat_font_family" style="flex:1"></select></div>
    </div>
    <div class="typo-bar">
      <button class="btn" id="btn-pick-font">上传字体…</button>
      <button class="btn" id="btn-remove-font">移除自定义字体</button>
      <button class="btn" id="btn-typo-reset">恢复默认</button>
      <span id="font_status"></span>
    </div>
    <div class="typo-preview" id="typo_preview">
      <h4>💎 长文阅读示例</h4>
      <p>对话内容以 <b>本地 JSON</b> 保存，不上传第三方；适合需要长期交流、反复打磨的创作场景。</p>
      <ul><li>段落之间留有呼吸感，行距更舒展</li><li>支持 <code>system_prompt</code> 与停止词等精细参数</li></ul>
      <p class="tp-note">预览区实时反映上方设置，保存后应用到对话页。</p>
    </div>
    <div class="hint">仅影响对话消息区（侧栏、输入栏保持原尺寸）。上传的字体文件保存在本机 data/fonts/，不会随程序上传到任何服务器。</div>

    <div class="sec">生成参数</div>
    <div class="row"><label class="k">temperature</label><div class="ctl">
      <input type="number" id="temperature" step="0.1" min="0" max="2" class="small">
      <span class="hint2" id="temp-note" style="font-size:11.5px;color:var(--text-dim)"></span>
    </div></div>
    <div class="hint">0 ~ 2，越大越发散。开启深度思考时该参数不生效，会被忽略。</div>
    <div class="row"><label class="k">top_p</label><div class="ctl"><input type="number" id="top_p" step="0.05" min="0.01" max="1" class="small"></div></div>
    <div class="hint">核采样阈值。deepseek-flash 在思考模式下最低 0.95，低于 0.95 会按 0.95 发送。</div>
    <div class="row"><label class="k">最大输出</label><div class="ctl">
      <input type="number" id="max_tokens" step="256" min="0" class="small">
      <span style="font-size:11.5px;color:var(--text-dim)">tokens，0 = 服务端默认</span>
    </div></div>
    <div class="row" style="align-items:flex-start"><label class="k" style="padding-top:6px">系统提示词</label><div class="ctl">
      <textarea id="system_prompt" rows="4" placeholder="留空则使用内置提示词"></textarea>
    </div></div>
    <div class="row" style="align-items:flex-start"><label class="k" style="padding-top:6px">停止词</label><div class="ctl">
      <textarea id="stop_words" rows="3" placeholder="一行一个，最多 16 个"></textarea>
    </div></div>

    <div class="sec">默认开关</div>
    <div class="row"><label class="k">深度思考</label><div class="ctl"><label class="sw"><input type="checkbox" id="thinking"> 默认开启</label></div></div>
    <div class="row"><label class="k">联网搜索</label><div class="ctl"><label class="sw"><input type="checkbox" id="web_search"> 默认开启</label></div></div>
    <div class="row"><label class="k">读取链接</label><div class="ctl"><label class="sw"><input type="checkbox" id="read_url"> 自动读取消息里的网页链接</label></div></div>
    <div class="row"><label class="k">思考过程</label><div class="ctl"><label class="sw"><input type="checkbox" id="show_reasoning"> 界面显示思考过程</label></div></div>
    <div class="row"><label class="k">本地历史</label><div class="ctl"><label class="sw"><input type="checkbox" id="save_history"> 自动保存对话历史</label></div></div>
    <div class="row"><label class="k">文件解析</label><div class="ctl"><label class="sw"><input type="checkbox" id="rich"> 默认按「含图表识别」解析</label></div></div>

    <div class="sec">语音</div>
    <div class="row"><label class="k">朗读音色</label><div class="ctl"><select id="voice"></select></div></div>
    <div class="row"><label class="k">自动朗读</label><div class="ctl"><label class="sw"><input type="checkbox" id="auto_read"> 新回答生成完自动朗读</label></div></div>

    <div class="sec">网络</div>
    <div class="row"><label class="k">代理</label><div class="ctl"><input type="text" id="proxy" placeholder="http://127.0.0.1:7890，留空走系统代理"></div></div>
    <div class="row"><label class="k">超时</label><div class="ctl"><input type="number" id="timeout" step="10" min="10" class="small"><span style="font-size:11.5px;color:var(--text-dim)">秒</span></div></div>
    <div class="row"><label class="k">数据目录</label><div class="ctl"><span class="dir" id="data_dir"></span></div></div>

    <div class="sec">软件更新</div>
    <div class="upd-card">
      <div class="upd-top">
        <span>当前版本：<b id="upd-cur">—</b></span>
        <span>可用版本：<b id="upd-lat">—</b></span>
      </div>
      <div class="upd-msg" id="upd-msg">点「检查更新」查看是否有新版本。</div>
      <div class="upd-btns">
        <button class="btn" id="btn-check">检查更新</button>
        <button class="btn solid" id="btn-download" disabled>下载更新</button>
        <button class="btn" id="btn-changelog" disabled>查看更新日志</button>
      </div>
      <div class="upd-notes" id="upd-notes"></div>
    </div>
    <div class="row"><label class="k">更新源</label><div class="ctl"><input type="text" id="update_repo" placeholder="owner/repo，留空使用默认仓库"></div></div>
    <div class="hint">仅点「检查更新」时向 GitHub 发起一次匿名请求，不发送 API Key、对话或任何本地数据；不自动检查、不上报。</div>
  </div>
  <div id="foot">
    <span id="test"></span>
    <button class="btn" id="btn-cancel">取消</button>
    <button class="btn primary" id="btn-save">保存</button>
  </div>
</div>
<script>
"use strict";
var D = {};
function $(id){ return document.getElementById(id); }
function post(o){ try{ window.chrome.webview.postMessage(o); }catch(e){} }

window.chrome.webview.addEventListener('message', function(e){
  var msg;
  try{ msg = typeof e.data === 'string' ? JSON.parse(e.data) : e.data; }catch(err){ return; }
  if(!msg || !msg.type) return;
  if(msg.type === 'init') fill(msg.data || {});
  else if(msg.type === 'testing'){ $('btn-test').disabled = !!msg.data; $('test').textContent = msg.data ? '正在连接…' : $('test').textContent; }
  else if(msg.type === 'test_result'){
    var d = msg.data || {};
    $('test').textContent = d.text || '';
    $('test').className = d.ok ? 'ok' : 'bad';
  }
  else if(msg.type === 'upd_status') updChecking(!!msg.data);
  else if(msg.type === 'upd_result') renderUpd(msg.data || {});
  else if(msg.type === 'font_face') setFontFace(msg.data || '');
  else if(msg.type === 'font_picked') onFontPicked(msg.data || {});
  else if(msg.type === 'font_error'){ $('font_status').textContent = msg.data || '字体导入失败'; }
});

// Python 注入的自定义字体 @font-face（base64 data URI），仅本设置页预览使用
function setFontFace(css){
  var st = $('ds-fontface');
  if(!st){ st=document.createElement('style'); st.id='ds-fontface'; document.head.appendChild(st); }
  st.textContent = css || '';
  if(css){ D.font_css = D.font_css || {}; D.font_css.custom = '"DSCustomFont","Microsoft YaHei",sans-serif'; applyTypoPreview(); }
}
function onFontPicked(d){
  var sel = $('chat_font_family');
  var opt = sel.querySelector('option[value="custom"]');
  if(!d.name){
    if(opt) opt.remove();
    sel.value = '';
    D.chat_font_name = '';
    $('btn-remove-font').disabled = true;
    $('font_status').textContent = '';
    applyTypoPreview();
    return;
  }
  if(!opt){ opt=document.createElement('option'); opt.value='custom'; sel.appendChild(opt); }
  opt.textContent = '自定义：' + d.name;
  sel.value = 'custom';
  D.chat_font_name = d.name;
  $('btn-remove-font').disabled = false;
  $('font_status').textContent = '已导入：' + d.name;
  applyTypoPreview();
}

function fill(d){
  D = d;
  document.body.classList.toggle('dark', !!d.dark);
  $('api_key').value = d.api_key || '';
  $('base_url').value = d.base_url || '';
  $('theme').value = d.theme || 'light';
  $('temperature').value = d.temperature;
  $('top_p').value = d.top_p;
  $('max_tokens').value = d.max_tokens || 0;
  $('system_prompt').value = d.system_prompt || '';
  $('stop_words').value = d.stop_words || '';
  $('proxy').value = d.proxy || '';
  $('timeout').value = d.timeout || 120;
  $('data_dir').textContent = d.data_dir || '';
  ['thinking','web_search','read_url','show_reasoning','save_history','rich','auto_read'].forEach(function(k){
    $(k).checked = !!d[k];
  });
  var voice = $('voice'); voice.innerHTML = '';
  Object.keys(d.voices || {}).forEach(function(k){
    var o = document.createElement('option'); o.value = k; o.textContent = d.voices[k]; voice.appendChild(o);
  });
  voice.value = d.voice || 'stella';
  $('upd-cur').textContent = d.version || '—';
  $('upd-lat').textContent = d.latest_version || '—';
  $('update_repo').value = d.update_repo || d.repo_default || '';
  // 阅读排版
  var sel = $('chat_font_family'); sel.innerHTML = '';
  (d.font_presets || []).forEach(function(p){
    var o = document.createElement('option'); o.value = p.value; o.textContent = p.label; sel.appendChild(o);
  });
  D.font_css = d.font_css || {};
  $('chat_pad_x').value = d.chat_pad_x != null ? d.chat_pad_x : 36;
  $('chat_line_height').value = d.chat_line_height != null ? d.chat_line_height : 1.85;
  $('chat_font_size').value = d.chat_font_size != null ? d.chat_font_size : 16;
  var fam = d.chat_font_family || '';
  if(fam === 'custom'){
    var o = document.createElement('option'); o.value='custom';
    o.textContent = d.chat_font_name ? ('自定义：' + d.chat_font_name) : '自定义字体';
    sel.appendChild(o);
  }
  sel.value = fam;
  $('btn-remove-font').disabled = !d.chat_font_name;
  $('font_status').textContent = d.chat_font_name ? ('已导入：' + d.chat_font_name) : '';
  applyTypoPreview();
  syncTemp();
}

// ---------------- 阅读排版实时预览 ----------------
function typoValues(){
  return {
    pad_x: Number($('chat_pad_x').value),
    lh: Number($('chat_line_height').value),
    fs: Number($('chat_font_size').value),
    fam: $('chat_font_family').value
  };
}
function applyTypoPreview(){
  var v = typoValues();
  $('v_pad_x').textContent = v.pad_x + ' px';
  $('v_lh').textContent = v.lh.toFixed(2);
  $('v_fs').textContent = v.fs + ' px';
  var box = $('typo_preview'), s = box.style;
  s.setProperty('--tp-pad', v.pad_x + 'px');
  s.setProperty('--tp-lh', String(v.lh));
  s.setProperty('--tp-fs', v.fs + 'px');
  s.setProperty('--tp-para', Math.min(0.95, Math.max(0.35, 0.35 + (v.lh - 1.4) * 0.45)).toFixed(2) + 'em');
  var css = (D.font_css && D.font_css[v.fam]) || '';
  if(css) s.setProperty('--tp-font', css); else s.removeProperty('--tp-font');
  // 自定义字体的 @font-face 由 Python 注入到本页
}
['chat_pad_x','chat_line_height','chat_font_size','chat_font_family'].forEach(function(id){
  $(id).addEventListener('input', applyTypoPreview);
  $(id).addEventListener('change', applyTypoPreview);
});

function syncTemp(){
  var think = $('thinking').checked;
  $('temperature').disabled = think;
  $('temp-note').textContent = think ? '思考模式下不生效' : '';
}

function updChecking(on){
  $('btn-check').disabled = !!on;
  $('btn-check').textContent = on ? '检查中…' : '检查更新';
  if(on){
    $('upd-msg').className = 'upd-msg';
    $('upd-msg').textContent = '正在检查更新…';
    $('upd-notes').classList.remove('show');
  }
}

function renderUpd(d){
  D.upd = d;
  $('upd-cur').textContent = d.current || D.version || '—';
  var lat = $('upd-lat');
  // 用 textContent 拼接，避免把线上 tag 当 HTML 注入
  lat.textContent = d.latest || '—';
  if(d.latest){ lat.textContent = ''; lat.appendChild(document.createTextNode(d.latest)); }
  if(d.prerelease && d.latest){
    var tag = document.createElement('span'); tag.className='upd-tag'; tag.textContent='预发布';
    lat.appendChild(tag);
  }
  var m = $('upd-msg');
  m.textContent = d.message || '';
  m.className = 'upd-msg' + (!d.ok ? ' bad' : (d.has_update ? ' new' : (d.prerelease ? ' pre' : ' ok')));
  $('btn-download').disabled = !(d.ok && d.has_update && (d.download_url || d.html_url));
  $('btn-changelog').disabled = !(d.ok && (d.notes || d.html_url));
  $('upd-notes').textContent = d.notes || '';
  $('upd-notes').classList.remove('show');
}

function collect(){
  return {
    api_key: $('api_key').value,
    base_url: $('base_url').value,
    theme: $('theme').value,
    thinking: $('thinking').checked,
    web_search: $('web_search').checked,
    read_url: $('read_url').checked,
    show_reasoning: $('show_reasoning').checked,
    save_history: $('save_history').checked,
    rich: $('rich').checked,
    auto_read: $('auto_read').checked,
    voice: $('voice').value,
    temperature: $('temperature').value,
    top_p: $('top_p').value,
    max_tokens: $('max_tokens').value,
    system_prompt: $('system_prompt').value,
    stop_words: $('stop_words').value,
    proxy: $('proxy').value,
    timeout: $('timeout').value,
    update_repo: $('update_repo').value,
    chat_pad_x: Number($('chat_pad_x').value),
    chat_line_height: Number($('chat_line_height').value),
    chat_font_size: Number($('chat_font_size').value),
    chat_font_family: $('chat_font_family').value,
    effort: D.effort
  };
}

$('thinking').addEventListener('change', syncTemp);
$('theme').addEventListener('change', function(){
  document.body.classList.toggle('dark', this.value === 'dark');
});
$('btn-save').onclick = function(){ post({type:'save', data: collect()}); };
$('btn-cancel').onclick = function(){ post({type:'close'}); };
$('btn-test').onclick = function(){ $('test').className = ''; post({type:'test', data: collect()}); };
$('btn-check').onclick = function(){ post({type:'check_update', data:{repo: $('update_repo').value}}); };
$('btn-pick-font').onclick = function(){ post({type:'pick_font'}); };
$('btn-remove-font').onclick = function(){ post({type:'remove_font'}); };
$('btn-typo-reset').onclick = function(){
  $('chat_pad_x').value = 36; $('chat_line_height').value = 1.85; $('chat_font_size').value = 16;
  $('chat_font_family').value = ''; applyTypoPreview();
};
$('btn-download').onclick = function(){ if(!this.disabled) post({type:'download_update'}); };
$('btn-changelog').onclick = function(){
  if(this.disabled) return;
  var box = $('upd-notes');
  if((D.upd && D.upd.notes) || box.textContent){ box.classList.toggle('show'); }
  else { post({type:'open_release'}); }
};
document.addEventListener('keydown', function(e){
  if(e.key === 'Escape') post({type:'close'});
  if((e.ctrlKey || e.metaKey) && e.key === 's'){ e.preventDefault(); $('btn-save').click(); }
});
post({type:'ready'});
</script>
</body>
</html>
"""


def settings_html() -> str:
    """返回设置页 HTML（留成函数，方便以后按主题/语言替换）。"""
    return SETTINGS_HTML
