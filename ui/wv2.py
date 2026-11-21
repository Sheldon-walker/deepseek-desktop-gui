"""WebView2 嵌入层：纯 ctypes 调 COM 接口，零第三方依赖。

只随应用分发一个约 190KB 的 WebView2Loader.dll，引擎走系统自带的
Evergreen Runtime（Win11 自带、Win10 2021 年后普遍预装）。

用法：
    wv = WebView(parent_hwnd, on_ready=..., on_message=..., on_error=...)
    # 在 Tk 主循环里定期调用 wv.poll()，把就绪/消息/错误派发到主线程
    wv.set_bounds(x, y, w, h)   # 物理像素，相对 parent_hwnd 客户区
    wv.navigate_html(html)
    wv.post_json('{"type":"...","data":...}')
"""

from __future__ import annotations

import ctypes
import queue
import sys
import time
from ctypes import wintypes
from pathlib import Path

# --------------------------------------------------------------------------- 常量与类型
HRESULT = ctypes.c_long
ULONG = ctypes.c_ulong
BOOL = wintypes.BOOL

S_OK = 0
S_FALSE = 1
E_NOINTERFACE = 0x80004002
COINIT_APARTMENTTHREADED = 0x2
RPC_E_CHANGED_MODE = 0x80010106


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class EventRegistrationToken(ctypes.Structure):
    _fields_ = [("value", ctypes.c_longlong)]


def _guid(s: str) -> GUID:
    a, b, c, d, e = s.split("-")
    return GUID(
        int(a, 16),
        int(b, 16),
        int(c, 16),
        (ctypes.c_ubyte * 8)(*bytes.fromhex(d + e)),
    )


def _guid_eq(x: GUID, y: GUID) -> bool:
    return (
        x.Data1 == y.Data1
        and x.Data2 == y.Data2
        and x.Data3 == y.Data3
        and bytes(x.Data4) == bytes(y.Data4)
    )


IID_IUNKNOWN = _guid("00000000-0000-0000-C000-000000000046")
IID_EnvironmentCompletedHandler = _guid("4e8a3389-c9d8-4bd2-b6b5-124fee6cc14d")
IID_ControllerCompletedHandler = _guid("6c4819f3-c9b7-4260-8127-c9f5bde7f68c")
IID_WebMessageReceivedEventHandler = _guid("57213f19-00e6-49fa-8e07-898ea01ecbd2")
IID_WebMessageReceivedEventArgs = _guid("0f99a40c-e962-4207-9e92-e3d542eff849")

# --------------------------------------------------------------------------- loader 加载
def _loader_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "WebView2Loader.dll"
    return Path(__file__).resolve().parent.parent / "lib" / "WebView2Loader.dll"


_loader = None
_CreateCoreWebView2EnvironmentWithOptions = None


def _ensure_loader() -> None:
    global _loader, _CreateCoreWebView2EnvironmentWithOptions
    if _loader is not None:
        return
    path = _loader_path()
    if not path.exists():
        raise RuntimeError(f"找不到 WebView2Loader.dll（{path}）")
    try:
        _loader = ctypes.WinDLL(str(path))
    except OSError as exc:
        raise RuntimeError(f"加载 WebView2Loader.dll 失败：{exc}") from exc
    _CreateCoreWebView2EnvironmentWithOptions = _loader.CreateCoreWebView2EnvironmentWithOptions
    _CreateCoreWebView2EnvironmentWithOptions.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    _CreateCoreWebView2EnvironmentWithOptions.restype = HRESULT


