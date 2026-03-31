# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 MonkeybutlerCJH (https://github.com/MonkeybutlerCJH)

"""Send fake WSJT-X UDP datagrams to test the potatui listener.

Usage:
    python tools/fake_wsjtx.py [--host 127.0.0.1] [--port 2237] [--qso] [--heartbeat]

Examples:
    # Send a heartbeat (marks WSJT-X as online in the net status modal)
    python tools/fake_wsjtx.py --heartbeat

    # Send a fake QSO logged message
    python tools/fake_wsjtx.py --qso

    # Send both (heartbeat first, then QSO)
    python tools/fake_wsjtx.py --heartbeat --qso

    # Repeat heartbeats every 15s to keep it "online"
    python tools/fake_wsjtx.py --heartbeat --loop
"""

from __future__ import annotations

import argparse
import socket
import struct
import time
from datetime import UTC, datetime

_MAGIC = 0xADBCCBDA
_SCHEMA = 2

_TYPE_HEARTBEAT = 0
_TYPE_QSO_LOGGED = 5


# ---------------------------------------------------------------------------
# Binary encoding helpers (mirror of wsjtx.py readers)
# ---------------------------------------------------------------------------

def _u32(val: int) -> bytes:
    return struct.pack(">I", val)


def _u64(val: int) -> bytes:
    return struct.pack(">Q", val)


def _i32(val: int) -> bytes:
    return struct.pack(">i", val)


def _utf8(s: str) -> bytes:
    encoded = s.encode("utf-8")
    return _u32(len(encoded)) + encoded


def _null_utf8() -> bytes:
    """Qt null QString."""
    return _u32(0xFFFFFFFF)


def _qdatetime(dt: datetime) -> bytes:
    """Encode a UTC datetime as QDateTime (Julian day + ms-since-midnight + timespec=1 UTC)."""
    # Julian Day Number: days since Jan 1, 4713 BC
    # Python date.toordinal() counts from Jan 1, year 1 (ordinal=1)
    # Julian Day for 1970-01-01 = 2440588
    ordinal = dt.toordinal()
    jd = ordinal + 1721424  # offset from proleptic Gregorian ordinal to Julian day
    ms = (dt.hour * 3600 + dt.minute * 60 + dt.second) * 1000 + dt.microsecond // 1000
    timespec = 1  # UTC
    return _u64(jd) + _u32(ms) + bytes([timespec])


def _header(msg_type: int, client_id: str = "potatui-test") -> bytes:
    return _u32(_MAGIC) + _u32(_SCHEMA) + _u32(msg_type) + _utf8(client_id)


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def build_heartbeat(version: str = "2.7.0") -> bytes:
    body = _u32(3)          # max_schema_number
    body += _utf8(version)  # version
    body += _utf8("abc123") # revision
    return _header(_TYPE_HEARTBEAT) + body


def build_qso_logged(
    callsign: str = "W1AW",
    grid: str = "FN31",
    freq_hz: int = 14_074_000,
    mode: str = "FT8",
    rst_sent: str = "-10",
    rst_rcvd: str = "-15",
    name: str = "Test Station",
    comments: str = "fake QSO from fake_wsjtx.py",
    tx_power: str = "5",
) -> bytes:
    now = datetime.now(UTC).replace(tzinfo=None)
    body  = _qdatetime(now)   # datetime_off
    body += _utf8(callsign)   # dx_call
    body += _utf8(grid)       # dx_grid
    body += _u64(freq_hz)     # tx_freq_hz (dial freq in Hz)
    body += _utf8(mode)       # mode
    body += _utf8(rst_sent)   # rst_sent
    body += _utf8(rst_rcvd)   # rst_rcvd
    body += _utf8(tx_power)   # tx_power
    body += _utf8(comments)   # comments
    body += _utf8(name)       # name
    return _header(_TYPE_QSO_LOGGED) + body


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def send(host: str, port: int, data: bytes, label: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(data, (host, port))
    print(f"Sent {label} ({len(data)} bytes) → {host}:{port}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake WSJT-X UDP sender for potatui testing")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2237)
    parser.add_argument("--heartbeat", action="store_true", help="Send a heartbeat packet")
    parser.add_argument("--qso", action="store_true", help="Send a QSO Logged packet")
    parser.add_argument("--call", default="W1AW", help="Callsign for the fake QSO")
    parser.add_argument("--grid", default="FN31", help="Grid square for the fake QSO")
    parser.add_argument("--freq", type=int, default=14_074_000, help="Dial freq in Hz (default: 14074000)")
    parser.add_argument("--mode", default="FT8", help="Mode (default: FT8)")
    parser.add_argument("--loop", action="store_true", help="Repeat heartbeats every 15s (Ctrl+C to stop)")
    args = parser.parse_args()

    if not args.heartbeat and not args.qso:
        parser.print_help()
        return

    if args.heartbeat:
        send(args.host, args.port, build_heartbeat(), "Heartbeat")

    if args.qso:
        pkt = build_qso_logged(
            callsign=args.call,
            grid=args.grid,
            freq_hz=args.freq,
            mode=args.mode,
        )
        send(args.host, args.port, pkt, f"QSO Logged ({args.call} {args.freq / 1000:.1f} kHz {args.mode})")

    if args.loop:
        print("Sending heartbeats every 15s — Ctrl+C to stop")
        try:
            while True:
                time.sleep(15)
                send(args.host, args.port, build_heartbeat(), "Heartbeat")
        except KeyboardInterrupt:
            print("Stopped.")


if __name__ == "__main__":
    main()
