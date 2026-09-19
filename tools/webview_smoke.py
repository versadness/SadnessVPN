"""Local diagnostic for the Windows pywebview activation race."""

import threading
import time

import webview
import clr
from System import Func, Object


def activate(window):
    print(f"shown={window.events.shown.wait(10)}", flush=True)
    native = window.native
    task = native.webview.Invoke(
        Func[Object](lambda: native.webview.EnsureCoreWebView2Async(None))
    )
    for attempt in range(1, 5):
        core = native.webview.CoreWebView2 if native is not None else None
        print(
            f"attempt={attempt} native={native is not None} core={core is not None} "
            f"task_status={task.Status} task_error={task.Exception}",
            flush=True,
        )
        if native is not None:
            native.show()
        time.sleep(2)


window = webview.create_window(
    "WebView Test",
    html="<html><body style='background:#72152c;color:white;font-size:50px'>WORKS</body></html>",
    width=600,
    height=400,
)
webview.start(
    activate,
    window,
    debug=True,
    private_mode=False,
    storage_path="build/webview-smoke-profile",
)
