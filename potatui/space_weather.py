# SPDX-License-Identifier: CC-BY-NC-SA-4.0
# Copyright (c) 2026 MonkeybutlerCJH (https://github.com/MonkeybutlerCJH)

"""NOAA space weather data fetching — Kp index and geomagnetic storm alerts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
_ALERTS_URL = "https://services.swpc.noaa.gov/products/alerts.json"
_SFI_URL = "https://services.swpc.noaa.gov/products/summary/10cm-flux.json"
_MUF_URL = "https://prop.kc2g.com/api/point_prediction.json"

# Age threshold (seconds) beyond which MUF model data is considered stale
_MUF_STALE_SECONDS = 17 * 60

# Minimum interval between API calls as requested by prop.kc2g.com
_MUF_CACHE_SECONDS = 15 * 60

# In-memory cache: maps (lat, lon) → (MufData, monotonic fetch time)
_muf_cache: dict[tuple[float, float], tuple[MufData, float]] = {}


@dataclass
class KpReading:
    time_utc: str
    kp: float


@dataclass
class SpaceWeatherAlert:
    product_id: str
    issue_datetime: str
    message: str

    @property
    def alert_key(self) -> str:
        return f"{self.product_id}|{self.issue_datetime}"


@dataclass
class MufData:
    mufd: float
    fof2: float
    ts: int  # Unix timestamp of model data
    stale: bool  # True if data is older than _MUF_STALE_SECONDS


@dataclass
class SpaceWeatherData:
    kp_current: float | None
    kp_history: list[KpReading]
    active_alerts: list[SpaceWeatherAlert]
    sfi: float | None = None
    fetch_error: bool = False


def kp_severity(kp: float) -> str:
    """Returns 'normal', 'elevated', or 'storm'."""
    if kp >= 7:
        return "storm"
    if kp >= 5:
        return "elevated"
    return "normal"


async def fetch_kp() -> list[KpReading]:
    """Fetch the last 8 Kp readings, newest first."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_KP_URL)
        resp.raise_for_status()
        data = resp.json()
    # data is [[datetime_str, kp_str, ...], ...], first row is header
    readings: list[KpReading] = []
    for row in data[1:]:
        try:
            readings.append(KpReading(time_utc=row[0], kp=float(row[1])))
        except (IndexError, ValueError):
            continue
    # newest first, cap at 8
    readings.reverse()
    return readings[:8]


async def fetch_sfi() -> float | None:
    """Fetch the current 10.7cm solar flux index (SFI)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_SFI_URL)
        resp.raise_for_status()
        data = resp.json()
    return float(data["Flux"])


async def fetch_alerts() -> list[SpaceWeatherAlert]:
    """Fetch active geomagnetic alerts from the past 24 hours."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_ALERTS_URL)
        resp.raise_for_status()
        data = resp.json()

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    alerts: list[SpaceWeatherAlert] = []
    _relevant_prefixes = ("ALTK", "WATA", "WATS", "G1", "G2", "G3", "G4", "G5")

    for item in data:
        try:
            product_id: str = item.get("product_id", "")
            issue_str: str = item.get("issue_datetime", "")
            message: str = item.get("message", "")
        except (AttributeError, KeyError):
            continue

        if not any(product_id.startswith(p) for p in _relevant_prefixes):
            continue

        # Parse issue_datetime — format is "2024-01-15 12:00:00.000"
        try:
            issue_dt = datetime.strptime(issue_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            continue

        if issue_dt < cutoff:
            continue

        alerts.append(SpaceWeatherAlert(
            product_id=product_id,
            issue_datetime=issue_str,
            message=message,
        ))

    return alerts


async def fetch_muf(lat: float, lon: float) -> MufData:
    """Fetch MUF prediction for the given lat/lon, cached for 15 min per api owner request."""
    import time as _time

    key = (round(lat, 4), round(lon, 4))
    cached = _muf_cache.get(key)
    if cached is not None:
        result, fetched_at = cached
        if _time.monotonic() - fetched_at < _MUF_CACHE_SECONDS:
            return result

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_MUF_URL, params={"grid": f"{lat},{lon}"})
        resp.raise_for_status()
        data = resp.json()

    mufd = float(data["mufd"])
    fof2 = float(data["fof2"])
    ts = int(data["ts"])
    stale = (_time.time() - ts) > _MUF_STALE_SECONDS
    result = MufData(mufd=mufd, fof2=fof2, ts=ts, stale=stale)
    _muf_cache[key] = (result, _time.monotonic())
    return result


async def fetch_space_weather() -> SpaceWeatherData:
    """Fetch Kp index, SFI, and alerts; never raises."""
    results = await asyncio.gather(fetch_kp(), fetch_alerts(), fetch_sfi(), return_exceptions=True)

    kp_result = results[0]
    alerts_result = results[1]
    sfi_result = results[2]

    fetch_error = isinstance(kp_result, BaseException) or isinstance(alerts_result, BaseException)

    kp_history: list[KpReading] = kp_result if isinstance(kp_result, list) else []
    active_alerts: list[SpaceWeatherAlert] = alerts_result if isinstance(alerts_result, list) else []
    sfi: float | None = sfi_result if isinstance(sfi_result, float) else None

    kp_current = kp_history[0].kp if kp_history else None

    return SpaceWeatherData(
        kp_current=kp_current,
        kp_history=kp_history,
        active_alerts=active_alerts,
        sfi=sfi,
        fetch_error=fetch_error,
    )
