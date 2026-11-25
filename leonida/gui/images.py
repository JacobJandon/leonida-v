"""Preview pictures for the mod chooser: fetched from the author's page at runtime and cached in the state folder."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QThreadPool, Signal, Slot

STOP_TIMEOUT_MS = 5000  # app exit: how long to wait for picture downloads already running

INDEX = "index.json"  # page URL -> image URL found on it, so pages aren't re-read every start


def network_allowed() -> bool:
    return not os.environ.get("LEONIDA_NO_NET")


class _Job(QRunnable):
    def __init__(self, loader: ImageLoader, key: str, image_url: str | None, page_url: str | None):
        super().__init__()
        self.loader, self.key, self.image_url, self.page_url = loader, key, image_url, page_url

    def run(self) -> None:
        url, path = self.image_url, None
        try:
            from .. import downloader as D

            if not url and self.page_url:
                url = D.page_image(self.page_url)
            if url:
                path = D.fetch_image(url, self.loader.cache_dir)
        except Exception:  # noqa: BLE001 - a missing picture is never fatal
            path = None
        self.loader._job_done.emit(self.key, self.page_url or "", url or "", str(path) if path else "")


class ImageLoader(QObject):
    """``request(key, image_url, page_url)``; ``loaded(key, path)`` fires on the UI thread ('' = no picture)."""

    loaded = Signal(str, str)
    _job_done = Signal(str, str, str, str)

    def __init__(self, cache_dir: Path, parent: QObject | None = None):
        super().__init__(parent)
        self.cache_dir = Path(cache_dir)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self.paths: dict[str, str] = {}
        self.pending: set[str] = set()
        self.index = self._load_index()
        self._job_done.connect(self._finish)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @Slot()
    def shutdown(self, timeout_ms: int = STOP_TIMEOUT_MS) -> bool:
        """Drop queued picture jobs and wait for running ones (app exit), so no job outlives this loader.
        True if the pool is idle."""
        self.pool.clear()
        return self.pool.waitForDone(timeout_ms)

    def _load_index(self) -> dict[str, str]:
        try:
            return json.loads((self.cache_dir / INDEX).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def cached(self, image_url: str | None, page_url: str | None) -> str | None:
        """The picture already in the cache folder (no network): by its URL, or by the URL found on the page before."""
        import hashlib

        url = image_url or (self.index.get(page_url) if page_url else None)
        if not url or not self.cache_dir.is_dir():
            return None
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        for hit in self.cache_dir.glob(key + ".*"):
            if hit.is_file() and hit.suffix != ".tmp" and hit.stat().st_size > 0:
                return str(hit)
        return None

    def request(self, key: str, image_url: str | None, page_url: str | None) -> None:
        if key not in self.paths:
            hit = self.cached(image_url, page_url)  # on disk already: shown at once, even offline
            if hit:
                self.paths[key] = hit
        if key in self.paths:
            self.loaded.emit(key, self.paths[key])
            return
        if key in self.pending or not network_allowed():
            return
        if not image_url and page_url:
            image_url = self.index.get(page_url) or None
        self.pending.add(key)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.pool.start(_Job(self, key, image_url, page_url))

    @Slot(str, str, str, str)
    def _finish(self, key: str, page_url: str, image_url: str, path: str) -> None:
        self.pending.discard(key)
        if page_url and image_url and self.index.get(page_url) != image_url:  # failures aren't cached: retry next start
            self.index[page_url] = image_url
            with contextlib.suppress(OSError):
                (self.cache_dir / INDEX).write_text(json.dumps(self.index, indent=1), encoding="utf-8")
        if path:
            self.paths[key] = path
        self.loaded.emit(key, path)
