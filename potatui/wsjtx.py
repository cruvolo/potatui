# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 MonkeybutlerCJH (https://github.com/MonkeybutlerCJH)

"""WSJT-X UDP listener for automatic QSO ingestion."""

from __future__ import annotations

import socket
import struct
import threading
import time
from datetime import UTC, datetime

_LOG_MAX = 100
_MAGIC = 0xADBCCBDA
_SCHEMA = 2  # WSJT-X schema version we support

# Message type IDs
_TYPE_HEARTBEAT = 0
_TYPE_STATUS = 1
_TYPE_DECODE = 2
_TYPE_CLEAR = 3
_TYPE_REPLY = 4
_TYPE_QSO_LOGGED = 5
_TYPE_CLOSE = 6


# ---------------------------------------------------------------------------
# Binary parsing helpers
# ---------------------------------------------------------------------------

def _read_u8(data: bytes, pos: int) -> tuple[int, int]:
    return data[pos], pos + 1


def _read_u32(data: bytes, pos: int) -> tuple[int, int]:
    val = struct.unpack_from(">I", data, pos)[0]
    return val, pos + 4


def _read_i32(data: bytes, pos: int) -> tuple[int, int]:
    val = struct.unpack_from(">i", data, pos)[0]
    return val, pos + 4


def _read_u64(data: bytes, pos: int) -> tuple[int, int]:
    val = struct.unpack_from(">Q", data, pos)[0]
    return val, pos + 8


def _read_bool(data: bytes, pos: int) -> tuple[bool, int]:
    return bool(data[pos]), pos + 1


def _read_double(data: bytes, pos: int) -> tuple[float, int]:
    val = struct.unpack_from(">d", data, pos)[0]
    return val, pos + 8


def _read_utf8(data: bytes, pos: int) -> tuple[str, int]:
    """Read a Qt QString (big-endian u32 length then UTF-8 bytes; 0xFFFFFFFF = null)."""
    length, pos = _read_u32(data, pos)
    if length == 0xFFFFFFFF:
        return "", pos
    text = data[pos: pos + length].decode("utf-8", errors="replace")
    return text, pos + length


def _read_qdatetime(data: bytes, pos: int) -> tuple[datetime | None, int]:
    """Read a QDateTime: Julian day (u64), ms since midnight (u32), timespec (u8)."""
    jd, pos = _read_u64(data, pos)
    ms_since_midnight, pos = _read_u32(data, pos)
    timespec, pos = _read_u8(data, pos)
    if timespec == 2:  # UTC offset — skip 4 bytes
        _, pos = _read_i32(data, pos)
    if jd == 0:
        return None, pos
    # Convert Julian day to unix epoch
    unix_day = jd - 2440588  # Julian day for 1970-01-01
    unix_ts = unix_day * 86400 + ms_since_midnight // 1000
    try:
        dt = datetime.fromtimestamp(unix_ts, tz=UTC).replace(tzinfo=None)
    except (OSError, OverflowError, ValueError):
        dt = None
    return dt, pos


# ---------------------------------------------------------------------------
# WsjtxClient
# ---------------------------------------------------------------------------

