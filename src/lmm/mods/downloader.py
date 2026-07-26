"""Threaded file downloader. Framework-agnostic (no Qt here) so it can be
unit tested and reused by both the GUI and any future CLI/headless mode.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ProgressCallback = Callable[[int, int], None]  # (downloaded_bytes, total_bytes)
CHUNK_SIZE = 256 * 1024


class DownloadCanceled(Exception):
    pass


def download_file(
    url: str,
    dest_path: str | Path,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    session: requests.Session | None = None,
    headers: dict[str, str] | None = None,
) -> Path:
    """Streams ``url`` to ``dest_path`` (via a .part temp file, renamed on
    success). Raises DownloadCanceled if ``cancel_event`` is set mid-flight.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

    sess = session or requests.Session()
    with sess.get(url, stream=True, timeout=60, headers=headers) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with tmp_path.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if cancel_event is not None and cancel_event.is_set():
                    fh.close()
                    tmp_path.unlink(missing_ok=True)
                    raise DownloadCanceled(url)
                if not chunk:
                    continue
                fh.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)

    tmp_path.replace(dest_path)
    return dest_path


class DownloadManager:
    """A small bounded worker pool for concurrent downloads."""

    def __init__(self, max_workers: int = 3):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="lmm-dl")
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        task_id: str,
        url: str,
        dest_path: str | Path,
        on_progress: ProgressCallback | None = None,
        on_done: Callable[[Path], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[task_id] = cancel_event

        def _run() -> None:
            try:
                result = download_file(
                    url, dest_path, on_progress=on_progress, cancel_event=cancel_event, headers=headers
                )
                if on_done:
                    on_done(result)
            except Exception as exc:  # surfaced to caller via on_error, not swallowed
                if on_error:
                    on_error(exc)
            finally:
                with self._lock:
                    self._cancel_events.pop(task_id, None)

        self._executor.submit(_run)

    def cancel(self, task_id: str) -> None:
        with self._lock:
            event = self._cancel_events.get(task_id)
        if event:
            event.set()

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)
