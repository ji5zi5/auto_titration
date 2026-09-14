"""Serialize requested camera power changes at a collector frame boundary."""
import threading
from typing import Callable


class CameraPowerControl:
    def __init__(self, *, start: Callable[[], None], stop: Callable[[], None]) -> None:
        self._start = start
        self._stop = stop
        self._lock = threading.Lock()
        self._enabled = True
        self._target = True
        self._phase = "on"
        self._applying = False
        self._error = ""

    def status(self) -> dict:
        with self._lock:
            return {"supported": True, "enabled": self._enabled,
                    "requested_enabled": self._target, "state": self._phase,
                    "error": self._error}

    def can_record(self) -> bool:
        with self._lock:
            return self._phase == "on"

    def request(self, enabled: bool, *, recording: bool) -> dict:
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        with self._lock:
            if recording:
                raise ValueError("stop recording/finalization before changing camera power")
            if self._phase in {"starting", "stopping"}:
                if enabled != self._target:
                    raise ValueError("camera power change is still in progress")
            elif self._phase == "error" and self._enabled and enabled:
                raise ValueError("finish stopping cameras before reopening them")
            elif enabled != self._enabled or self._phase == "error":
                self._target = enabled
                self._phase = "starting" if enabled else "stopping"
                self._error = ""
        return self.status()

    def reconcile(self) -> bool:
        """Called by the acquisition loop, never the HTTP request thread."""
        with self._lock:
            if self._phase not in {"starting", "stopping"} or self._applying:
                return False
            target = self._target
            self._applying = True
        try:
            (self._start if target else self._stop)()
        except Exception as exc:
            cleanup_error = ""
            if target:
                try:
                    self._stop()
                except Exception as cleanup_exc:
                    cleanup_error = str(cleanup_exc)
            with self._lock:
                self._phase = "error"
                self._error = str(exc) + (f"; cleanup failed: {cleanup_error}" if cleanup_error else "")
                if cleanup_error:
                    self._enabled = True  # resources may still be open; require OFF retry
        else:
            with self._lock:
                self._enabled = target
                self._phase = "on" if target else "off"
        finally:
            with self._lock:
                self._applying = False
        return True
