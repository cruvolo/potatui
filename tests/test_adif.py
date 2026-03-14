# SPDX-License-Identifier: CC-BY-NC-SA-4.0
# Copyright (c) 2026 MonkeybutlerCJH (https://github.com/MonkeybutlerCJH)

"""Tests for freq_to_band() in adif.py."""

import pytest

from potatui.adif import freq_to_band


# --------------------------------------------------------------------------
# Representative centre frequencies — should map to correct band
# --------------------------------------------------------------------------

@pytest.mark.parametrize("freq_khz, expected", [
    (1900.0,   "160m"),
    (3750.0,   "80m"),
    (5357.0,   "60m"),
    (7100.0,   "40m"),
    (10125.0,  "30m"),
    (14200.0,  "20m"),
    (18100.0,  "17m"),
    (21200.0,  "15m"),
    (24940.0,  "12m"),
    (28500.0,  "10m"),
    (52000.0,  "6m"),
    (146000.0, "2m"),
    (435000.0, "70cm"),
])
def test_centre_frequencies(freq_khz, expected):
    assert freq_to_band(freq_khz) == expected


# --------------------------------------------------------------------------
# Band boundary edge cases
# --------------------------------------------------------------------------

@pytest.mark.parametrize("freq_khz, expected", [
    # 20m boundaries (14000–14350)
    (14000.0,  "20m"),   # lower bound inclusive
    (14350.0,  "20m"),   # upper bound inclusive
    (13999.9,  "?"),     # just below 20m
    (14350.1,  "?"),     # just above 20m

    # 40m boundaries (7000–7300)
    (7000.0,   "40m"),
    (7300.0,   "40m"),
    (6999.9,   "?"),
    (7300.1,   "?"),

    # 2m boundaries (144000–148000)
    (144000.0, "2m"),
    (148000.0, "2m"),
    (143999.9, "?"),
    (148000.1, "?"),
])
def test_band_boundaries(freq_khz, expected):
    assert freq_to_band(freq_khz) == expected


# --------------------------------------------------------------------------
# Out-of-range / unknown frequencies
# --------------------------------------------------------------------------

@pytest.mark.parametrize("freq_khz", [
    0.0,
    1799.9,
    2000.1,
    500000.0,
    999999.0,
    -1.0,
])
def test_unknown_frequency_returns_question_mark(freq_khz):
    assert freq_to_band(freq_khz) == "?"