def runtime_available() -> bool:
    """检测系统是否装了 WebView2 Runtime / Edge。"""
    try:
        _ensure_loader()
    except RuntimeError:
        return False
    try:
        version = wintypes.LPWSTR()
        fn = _loader.GetAvailableCoreWebView2BrowserVersionString
        fn.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPWSTR)]
        fn.restype = HRESULT
        hr = fn(None, ctypes.byref(version))
        if hr < 0 or not version.value:
            return False
        ole32 = ctypes.WinDLL("ole32")
        ole32.CoTaskMemFree(ctypes.cast(version, ctypes.c_void_p))
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- COM 接口指针
class _ComInterface:
    """一个 COM 接口指针的轻量包装，按 vtable 序号调用方法。

    注意：COM 每个 vtable 前 3 个槽是 IUnknown 的 QueryInterface/AddRef/Release，
    接口方法从第 4 个槽（下标 3）开始。这里 `_method` 的 `index` 是**接口方法序号**
    （不含 IUnknown 的 3 个），内部自动 +3。
    """

    _IUNKNOWN_METHODS = 3

    def __init__(self, ptr: int) -> None:
        if not ptr:
            raise ValueError("COM 接口指针为空")
        self._ptr = ptr

    def _method(self, index: int, restype, argtypes, *args):
        vtbl = ctypes.cast(self._ptr, ctypes.POINTER(ctypes.c_void_p)).contents
        fn = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[index + self._IUNKNOWN_METHODS]
        proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
        return proto(fn)(self._ptr, *args)

    def addref(self) -> int:
        vtbl = ctypes.cast(self._ptr, ctypes.POINTER(ctypes.c_void_p)).contents
        fn = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[1]
        return ctypes.WINFUNCTYPE(ULONG, ctypes.c_void_p)(fn)(self._ptr)

    def release(self) -> int:
        vtbl = ctypes.cast(self._ptr, ctypes.POINTER(ctypes.c_void_p)).contents
        fn = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[2]
        return ctypes.WINFUNCTYPE(ULONG, ctypes.c_void_p)(fn)(self._ptr)


# --------------------------------------------------------------------------- 回调对象
def _make_handler(iid: GUID, restype, argtypes, callback):
    """构造一个 Python 实现的 COM 回调对象，返回 (对象指针, 保持引用的元组)。"""

    @ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
    def query_interface(this, riid, ppv):
        if riid and (_guid_eq(riid.contents, iid) or _guid_eq(riid.contents, IID_IUNKNOWN)):
            ppv[0] = this
            return S_OK
        ppv[0] = None
        return E_NOINTERFACE

    @ctypes.WINFUNCTYPE(ULONG, ctypes.c_void_p)
    def addref(this):
        return 1

    @ctypes.WINFUNCTYPE(ULONG, ctypes.c_void_p)
    def release(this):
        return 1

    invoke = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(callback)

    vtable = (ctypes.c_void_p * 4)(
        ctypes.cast(query_interface, ctypes.c_void_p),
        ctypes.cast(addref, ctypes.c_void_p),
        ctypes.cast(release, ctypes.c_void_p),
        ctypes.cast(invoke, ctypes.c_void_p),
    )

    class _Obj(ctypes.Structure):
        _fields_ = [("vtbl", ctypes.POINTER(ctypes.c_void_p))]

    obj = _Obj()
    obj.vtbl = ctypes.cast(vtable, ctypes.POINTER(ctypes.c_void_p))
    ptr = ctypes.cast(ctypes.pointer(obj), ctypes.c_void_p)
    return ptr, (query_interface, addref, release, invoke, obj, vtable)


