"""Application entry point: argument handling, single-instance nxm://
forwarding, and Qt event loop startup."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .gui import theme
from .gui.ipc import NxmIpcServer, send_to_running_instance
from .gui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    if argv and argv[0] == "handle-nxm" and len(argv) > 1:
        url = argv[1]
        app = QApplication(sys.argv[:1])  # QLocalSocket needs a running event loop
        if send_to_running_instance(url):
            return 0
        return _run_gui(app, initial_url=url)

    app = QApplication(sys.argv)
    return _run_gui(app)


def _run_gui(app: QApplication, initial_url: str | None = None) -> int:
    theme.apply_theme(app)
    window = MainWindow()

    ipc_server = NxmIpcServer(window)
    ipc_server.url_received.connect(window.handle_nxm_url)
    ipc_server.start()

    window.show()
    if initial_url:
        window.handle_nxm_url(initial_url)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
