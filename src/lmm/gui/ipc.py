"""Single-instance IPC: `lmm handle-nxm <url>` forwards the link to an
already-running LMM window instead of opening a second one, which is what
the OS does every time a browser "Download with Manager" button fires.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

SOCKET_NAME = "lmm-nxm-ipc"


class NxmIpcServer(QObject):
    url_received = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)

    def start(self) -> None:
        QLocalServer.removeServer(SOCKET_NAME)  # clear a stale socket from a crashed run
        self._server.listen(SOCKET_NAME)

    def _on_new_connection(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.readyRead.connect(lambda: self._read(socket))

    def _read(self, socket: QLocalSocket) -> None:
        data = bytes(socket.readAll()).decode("utf-8", errors="replace").strip()
        if data:
            self.url_received.emit(data)
        socket.disconnectFromServer()


def send_to_running_instance(url: str, timeout_ms: int = 500) -> bool:
    """Returns True if a running LMM instance accepted the link."""
    socket = QLocalSocket()
    socket.connectToServer(SOCKET_NAME)
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(url.encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    return True