class WsjtxClient:
    """Thread-based UDP listener that receives WSJT-X broadcast datagrams."""

    def __init__(self, host: str = "127.0.0.1", port: int = 2237) -> None:
        self._host = host
        self._port = port
        self._lock = threading.Lock()
        self._qso_queue: list[dict] = []
        self._last_rx: float = 0.0  # monotonic time of last received message
        self.log: list[str] = []  # timestamped diagnostic log
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._sock: socket.socket | None = None

    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------

    def _append_log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        entry = f"{ts}  {msg}"
        with self._lock:
            self.log.append(entry)
            if len(self.log) > _LOG_MAX:
                self.log = self.log[-_LOG_MAX:]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Bind the UDP socket and start the listener thread."""
        self._stop_event.clear()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # SO_REUSEPORT is not available on all platforms
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except (OSError, AttributeError):
                    pass
            sock.settimeout(2.0)
            sock.bind((self._host, self._port))
            self._sock = sock
            self._append_log(f"Listening on {self._host}:{self._port}")
        except OSError as exc:
            self._append_log(f"Bind failed: {exc}")
            self._sock = None

        self._thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="wsjtx-listener"
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the listener thread to stop and close the socket."""
        self._stop_event.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def is_online(self) -> bool:
        """True if any WSJT-X message was received within the last 20 seconds."""
        with self._lock:
            return (self._last_rx > 0) and (time.monotonic() - self._last_rx < 20.0)

    def drain_qsos(self) -> list[dict]:
        """Return and clear all pending QSO Logged messages (thread-safe)."""
        with self._lock:
            qsos, self._qso_queue = self._qso_queue, []
        return qsos

    # ------------------------------------------------------------------
    # Listener thread
    # ------------------------------------------------------------------

    def _listen_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._sock is None:
                time.sleep(1.0)
                continue
            try:
                data, _addr = self._sock.recvfrom(4096)
                with self._lock:
                    self._last_rx = time.monotonic()
                self._parse_message(data)
            except TimeoutError:
                pass  # normal 2-second poll interval
            except OSError:
                if not self._stop_event.is_set():
                    self._append_log("Socket error in listener loop")
                break

    # ------------------------------------------------------------------
    # Message parsing
    # ------------------------------------------------------------------

    def _parse_message(self, data: bytes) -> None:
        if len(data) < 8:
            return
        magic, pos = _read_u32(data, 0)
        if magic != _MAGIC:
            return
        _schema, pos = _read_u32(data, pos)
        msg_type, pos = _read_u32(data, pos)
        _id, pos = _read_utf8(data, pos)

        if msg_type == _TYPE_HEARTBEAT:
            self._parse_heartbeat(data, pos)
        elif msg_type == _TYPE_STATUS:
            self._parse_status(data, pos)
        elif msg_type == _TYPE_QSO_LOGGED:
            self._parse_qso_logged(data, pos)

    def _parse_heartbeat(self, data: bytes, pos: int) -> None:
        try:
            _max_schema, pos = _read_u32(data, pos)
            version, pos = _read_utf8(data, pos)
            self._append_log(f"Heartbeat from WSJT-X {version}")
        except Exception as exc:
            self._append_log(f"Heartbeat parse error: {exc}")

    def _parse_status(self, data: bytes, pos: int) -> None:
        try:
            dial_freq_hz, pos = _read_u64(data, pos)
            mode, pos = _read_utf8(data, pos)
            dx_call, pos = _read_utf8(data, pos)
            self._append_log(
                f"Status: {dial_freq_hz / 1000:.1f} kHz  {mode}"
                + (f"  DX={dx_call}" if dx_call else "")
            )
        except Exception as exc:
            self._append_log(f"Status parse error: {exc}")

    def _parse_qso_logged(self, data: bytes, pos: int) -> None:
        try:
            datetime_off, pos = _read_qdatetime(data, pos)
            dx_call, pos = _read_utf8(data, pos)
            dx_grid, pos = _read_utf8(data, pos)
            tx_freq_hz, pos = _read_u64(data, pos)
            mode, pos = _read_utf8(data, pos)
            rst_sent, pos = _read_utf8(data, pos)
            rst_rcvd, pos = _read_utf8(data, pos)
            tx_power, pos = _read_utf8(data, pos)
            comments, pos = _read_utf8(data, pos)
            name, pos = _read_utf8(data, pos)

            qso: dict = {
                "datetime_off": datetime_off,
                "dx_call": dx_call.strip().upper(),
                "dx_grid": dx_grid.strip().upper(),
                "tx_freq_hz": tx_freq_hz,
                "mode": mode.strip().upper(),
                "rst_sent": rst_sent.strip() or "-10",
                "rst_rcvd": rst_rcvd.strip() or "-10",
                "name": name.strip(),
                "comments": comments.strip(),
            }
            self._append_log(
                f"QSO Logged: {qso['dx_call']}  {tx_freq_hz / 1000:.1f} kHz  {mode}"
            )
            with self._lock:
                self._qso_queue.append(qso)
        except Exception as exc:
            self._append_log(f"QSO Logged parse error: {exc}")
