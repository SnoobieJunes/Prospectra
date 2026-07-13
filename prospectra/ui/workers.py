# 2026-07-13 (P1): Worker plumbing — run any callable on the global QThreadPool and deliver the
# result/error back on the *caller's* (GUI) thread.
# Why the relay object: Qt connections to bare Python callables have no receiver QObject, so they
# execute in the emitting (pool) thread — touching widgets/models there crashes (observed as a
# bus error in the grid tests). The relay is a QObject created in the caller's thread; the worker
# emits to it cross-thread (queued), its bound-method slots run on the caller's thread, and only
# then are the user callbacks invoked. Relays are kept alive in a registry until delivery is done.

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

logger = logging.getLogger(__name__)

_ACTIVE_RELAYS: set[_Relay] = set()


class _Relay(QObject):
    result_sig = Signal(object)
    error_sig = Signal(str)
    finished_sig = Signal()

    def __init__(
        self,
        on_result: Callable[[Any], None] | None,
        on_error: Callable[[str], None] | None,
        on_finished: Callable[[], None] | None,
    ) -> None:
        super().__init__()
        self._on_result = on_result
        self._on_error = on_error
        self._on_finished = on_finished
        # Bound-method slots give Qt a receiver object -> queued delivery on this thread.
        self.result_sig.connect(self._deliver_result)
        self.error_sig.connect(self._deliver_error)
        self.finished_sig.connect(self._deliver_finished)

    def _deliver_result(self, value: object) -> None:
        if self._on_result is not None:
            self._on_result(value)

    def _deliver_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)

    def _deliver_finished(self) -> None:
        if self._on_finished is not None:
            self._on_finished()
        # Drop the registry reference on the *next* event-loop pass, never inside our own slot.
        QTimer.singleShot(0, lambda relay=self: _ACTIVE_RELAYS.discard(relay))


class FunctionWorker(QRunnable):
    def __init__(
        self,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        relay: _Relay,
    ) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._relay = relay

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:
            logger.error("Worker failed: %s\n%s", exc, traceback.format_exc())
            self._relay.error_sig.emit(str(exc))
        else:
            self._relay.result_sig.emit(result)
        finally:
            self._relay.finished_sig.emit()


def run_in_pool(
    fn: Callable[..., Any],
    *args: Any,
    on_result: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    on_finished: Callable[[], None] | None = None,
    **kwargs: Any,
) -> None:
    """Run fn(*args, **kwargs) on the thread pool; callbacks fire on the calling thread."""
    relay = _Relay(on_result, on_error, on_finished)
    _ACTIVE_RELAYS.add(relay)
    QThreadPool.globalInstance().start(FunctionWorker(fn, args, kwargs, relay))
