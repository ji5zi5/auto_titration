"""Laptop-side mobile ingest bridge for Android sensor companion mode."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
import time
from typing import Any, Mapping, Protocol

from .mobile_protocol import MobileProtocolError, mobile_payload_to_csv_row


class CsvBufferLike(Protocol):
    def add(self, row: dict[str, Any], *, now_monotonic_s: float | None = None) -> bool: ...

    def status(self, *, now_monotonic_s: float | None = None) -> dict[str, Any]: ...


class MobileBridgeError(ValueError):
    """Raised when mobile pairing or ingest cannot be accepted."""


@dataclass(frozen=True)
class MobilePairing:
    token: str
    created_epoch_s: float
    expires_epoch_s: float


class MobileBridge:
    """Owns mobile-mode feature ingestion and writes rows to a CSV buffer.

    The dashboard may proxy these APIs, but the bridge is the state owner for
    mobile feature rows.  This avoids making the static dashboard server mutate
    CSV state directly.
    """

    def __init__(
        self,
        *,
        csv_buffer: CsvBufferLike,
        token_ttl_s: float = 300.0,
        stale_after_s: float = 2.5,
        token_factory: Any | None = None,
    ) -> None:
        self.csv_buffer = csv_buffer
        self.token_ttl_s = max(1.0, float(token_ttl_s))
        self.stale_after_s = max(0.1, float(stale_after_s))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(12))
        self._pairing: MobilePairing | None = None
        self._last_received_epoch_s: float | None = None
        self._last_status: dict[str, Any] = {}
        self._accepted_frames = 0
        self._rejected_frames = 0

    def create_pairing(self, *, now_epoch_s: float | None = None) -> dict[str, Any]:
        now = _now_epoch(now_epoch_s)
        pairing = MobilePairing(
            token=str(self._token_factory()),
            created_epoch_s=round(now, 6),
            expires_epoch_s=round(now + self.token_ttl_s, 6),
        )
        self._pairing = pairing
        return {
            "token": pairing.token,
            "created_epoch_s": pairing.created_epoch_s,
            "expires_epoch_s": pairing.expires_epoch_s,
            "ttl_s": self.token_ttl_s,
        }

    def ingest(
        self,
        frame_payload: Mapping[str, Any],
        *,
        token: str,
        server_received_epoch_s: float | None = None,
        now_monotonic_s: float | None = None,
    ) -> dict[str, Any]:
        received_epoch = _now_epoch(server_received_epoch_s)
        self._require_token(token, now_epoch_s=received_epoch)
        try:
            row = mobile_payload_to_csv_row(frame_payload, server_received_epoch_s=received_epoch)
        except MobileProtocolError:
            self._rejected_frames += 1
            raise
        recorded = self.csv_buffer.add(row, now_monotonic_s=now_monotonic_s)
        if recorded:
            self._accepted_frames += 1
        self._last_received_epoch_s = received_epoch
        self._last_status = {
            "source": "android_mobile",
            "state": "streaming",
            "last_frame_id": row.get("frame_id"),
            "device_id": row.get("mobile_device_id"),
            "run_id": row.get("mobile_run_id"),
            "last_received_epoch_s": round(received_epoch, 6),
            "thermal_calibrated": row.get("thermal_calibrated"),
            "sync_quality": row.get("sync_quality"),
        }
        return {
            "ok": bool(recorded),
            "row_recorded": bool(recorded),
            "mobile": self.status(now_epoch_s=received_epoch)["mobile"],
            "csv": self.csv_buffer.status(now_monotonic_s=now_monotonic_s),
        }

    def status(self, *, now_epoch_s: float | None = None) -> dict[str, Any]:
        now = _now_epoch(now_epoch_s)
        paired = self._pairing is not None and now <= self._pairing.expires_epoch_s
        mobile: dict[str, Any] = {
            "enabled": True,
            "source": "android_mobile",
            "paired": paired,
            "state": "paired" if paired else "waiting_for_pairing",
            "accepted_frames": self._accepted_frames,
            "rejected_frames": self._rejected_frames,
        }
        if self._pairing is not None:
            mobile.update(
                {
                    "pairing_expires_epoch_s": self._pairing.expires_epoch_s,
                    "pairing_ttl_s": self.token_ttl_s,
                }
            )
        if self._last_status:
            mobile.update(self._last_status)
            age_s = max(0.0, now - float(self._last_received_epoch_s or now))
            mobile["last_frame_age_ms"] = round(age_s * 1000.0, 3)
            mobile["state"] = "stale" if age_s > self.stale_after_s else "streaming"
        return {"ok": True, "mobile": mobile, "csv": self.csv_buffer.status()}

    def _require_token(self, token: str, *, now_epoch_s: float) -> None:
        if self._pairing is None or str(token or "") != self._pairing.token:
            raise MobileBridgeError("invalid pairing token")
        if now_epoch_s > self._pairing.expires_epoch_s:
            raise MobileBridgeError("expired pairing token")


def _now_epoch(value: float | None) -> float:
    return float(time.time() if value is None else value)
