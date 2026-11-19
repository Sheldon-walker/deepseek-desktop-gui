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
#foot{flex-shrink:0;display:flex;align-items:center;gap:10px;padding:12px 24px;border-top:1px solid var(--border-soft);background:var(--surface-soft)}
#test{font-size:12px;color:var(--text-dim);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#test.ok{color:var(--ok)} #test.bad{color:var(--danger)}
.dir{font-size:11.5px;color:var(--text-dim);word-break:break-all}
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
});

function fill(d){
  D = d;
  document.body.classList.toggle('dark', !!d.dark);
  $('api_key').value = d.api_key || '';
  $('base_url').value = 'https://api.deepseek.com';
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
  syncTemp();
}

function syncTemp(){
  var think = $('thinking').checked;
  $('temperature').disabled = think;
  $('temp-note').textContent = think ? '思考模式下不生效' : '';
}

function collect(){
  return {
    api_key: $('api_key').value,
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
