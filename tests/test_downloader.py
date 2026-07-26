import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lmm.mods.downloader import DownloadCanceled, download_file


class _Handler(BaseHTTPRequestHandler):
    payload = b"x" * (512 * 1024)

    def do_GET(self):  # noqa: N802 - stdlib API name
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        for i in range(0, len(self.payload), 4096):
            self.wfile.write(self.payload[i : i + 4096])

    def log_message(self, *args):
        pass  # keep test output quiet


@pytest.fixture
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join()


def test_download_file_writes_full_content(tmp_path, http_server):
    port = http_server.server_address[1]
    dest = tmp_path / "out.bin"

    progress_calls = []
    result = download_file(
        f"http://127.0.0.1:{port}/file",
        dest,
        on_progress=lambda d, t: progress_calls.append((d, t)),
    )

    assert result == dest
    assert dest.read_bytes() == _Handler.payload
    assert not dest.with_suffix(".bin.part").exists()
    assert progress_calls[-1][0] == len(_Handler.payload)


def test_download_file_respects_cancel_event(tmp_path, http_server):
    port = http_server.server_address[1]
    dest = tmp_path / "out.bin"
    cancel_event = threading.Event()

    def _cancel_after_first_chunk(downloaded, total):
        cancel_event.set()

    with pytest.raises(DownloadCanceled):
        download_file(
            f"http://127.0.0.1:{port}/file",
            dest,
            on_progress=_cancel_after_first_chunk,
            cancel_event=cancel_event,
        )

    assert not dest.exists()
    assert not (tmp_path / "out.bin.part").exists()
