# DeepSeek Desktop

一个运行在 Windows 上的**第三方本地 GUI 客户端**，通过 **DeepSeek 官方 API** 进行对话。
对话历史以 JSON 明文保存在你自己的电脑上，界面基于 CustomTkinter + WebView2，可打包为免安装的单文件 exe。

> **请先读完这段再使用**
>
> - 本项目是**第三方开源作品，非 DeepSeek 官方出品**，与官方无隶属、授权、背书或合作关系。
> - **不自带任何 API 额度、免费次数或 API Key**。使用前需自行到 [DeepSeek 开放平台](https://platform.deepseek.com) 注册、创建自己的 API Key 并保证账号有可用余额。
> - 所有请求通过你自己的 Key 直连**官方 API 通道**，**不受网页版的访问限流限制**；可用额度由你自己的 API 账号决定，**计费以 DeepSeek 官方 API 计费标准为准**，费用由你自行承担。
> - 客户端不经过网页版，但这**不等于无限制使用**：官方 API 通道仍有速率（QPS）与余额约束，余额不足时请求会失败。

---

## 一、项目简介

网页版适合轻量随手问答，而当你需要本地留存对话、精细控制模型参数、把文件/语音接进工作流、或长时间处理超长对话时，一个本地客户端会更顺手。这个项目的定位就是：**用官方 API 的能力，配一套完全由你自己掌控的桌面界面与本地数据**。

它与网页版的关键区别：

| 对比项 | 网页版 | 本客户端（官方 API 通道） |
| --- | --- | --- |
| 访问限制 | 通常存在对话频次、高峰排队等访问限流 | 不经过网页版通道，**不受网页版访问限流限制**；受官方 API 的 QPS 与账号余额约束 |
| 额度来源 | 平台提供的访问额度 | **你自己的 API 账号余额**，额度由你充值决定 |
| 计费方式 | 按平台规则 | **按 DeepSeek 官方 API 计费标准按量计费**，以官方价格页为准 |
| 对话数据 | 存于平台云端 | **本地 JSON 文件**（`data/sessions/`），不上传第三方 |
| 参数控制 | 界面提供的选项 | 模型、temperature、top_p、max_tokens、思考强度、**系统提示词、stop 停止词**均可自定义 |
| 运行环境 | 浏览器 | Windows 桌面程序，可打包成免安装单文件 exe |

技术栈上刻意保持轻量：只用 `requests` 直接对接官方接口（不引 openai SDK，便于原样处理 `reasoning_content`、`server_tool_calls`、`annotations` 等扩展字段），界面用 CustomTkinter，对话区用系统自带的 WebView2 渲染（不打包 Chromium）。

---

## 二、核心优势

- **对话数据本地存储，不上传第三方**：每条会话一个 JSON 文件，原子写入，可整目录拷走迁移；项目不含统计、遥测或数据回传。需要明确的是：为获得回答，你的提问与上下文仍会发送给 DeepSeek 官方 API，但**本地历史文件本身不会外传**。
- **语音输入与朗读**：按住说话、松开自动识别并填入输入框；每条回答可一键朗读/停止，长文自动分段，音色可选。录音与播放音频都只走内存，不落临时文件。
- **文件解析**：PDF / Word / PPT / Excel / 图片 / 文本 / 代码 / epub 等，走官方 Files API，扫描件可 OCR，可选「含图表识别」。
- **自定义参数**：模型、temperature、top_p、max_tokens、思考强度、联网与读链接开关、代理、超时都可在设置里改。
- **自定义系统提示词 + stop 停止词**：可按自己的场景固定人设/输出格式，或用停止词精确截断生成。
- **WebView2 渲染长对话**：完整 Markdown、表格、代码高亮、引用、可折叠思考块；虚拟滚动让超长对话依然流畅，不卡顿、不裁切。
- **深色主题**：浅色/深色一键切换，切换时保留当前会话与附件；另有 Ctrl + 滚轮缩放（70%～180%）。
- **费用可见**：每条回答显示 token 明细与预估金额（本地估算，仅供参考，实际账单以官方为准），并可直接查询 API 账户余额。
- **便携与可验证**：绿色单文件 exe，配置与数据都在程序目录；附带离线自测（`selftest.py`，不需要 Key、不产生费用）和全链路自检（`cli.py verify`）。
- **同时提供命令行**：`cli.py` 覆盖对话、检索、抓取、文档、语音、账户、会话管理等子命令，便于脚本化与排查。

---

## 三、完整功能清单

### 对话

| 功能 | 说明 |
| --- | --- |
| 流式输出 | 逐字渲染，首字延迟可见 |
| 深度思考 | 思考过程单独成块，展开查看、生成完自动折叠；强度 `low / medium / high` |
| 联网搜索 | 两条路径：模型自主联网（自己决定搜什么）、客户端显式检索（展示结果列表） |
| 读取链接 | 消息里贴 URL，模型可自主读取；也可显式抓取网页正文 |
| 引用来源侧栏 | 联网回答自动展开来源链接，按搜索词分组，可折叠，点击用系统浏览器打开 |
| 多会话管理 | 新建、搜索过滤、重命名、置顶、删除、导出 Markdown、导出备份 JSON |
| 消息操作 | 复制完整 Markdown；编辑用户消息（从该条截断重发）；重新生成助手回复 |
| 停止生成 | 中途停止，已生成内容保留并落库（已生成 token 仍会计费） |
| 会话导入 | 支持官网导出 v3（`deepseek_data-*.zip` / 解压 json）、旧版 mapping 树、通用 `messages` 格式、本软件备份；自动去重、多选、预览 |
| 快捷键 | `Ctrl+N` 新建，`Enter` 发送，`Shift+Enter` 换行，`Esc` 取消录音/朗读 |

### 模型与自定义参数

| 功能 | 说明 |
| --- | --- |
| 模型 | `deepseek-flash`、`deepseek-v4-pro`，可切换 |
| temperature | 0～2；思考模式下不生效（界面会置灰） |
| top_p | 0.01～1；`deepseek-flash` 思考模式下服务端下限 0.95，客户端会提前钳制 |
| max_tokens | 0 表示不传、用服务端默认 |
| 思考强度 | `low / medium / high` |
| **系统提示词** | 自定义，留空使用内置默认提示词 |
| **stop 停止词** | 一行一个，最多 16 个，命中即停止生成 |
| 开关 | 深度思考、联网搜索、读取链接、自动朗读、含图表识别、保存历史 |
| 其他 | 代理地址、读超时、美元→人民币汇率（仅用于费用估算展示） |

### 文件解析

| 功能 | 说明 |
| --- | --- |
| 版式文档 | PDF / Word / PPT / 图片（png、jpg、webp、gif、bmp、tif）走服务端解析，扫描件可 OCR |
| 数据与代码 | txt / md / csv / json / xlsx / xls / epub / mobi 及常见代码文件直接转 Markdown |
| 含图表识别 | 可选开关，把图表按原位置交给模型（消耗更多 token） |
| 附件复用 | 上传后以 `file_id` 引用，可存进本地历史；也支持附件 + 提问组合 |

### 语音

| 功能 | 说明 |
| --- | --- |
| 语音输入 | 按住说话、松开识别，结果写入输入框可修改后再发送；WinMM 录音，16kHz 单声道 PCM，音频只在内存 |
| 语音朗读 | 每条回答可朗读/停止；长文自动分段并后台预合成；代码块、表格、链接不朗读 |
| 音色 | `stella`（女声，默认）/ `tide`（男声） |
| 自动朗读 | 顶栏/设置开关，默认关闭 |

### 界面与数据

| 功能 | 说明 |
| --- | --- |
| WebView2 对话区 | 完整 Markdown、表格、代码高亮、引用、折叠思考块；纯 ctypes 封装 COM，零额外依赖，前端不引 CDN、离线可用 |
| 虚拟滚动 | 恒定 DOM 节点数，超长对话滚动流畅、底部不裁切 |
| 深色主题 | 浅色 / 深色两套调色板，切换保留会话与附件 |
| 页面缩放 | `Ctrl + 滚轮` 70%～180%，`Ctrl + 0` 复位，比例持久化 |
| 高 DPI 感知 | 启动时显式开启，避免高分屏下窗口被虚拟化缩放 |
| 费用徽标 | 回答底部显示输入/输出/思考 token 与联网次数、预估金额；状态栏汇总 |
| 本地存储 | `data/sessions/*.json`，一条会话一个文件，原子写入；可导出 Markdown / 备份 JSON |
| 便携 | 配置与数据集中在 `data/`，整个文件夹拷走即可迁移；目录不可写时回退 `%APPDATA%\DeepSeekDesktop` |
| 账户 | 查询可用模型列表、账户余额 |
| 错误提示 | HTTP / 网络 / 流中断异常统一转成中文提示（含 401 Key 无效、402 余额不足、429 自动退避重试等） |

### 命令行（`cli.py`）

`verify`（9 项全链路自检）、`chat`、`repl`、`search`、`fetch`、`doc`、`asr`、`tts`、`models`、`balance`、`config`、`sessions`。
另有 `selftest.py`（本机假服务器离线自测，覆盖 SSE 分片、重试、错误映射、计费、导入等，**不需要 Key、不产生费用**）与 `smoke_ui.py`（界面冒烟测试）。

---

## 四、运行方法

### 环境要求

- Windows 10 / 11；对话区依赖系统 **WebView2 Runtime**（Win11 及 2021 年后的 Win10 通常已预装，缺失时会自动降级提示，不影响其他功能）
- Python **3.10+**，且该解释器自带 `tkinter`（Anaconda / Python 官方安装包均可；若 `import tkinter` 失败，换一个自带 Tk 的解释器重建虚拟环境）
- **一个你自己的 DeepSeek API Key**（本项目不提供）

### 方式 A：源码运行

```bash
git clone <你的仓库地址>
cd deepseek

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python app.py
```

Windows 下也可以直接双击 `run.bat`（自动优先使用 `.venv` 里的 `pythonw.exe`，无控制台窗口）。
运行时依赖只有 `requests` 与 `customtkinter`；`pyinstaller` 仅在打包时需要。

### 配置 API Key（三选一）

1. **界面**：打开「设置」填写 API Key（推荐）。
2. **命令行**：
   ```bash
   python cli.py config set-key sk-你的Key
   python cli.py config show        # 查看（Key 会打码显示）
   ```
3. **环境变量**（优先级最高、不落盘）：
   ```bat
   set DEEPSEEK_API_KEY=sk-你的Key        :: cmd
   ```
   ```powershell
   $env:DEEPSEEK_API_KEY = 'sk-你的Key'   # PowerShell
   ```

> Key 以明文保存在程序目录的 `data/config.json`，**仅存本机**。该文件已被 `.gitignore` 屏蔽，请勿提交到任何仓库、不要截图外发。若不希望落盘，用环境变量方式。

### 首次验证

```bash
python cli.py verify   # 真实调用 9 项官方接口，会产生少量 API 费用
python selftest.py     # 离线自测，不需要 Key，不产生任何费用
```

`verify` 依次检查 Key 与模型列表、流式对话、深度思考、搜索、抓取、文件解析、带文件对话、模型自主联网、异常捕获，并给出 PASS/FAIL 汇总。

### 方式 B：直接运行 exe

从 Releases 下载 `DeepSeekDesktop.exe` 双击即可，**无需 Python 环境**。配置与会话会自动生成在 exe 同目录的 `data/` 下，整个文件夹拷走即可迁移。

---

## 五、PyInstaller 打包教程

仓库自带 `build.bat`，也可按下面步骤手动打包出单文件 exe。

**第 1 步：安装打包工具**

```bash
.venv\Scripts\activate
pip install "pyinstaller>=6.10"
```

**第 2 步：确认本机 Tcl/Tk 运行时 DLL 路径**

`build.bat` 顶部有一行 `set LIB=D:\ProgramData\anaconda3\Library\bin`，指向 Anaconda 的 `Library\bin`。
**换机器时必须改成你自己的路径**；若使用普通 CPython（自带 Tcl/Tk，DLL 已能被 PyInstaller 找到），可以删掉这些 `--add-binary` 行。

**第 3 步：执行打包**

```bat
build.bat
```

等价于在项目根目录执行（`^` 为 cmd 换行符）：

```bat
@echo off
set LIB=D:\ProgramData\anaconda3\Library\bin

call .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name DeepSeekDesktop --icon app.ico --collect-all customtkinter ^
  --add-data "assets\icons;assets\icons" ^
  --add-data "app.ico;." ^
  --add-binary "lib\WebView2Loader.dll;." ^
  --add-binary "%LIB%\tcl86t.dll;." ^
  --add-binary "%LIB%\tk86t.dll;." ^
  --add-binary "%LIB%\ffi.dll;." ^
  --add-binary "%LIB%\libexpat.dll;." ^
  --add-binary "%LIB%\liblzma.dll;." ^
  --add-binary "%LIB%\libbz2.dll;." ^
  --add-binary "%LIB%\libmpdec-4.dll;." ^
  --add-binary "%LIB%\libssl-3-x64.dll;." ^
  --add-binary "%LIB%\libcrypto-3-x64.dll;." ^
  --add-binary "%LIB%\zlib.dll;." ^
  app.py
```

**第 4 步：取产物**

生成 `dist\DeepSeekDesktop.exe`（约 15–25 MB，取决于 Python 基线），双击运行，无需 Python。

**几个关键点**

| 参数 / 文件 | 为什么需要 |
| --- | --- |
| `--onefile --windowed` | 单文件、无控制台窗口 |
| `--collect-all customtkinter` | CustomTkinter 的主题 JSON 资源必须显式收集，否则界面样式丢失 |
| `--add-binary` 一列 DLL | Anaconda 的 Tcl/Tk/OpenSSL 等 DLL 不在 PyInstaller 默认搜索路径，缺失时 exe 启动即崩 |
| `lib\WebView2Loader.dll` | 对话区 WebView2 的加载器（约 190 KB）；Chromium 引擎走系统 Evergreen Runtime，不打进 exe |
| `--icon app.ico` | 应用图标 |
| DPI 感知 | `app.py` 在创建窗口前调用 `SetProcessDpiAwarenessContext`，避免高分屏下窗口被缩放 |

**注意事项**

- `*.spec` 是 PyInstaller 自动生成的中间文件，且**写死了本机绝对路径**，已由 `.gitignore` 屏蔽，不要提交；复现打包用上面的命令即可。
- **不要把 exe / `dist/` / `build/` 提交进仓库**。对外分发请用 GitHub Releases 上传二进制文件。
- 打包后 `data/` 与 exe 同级生成，属于绿色便携结构；exe 放在只读目录时会自动回退到 `%APPDATA%\DeepSeekDesktop`。

---

## 六、目录结构

```
deepseek/
├─ app.py                    图形界面入口
├─ cli.py                    命令行（verify / chat / repl / search / fetch / doc / asr / tts …）
├─ dskit/                    API 封装层（client / search / docs / importer / audio / asr /
│                            tts / player / session / usage / config / errors / console）
├─ ui/                       界面层（CustomTkinter + WebView2，含 chat_html / wv2 / theme …）
├─ assets/icons/             界面图标
├─ lib/WebView2Loader.dll    WebView2 加载器（随仓库分发）
├─ app.ico / app.png         应用图标
├─ run.bat / cli.bat / build.bat  启动 / 命令行 / 打包脚本
├─ requirements.txt
├─ selftest.py / smoke_ui.py     离线自测 / 界面冒烟测试
├─ README.md
└─ data/                     ★ 运行时自动生成（配置 + 会话 + WebView2 缓存），不入库
```

---

## 七、免责声明

1. **非官方产品**。本项目为第三方独立开发的本地 GUI 客户端，**不是 DeepSeek 官方出品**，未经官方授权、背书或认可，与官方不存在隶属、合作或代理关系。"DeepSeek" 及相关名称、标识、商标归其各自权利人所有，本项目仅用于说明其所兼容的服务。
2. **不提供任何额度**。本项目不附带、不赠送、不代管 API Key、免费额度、访问次数或充值服务。使用前须自行在 DeepSeek 开放平台注册、创建 API Key，并确保账号有可用余额。
3. **费用自行承担**。所有请求通过你自己的 Key 直连 DeepSeek 官方 API，由此产生的**一切费用按 DeepSeek 官方 API 计费标准结算，由使用者自行承担**。客户端内显示的 token 用量与金额为本地估算，仅供参考，**实际账单以官方为准**。模型、接口与价格可能调整，请以官方文档与价格页为准。
4. **关于"不受网页版限流"的准确说明**。客户端不经过网页版通道，因此不受网页版的访问限流与排队限制；但这**不等于无限制或免费使用**——官方 API 通道仍有速率限制（QPS）、并发约束，余额为零时请求会失败（返回 402）。请合规使用自有账号，勿用于绕过任何服务条款。
5. **数据说明**。对话历史以 JSON 明文保存在本机 `data/sessions/`，**不会上传给除 DeepSeek 官方 API 以外的任何第三方服务**，项目不含统计、遥测或数据回传。但为获得回答，你的提问、附件与上下文**必然需要发送给 DeepSeek 官方 API**；文件解析、语音识别、语音合成、联网搜索、网页抓取等功能同样由官方接口在服务端处理。请勿在明文本地文件中存放敏感信息，并自行做好备份与访问控制。
6. **API Key 安全**。Key 明文存于 `data/config.json`。请勿提交到任何仓库、不要截图外发；**若曾误提交，请立即到开放平台撤销并重新生成该 Key**。
7. **按"现状"提供，无担保**。不保证服务不间断、无错误或适合特定用途；作者不对因使用本软件产生的内容、费用、数据丢失或任何间接损失负责。AI 生成内容可能存在错误，重要场景请自行核实。
8. **合规使用**。使用本软件即表示你同意遵守 DeepSeek 的服务条款、API 使用政策及适用法律法规，不得用于违法违规用途。

---

## 八、计费与常见问题

- **费用从哪来**：对话按输入/输出 token 计费，联网搜索、网页抓取、文档解析、语音识别、语音合成另有按次/按量计费；具体项目与单价以官方价格页为准。界面里的费用徽标是估算值，不是账单。
- **停止生成仍会计费**：中途停止只是不再继续读流，已经生成的 token 照样计费。
- **401 / 402**：401 表示 Key 无效，请重新填写；402 表示账户余额不足，请到开放平台充值。
- **WebView2 不可用**：对话区会降级显示提示，安装 Microsoft Edge WebView2 Runtime 后重启即可，其余功能不受影响。
- **界面空白 / 样式丢失**：多为打包时漏了 `--collect-all customtkinter` 或 Tcl/Tk DLL，按第五节重新打包。

---

## 九、许可证

本项目**尚未指定开源许可证**，正式发布前请补充 `LICENSE` 文件并明确使用条款。
