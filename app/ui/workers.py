"""Ejecuta tareas largas (rastreo, IA) fuera del hilo de la interfaz."""
from __future__ import annotations

import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Signal


class WorkerSignals(QObject):
    progress = Signal(str)
    finished = Signal(object)
    error = Signal(str)


class Worker(QRunnable):
    """Ejecuta fn(progress=..., cancelled=...) si acepta esos argumentos, o fn() si no."""

    def __init__(self, fn: Callable, with_progress: bool = False):
        super().__init__()
        self.fn = fn
        self.with_progress = with_progress
        self.signals = WorkerSignals()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            if self.with_progress:
                result = self.fn(progress=self.signals.progress.emit, cancelled=lambda: self._cancel)
            else:
                result = self.fn()
        except Exception as e:
            traceback.print_exc()
            self.signals.error.emit(str(e))
        else:
            self.signals.finished.emit(result)
