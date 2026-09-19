"""Managed lifecycle; no HWND style mutations from server threads."""
import threading
from engine.diagnostics import journal

controller = None


class WindowController:
    def __init__(self, window, shutdown, icon):
        self.window, self.shutdown, self.icon = window, shutdown, icon
        self.silent = False
        self.ready = threading.Event()
        self._closing = False
        self._allow_close = False
        self._show_requested = False
        self.close_to_tray = lambda: False
        from engine.window_preferences import load_maximized
        self._maximized = load_maximized()

    def dispatch(self, callback):
        native = self.window.native
        if native is None or native.IsDisposed:
            raise RuntimeError("Окно ещё не готово")
        from System import Action
        if native.InvokeRequired:
            native.BeginInvoke(Action(callback))
        else:
            callback()

    def before_show(self):
        from System.Drawing import Icon
        native = self.window.native
        native.Icon = Icon(self.icon)
        import os
        import clr
        clr.AddReference(os.path.join(os.path.dirname(__file__), "native", "SadnessChrome.dll"))
        from SadnessVPN import WindowChrome
        self.chrome = WindowChrome(native)
        native.Resize += self.native_resized
        native.Shown += self.native_resized
        native.webview.CoreWebView2InitializationCompleted += self.webview_initialized

    def webview_initialized(self, sender, args):
        if not args.IsSuccess:
            journal.error("WebView2: %s", args.InitializationException)
            return
        sender.CoreWebView2.ProcessFailed += self.process_failed
        sender.CoreWebView2.Settings.IsNonClientRegionSupportEnabled = True
        journal.info("WebView2 инициализирован")

    def process_failed(self, sender, args):
        journal.error("WebView2 ProcessFailed: %s", args.ProcessFailedKind)
        self.show_error("Графический процесс завершился. Закройте и снова откройте Sadness VPN. Диагностика сохранена.")

    def show_error(self, text):
        def display():
            from System.Windows.Forms import MessageBox
            self.window.native.Show()
            MessageBox.Show(self.window.native, text, "Sadness VPN")
        self.dispatch(display)

    def loaded(self):
        self.ready.set()
        self.window.run_js("document.documentElement.classList.add('custom-frame')")
        journal.info("Интерфейс готов")
        def restore_layout():
            from System.Windows.Forms import FormWindowState
            if self._maximized:self.window.native.WindowState=FormWindowState.Maximized
            self.sync_surface()
        self.dispatch(restore_layout if self._maximized else self.sync_surface)
        if self.silent and not self._show_requested:
            self.dispatch(lambda: self.window.native.Hide())

    def native_resized(self, sender, args):
        if not self.ready.is_set():
            return
        from System.Windows.Forms import FormWindowState
        self.sync_surface()
        maximized = self.window.native.WindowState == FormWindowState.Maximized
        if not self._closing and self.window.native.WindowState != FormWindowState.Minimized:
            self._maximized = maximized
        self.window.native.webview.CoreWebView2.ExecuteScriptAsync(
            "window.setWindowMaximized && setWindowMaximized(" + str(maximized).lower() + ")"
        )

    def sync_surface(self):
        """Restore the child surface after native non-client recalculation.

        Runs only on the WinForms thread; do not recreate the renderer or
        clear its profile during resize/reopen.
        """
        from System.Windows.Forms import DockStyle, FormWindowState
        from System.Drawing import Rectangle
        native = self.window.native
        if native.IsDisposed or native.WindowState == FormWindowState.Minimized:
            return
        surface = native.webview
        surface.Dock = DockStyle.Fill
        pad = native.Padding
        width = max(1, native.ClientSize.Width - pad.Horizontal)
        height = max(1, native.ClientSize.Height - pad.Vertical)
        bounds = Rectangle(pad.Left, pad.Top, width, height)
        if surface.Bounds != bounds:
            surface.Bounds = bounds
        surface.Visible = True
        surface.BringToFront()
        native.PerformLayout()
        surface.Invalidate()

    def watch_startup(self):
        for _ in range(100):
            if self.ready.wait(.25) or self._closing:
                return
        journal.error("Интерфейс не готов за 25 секунд")
        self.show_error("Интерфейс не загрузился за 25 секунд. Попробуйте перезапустить приложение. Журнал сохранён в diagnostics в папке данных.")

    def show(self):
        if self._closing:
            return
        self._show_requested = True
        if not self.window.events.shown.wait(15):
            journal.warning("Окно пока не готово к активации")
            return
        def restore():
            from System.Windows.Forms import FormWindowState
            native = self.window.native
            native.Show()
            if native.WindowState == FormWindowState.Minimized:
                native.WindowState = FormWindowState.Normal
            native.Activate()
            self.sync_surface()
        self.dispatch(restore)

    def minimize(self):
        def minimize():
            from System.Windows.Forms import FormWindowState
            self.window.native.WindowState = FormWindowState.Minimized
        self.dispatch(minimize)

    def toggle_maximize(self):
        def toggle():
            from System.Windows.Forms import FormWindowState
            native = self.window.native
            native.WindowState = FormWindowState.Normal if native.WindowState == FormWindowState.Maximized else FormWindowState.Maximized
        self.dispatch(toggle)

    def on_closing(self):
        if self._allow_close:
            return True
        self.request_close()
        return False

    def request_close(self):
        if self.close_to_tray():
            self.dispatch(lambda: self.window.native.Hide())
        else:
            self.close()

    def close(self):
        if self._closing:
            return
        self._closing = True
        try:
            from engine.window_preferences import save_maximized
            save_maximized(self._maximized)
        except OSError:
            journal.warning('Не удалось сохранить состояние окна')
        def finish():
            try:
                self.shutdown()
            except Exception:
                journal.exception("Закрытие отменено: туннель не остановлен")
                self._closing = False
                self.show_error("Не удалось остановить туннель. Повторите отключение, затем закройте приложение.")
            else:
                self._allow_close = True
                def close_native():
                    from System.Windows.Forms import FormWindowState
                    native = self.window.native
                    # Release the maximized child surface before destruction;
                    # otherwise GPU overlays can retain a blank full-size host.
                    if native.WindowState == FormWindowState.Maximized:
                        native.WindowState = FormWindowState.Normal
                    native.Close()
                self.dispatch(close_native)
        threading.Thread(target=finish, daemon=True).start()