# --------------------------------------------------------------------------- 高层封装
class WebView:
    """嵌入到给定 HWND 的一个 WebView2 控件。"""

    def __init__(self, parent_hwnd: int, *, on_ready=None, on_message=None, on_error=None,
                 user_data_folder: str | None = None) -> None:
        self.parent_hwnd = int(parent_hwnd)
        self.on_ready = on_ready
        self.on_message = on_message
        self.on_error = on_error

        self._env: int | None = None
        self._controller: int | None = None
        self._webview: int | None = None
        self._ready_pending = False
        self._failed = False
        self._error_msg: str | None = None
        self._messages: "queue.Queue[str]" = queue.Queue()
        self._keepalive: list = []
        self._closed = False
        self._last_raise = time.monotonic()

        self._coinit()
        _ensure_loader()
        self._create_environment(user_data_folder)

    # ------------------------------------------------------------------ 初始化
    def _coinit(self) -> None:
        try:
            ole32 = ctypes.WinDLL("ole32")
            ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
            ole32.CoInitializeEx.restype = HRESULT
            hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
            if hr == RPC_E_CHANGED_MODE:
                raise RuntimeError("COM 已被以 MTA 模式初始化，WebView2 需要 STA（单线程套间）")
        except OSError as exc:
            raise RuntimeError(f"初始化 COM 失败：{exc}") from exc

    def _create_environment(self, user_data_folder: str | None) -> None:
        handler, refs = _make_handler(
            IID_EnvironmentCompletedHandler, HRESULT, [HRESULT, ctypes.c_void_p], self._on_environment_created
        )
        self._keepalive.append(refs)
        hr = _CreateCoreWebView2EnvironmentWithOptions(None, user_data_folder, None, handler)
        if hr < 0:
            self._fail(f"创建 WebView2 环境失败 (HRESULT 0x{hr & 0xFFFFFFFF:08X})")

    def _on_environment_created(self, this, error_code: int, env_ptr) -> int:
        if error_code != S_OK:
            self._fail(f"WebView2 环境创建失败 (HRESULT 0x{error_code & 0xFFFFFFFF:08X})，请确认已安装 WebView2 Runtime")
            return S_OK
        self._env = int(env_ptr)
        _ComInterface(self._env).addref()   # 回调给的是借用指针，保存前必须 AddRef
        self._create_controller()
        return S_OK

    def _create_controller(self) -> None:
        env = _ComInterface(self._env)
        handler, refs = _make_handler(
            IID_ControllerCompletedHandler, HRESULT, [HRESULT, ctypes.c_void_p], self._on_controller_created
        )
        self._keepalive.append(refs)
        hr = env._method(0, HRESULT, [wintypes.HWND, ctypes.c_void_p], self.parent_hwnd, handler)
        if hr < 0:
            self._fail(f"创建 WebView2 控制器失败 (HRESULT 0x{hr & 0xFFFFFFFF:08X})")

    def _on_controller_created(self, this, error_code: int, controller_ptr) -> int:
        if error_code != S_OK:
            self._fail(f"WebView2 控制器创建失败 (HRESULT 0x{error_code & 0xFFFFFFFF:08X})")
            return S_OK
        self._controller = int(controller_ptr)
        _ComInterface(self._controller).addref()   # 借用指针 → AddRef 持有

        controller = _ComInterface(self._controller)
        core = ctypes.c_void_p()
        controller._method(22, HRESULT, [ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(core))
        self._webview = core.value   # get_CoreWebView2 返回的 out 指针已由被调用方 AddRef

        self._configure_settings()
        self._register_message_handler()
        self._bring_to_front()
        self._ready_pending = True
        return S_OK

    def _bring_to_front(self) -> None:
        """把 WebView 的 Chrome 子窗口置顶，避免被 Tk 在宿主窗口上的绘图覆盖。"""
        try:
            u = ctypes.windll.user32
            EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def cb(h, _):
                cls = ctypes.create_unicode_buffer(64)
                u.GetClassNameW(h, cls, 64)
                if "Chrome" in cls.value:
                    # HWND_TOP(0) + SWP_NOMOVE|SWP_NOSIZE
                    u.SetWindowPos(h, 0, 0, 0, 0, 0, 0x0003)
                return True

            u.EnumChildWindows(self.parent_hwnd, EnumChildProc(cb), 0)
        except Exception:
            pass

    def _configure_settings(self) -> None:
        webview = _ComInterface(self._webview)
        settings = ctypes.c_void_p()
        webview._method(0, HRESULT, [ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(settings))
        s = _ComInterface(settings.value)
        s._method(1, HRESULT, [BOOL], True)    # IsScriptEnabled
        s._method(3, HRESULT, [BOOL], True)    # IsWebMessageEnabled
        s._method(5, HRESULT, [BOOL], False)   # AreDefaultScriptDialogsEnabled
        s._method(7, HRESULT, [BOOL], False)   # IsStatusBarEnabled
        s._method(9, HRESULT, [BOOL], False)   # AreDevToolsEnabled
        s._method(11, HRESULT, [BOOL], False)  # AreDefaultContextMenusEnabled
        s._method(15, HRESULT, [BOOL], False)  # IsZoomControlEnabled

    def _register_message_handler(self) -> None:
        webview = _ComInterface(self._webview)
        handler, refs = _make_handler(
            IID_WebMessageReceivedEventHandler, HRESULT, [ctypes.c_void_p, ctypes.c_void_p], self._on_web_message
        )
        self._keepalive.append(refs)
        token = EventRegistrationToken()
        webview._method(31, HRESULT, [ctypes.c_void_p, ctypes.POINTER(EventRegistrationToken)],
                        handler, ctypes.byref(token))

    def _on_web_message(self, this, sender, args_ptr) -> int:
        if not self.on_message:
            return S_OK
        try:
            args = _ComInterface(int(args_ptr))
            value = wintypes.LPWSTR()
            args._method(1, HRESULT, [ctypes.POINTER(wintypes.LPWSTR)], ctypes.byref(value))
            if value.value:
                self._messages.put(value.value)
                ole32 = ctypes.WinDLL("ole32")
                ole32.CoTaskMemFree(ctypes.cast(value, ctypes.c_void_p))
        except Exception:
            pass
        return S_OK

    def _fail(self, message: str) -> None:
        self._failed = True
        self._error_msg = message

    # ------------------------------------------------------------------ 主循环派发
    def poll(self) -> None:
        """Tk 主循环定期调用：把就绪/消息/错误派发到主线程。"""
        if self._ready_pending:
            self._ready_pending = False
            if self.on_ready:
                self.on_ready()
        if self._failed and self._error_msg:
            msg, self._error_msg = self._error_msg, None
            if self.on_error:
                self.on_error(msg)
        while not self._messages.empty():
            try:
                msg = self._messages.get_nowait()
            except queue.Empty:
                break
            if self.on_message:
                try:
                    self.on_message(msg)
                except Exception:
                    # 以前这里静默吞掉所有 web 消息回调异常，表现为「点了没反应且无日志」
                    import traceback
                    traceback.print_exc()

    # ------------------------------------------------------------------ 控制
    def set_bounds(self, x: int, y: int, width: int, height: int) -> None:
        if self._controller is None:
            return
        rect = RECT(int(x), int(y), int(x) + int(width), int(y) + int(height))
        _ComInterface(self._controller)._method(3, HRESULT, [RECT], rect)
        # _bring_to_front 会枚举宿主窗口下所有子窗口，很贵；拖拽/缩放窗口时
        # 每帧都调会明显掉帧，这里限流到 ~4 次/秒，足够压住重绘覆盖。
        now = time.monotonic()
        if now - self._last_raise > 0.25:
            self._last_raise = now
            self._bring_to_front()

    def set_visible(self, visible: bool) -> None:
        if self._controller is None:
            return
        _ComInterface(self._controller)._method(1, HRESULT, [BOOL], bool(visible))

    def navigate_html(self, html: str) -> None:
        if self._webview is None:
            return
        _ComInterface(self._webview)._method(3, HRESULT, [wintypes.LPCWSTR], html)

    def post_json(self, json_str: str) -> None:
        if self._webview is None:
            return
        _ComInterface(self._webview)._method(29, HRESULT, [wintypes.LPCWSTR], json_str)

    def set_zoom(self, zoom: float) -> None:
        """网页缩放（如 Ctrl+滚轮），范围约 0.5~5。"""
        if self._controller is None:
            return
        _ComInterface(self._controller)._method(5, HRESULT, [ctypes.c_double], float(zoom))

    def open_devtools(self) -> None:
        if self._webview is None:
            return
        _ComInterface(self._webview)._method(48, HRESULT, [])

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._controller is not None:
            try:
                ctrl = _ComInterface(self._controller)
                ctrl._method(21, HRESULT, [])
                ctrl.release()   # 释放我们 AddRef 的引用
            except Exception:
                pass
        if self._webview is not None:
            try:
                _ComInterface(self._webview).release()
            except Exception:
                pass
        if self._env is not None:
            try:
                _ComInterface(self._env).release()
            except Exception:
                pass
        self._controller = None
        self._webview = None
        self._env = None

    @property
    def is_ready(self) -> bool:
        return self._webview is not None and not self._failed
