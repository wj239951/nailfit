from __future__ import annotations

import pytest

from core.color import ita_band, ita_degrees, srgb_to_lab, warmth_from_lab


def test_white_maps_to_lab_white_point() -> None:
    lightness, a, b = srgb_to_lab((255, 255, 255))
    assert lightness == pytest.approx(100.0, abs=0.5)
    assert a == pytest.approx(0.0, abs=0.5)
    assert b == pytest.approx(0.0, abs=0.5)


def test_black_maps_to_lab_black_point() -> None:
    lightness, _, _ = srgb_to_lab((0, 0, 0))
    assert lightness == pytest.approx(0.0, abs=0.5)


def test_ita_bands() -> None:
    assert ita_band(60) == "light"
    assert ita_band(30) == "mid"
    assert ita_band(0) == "deep"


def test_ita_degrees_direction() -> None:
    # 越亮 ITA 越大（同一 b* 前提下）
    lighter = ita_degrees((70.0, 10.0, 20.0))
    darker = ita_degrees((40.0, 10.0, 20.0))
    assert lighter > darker


def test_warmth_returns_known_value() -> None:
    assert warmth_from_lab((70.0, 10.0, 20.0)) in {"cool", "neutral", "warm"}
