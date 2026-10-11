"""Open and decode candidates off the Qt thread before replacing a composition."""

import threading
from concurrent.futures import CancelledError, ThreadPoolExecutor

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QProgressDialog

from .media import MediaClip


def open_media(source, cache_root, parent, *, factory=MediaClip):
    cancelled = threading.Event()
    progress = ["Reading media", 0, 0]
    dialog = QProgressDialog("Reading media…", "Cancel", 0, 0, parent)
    dialog.setWindowTitle("Opening " + source.name)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(150)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.canceled.connect(cancelled.set)

    def report(message, current, total):
        progress[:] = [message, current, total]

    def decode():
        media = None
        try:
            media = factory(source, cache_root, cancelled=cancelled, progress=report)
            frame = media.frame_at(0.0)
            if cancelled.is_set():
                raise CancelledError()
            return media, frame
        except BaseException:
            if media is not None:
                media.close()
            raise

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scenelight-media-open")
    future = executor.submit(decode)
    timer = QTimer(dialog)

    def tick():
        if future.done():
            dialog.accept()
            return
        message, current, total = progress[:]
        dialog.setLabelText(message + (f" · {current} / {total}" if total else "…"))
        dialog.setRange(0, total)
        dialog.setValue(current)

    timer.timeout.connect(tick)
    timer.start(30)
    try:
        dialog.exec()
        if not future.done() or cancelled.is_set():
            cancelled.set()

            def discard(completed):
                if not completed.cancelled() and completed.exception() is None:
                    completed.result()[0].close()

            future.add_done_callback(discard)
            return None
        return future.result()
    except CancelledError:
        return None
    finally:
        timer.stop()
        executor.shutdown(wait=False, cancel_futures=True)
        dialog.deleteLater()
