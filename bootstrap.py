"""Frozen entry point: start diagnostics before application imports."""
from engine.startup_diagnostics import initialize, report_failure


def run():
    initialize()
    try:
        # С 2.0.26 окно рисует Electron, а этот процесс — только сервер API
        # движков. Собственного окна на WebView2 больше нет.
        import backend_main
        backend_main.main()
        return 0
    except Exception as exc:
        report_failure(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
