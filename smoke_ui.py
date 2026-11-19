"""临时冒烟测试：只验证界面能否构建、消息能否渲染，不发任何网络请求。"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["DEEPSEEK_API_KEY"] = "sk-smoke-test"

from ui.window import App  # noqa: E402


def pump(app, n=25):
    for _ in range(n):
        app.update()
        time.sleep(0.01)


def main() -> int:
    app = App()
    pump(app)

    app.chat.add_user("这是一条用户消息，用来测试换行与宽度自适应。第二行内容稍微长一点，看看会不会自动折行。")
    block = app.chat.add_assistant(model="deepseek-flash")
    block.append_reasoning("用户在测试界面渲染，我应该给出一段包含标题、列表、加粗、行内代码和代码块的示范。")
    block.append_content("# 渲染测试\n\n")
    block.append_content("这是一段正文，包含 **加粗**、`行内代码` 和一个[链接](https://example.com)。\n\n")
    block.append_content("## 列表\n- 第一项\n- 第二项\n\n```python\nprint('hello')\nfor i in range(3):\n    print(i)\n```\n\n> 引用一段话作为结尾。\n")
    block.finalize(
        citations=[{"url": "https://api-docs.deepseek.com", "title": "DeepSeek API 文档"}],
        footer="输入 1200（缓存命中 900） | 输出 300 | 合计 1500 tokens · 预估 $0.000301 / ¥0.00214（闲时价，deepseek-flash）",
    )
    block.add_note("联网搜索：DeepSeek V4.1 Flash 发布")
    app.chat.add_notice("（已注入网页/搜索上下文）")
    app.status_left.configure(text="这一步只是本地渲染，没有调用接口")
    pump(app, 40)

    app.input.set_text("输入框里的文字测试")
    pump(app, 10)

    # 设置窗口与导入窗口各开一次，确认能构建
    from ui.settings_window import SettingsWindow
    from ui.import_window import ImportWindow

    sw = SettingsWindow(app, app.cfg)
    pump(app, 10)
    sw.destroy()

    iw = ImportWindow(app, store=app.store, on_imported=lambda s: None)
    pump(app, 10)
    iw.destroy()

    pump(app, 10)
    app.destroy()
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
