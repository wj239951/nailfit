"""视觉层（core/vision.py）单测：纯几何量 + 质量门槛 + 肤色粗筛。

不依赖 mediapipe/opencv 跑模型：
- 几何与分类都是纯函数，直接用合成关键点测；
- 模型相关的 detect_hand 只测脚本能报错的部分（图片不存在 / 模型不存在）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import vision
from core.errors import NailFitError
from core.vision import (
    FINGERS,
    HandObservation,
    classify_hand_type,
    classify_length,
    classify_nail_bed,
    classify_shape,
    _median,
    _robust_mean,
    _width_at_point,
    finger_extension,
    finger_travel,
    nail_bed_ratio,
    palm_ratio,
    quality_gate,
)


def make_landmarks(open_hand: bool) -> list[tuple[float, float]]:
    """合成 21 个关键点：张开手 vs 握拳（指尖贴近指根）。"""
    wrist = (0.0, 0.0)
    mcp_row = {5: (-0.45, 1.00), 9: (-0.10, 1.10), 13: (0.20, 1.05), 17: (0.50, 0.95)}
    points: list[tuple[float, float]] = [wrist] * 21
    points[0] = wrist
    # 拇指
    points[1], points[2], points[3], points[4] = (-0.5, 0.4), (-0.8, 0.2), (-1.0, 0.1), (-1.2, 0.0)
    index_mcp = mcp_row[5]
    for finger, (mcp, pip, dip, tip) in FINGERS.items():
        base = mcp_row[mcp]
        points[mcp] = base
        if open_hand:
            dx, dy = (base[0] - wrist[0]) / 10.0, 1.9
            points[pip] = (base[0] + dx * 0.5, base[1] + dy * 0.33)
            points[dip] = (base[0] + dx * 0.8, base[1] + dy * 0.66)
            points[tip] = (base[0] + dx, base[1] + dy)
        else:
            # 握拳：指尖回缩到指根附近（弦长远小于骨长）
            points[pip] = (base[0] + 0.15, base[1] + 0.30)
            points[dip] = (base[0] + 0.05, base[1] + 0.15)
            points[tip] = (base[0], base[1] + 0.05)
    return points


def make_observation(
    *,
    open_hand: bool = True,
    gesture: str = "Open_Palm",
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 800.0, 800.0),
) -> HandObservation:
    return HandObservation(
        image=__import__("pathlib").Path("fake.jpg"),
        handedness="Right",
        handedness_score=0.99,
        landmarks=make_landmarks(open_hand),
        image_size=(1000, 1000),
        bbox=bbox,
        gesture=gesture,
        gesture_score=0.9,
    )


# --------------------------------------------------------------------------- 几何量
def test_open_hand_is_more_extended_than_fist():
    assert finger_extension(make_landmarks(True)) > finger_extension(make_landmarks(False)) + 0.3


def test_finger_travel_separates_open_and_fist():
    assert finger_travel(make_landmarks(True)) > vision.MIN_FINGER_TRAVEL
    assert finger_travel(make_landmarks(False)) < vision.MIN_FINGER_TRAVEL


def test_palm_ratio_is_positive_and_stable():
    ratio = palm_ratio(make_landmarks(True))
    assert 0.3 < ratio < 3.0


# --------------------------------------------------------------------------- 分类阈值
def test_hand_type_thresholds():
    assert classify_hand_type(0.5) == "slim"
    assert classify_hand_type(0.95) == "standard"
    assert classify_hand_type(1.5) == "fleshy"
    assert classify_hand_type(0.0) == "standard"


def test_nail_bed_thresholds():
    assert nail_bed_ratio(60, 100) == "slender"
    assert nail_bed_ratio(85, 100) == "standard"
    assert nail_bed_ratio(120, 100) == "short_wide"
    assert nail_bed_ratio(0, 0) == "standard"


def test_shape_classification():
    assert classify_shape(0.95, 0.95) == "square"
    assert classify_shape(0.85, 0.92) == "squoval"
    assert classify_shape(0.78, 0.93) == "round"
    assert classify_shape(0.60, 0.60) == "almond"
    assert classify_shape(0.0, 0.0) == "oval"


def test_length_classification():
    assert classify_length(50, 100) == "very_short"
    assert classify_length(95, 100) == "short"
    assert classify_length(120, 100) == "mid"
    assert classify_length(160, 100) == "long"


# --------------------------------------------------------------------------- 质量门槛
def test_quality_ok_for_open_palm():
    quality, notes = quality_gate(make_observation(open_hand=True))
    assert quality == "ok"
    assert isinstance(notes, list)


def test_quality_clenched_for_fist_gesture():
    quality, notes = quality_gate(
        make_observation(open_hand=False, gesture="Closed_Fist")
    )
    assert quality == "clenched"
    assert "Closed_Fist" in notes[0]


def make_relaxed_landmarks() -> list[tuple[float, float]]:
    """手指「有点扣」：指尖向掌心方向折回，伸展度落在 0.60–0.88。"""
    points = make_landmarks(open_hand=True)
    offsets = ((0.10, 0.35), (0.20, 0.70), (0.35, 0.55))  # pip / dip / tip 相对 mcp
    for mcp, pip, dip, tip in FINGERS.values():
        base = points[mcp]
        for index, (dx, dy) in zip((pip, dip, tip), offsets):
            points[index] = (base[0] + dx, base[1] + dy)
    return points


def test_quality_relaxed_for_slightly_bent_hand():
    """自然随手拍（手略扣）不判错，只降级到「只出肤色」，提示用下拉补。"""
    obs = make_observation(open_hand=True, gesture="Unknown")
    obs.landmarks = make_relaxed_landmarks()
    quality, notes = quality_gate(obs)
    assert quality == "relaxed"
    assert "下拉" in notes[0]


def test_quality_ok_for_flat_hand_without_gesture():
    """手势模型没给 Open_Palm 时，几何伸展度足够也算平放/自然展开。"""
    quality, notes = quality_gate(make_observation(open_hand=True, gesture="None"))
    assert quality == "ok"
    assert "自然展开" in notes[0]


def test_quality_pose_when_palm_foreshortened():
    obs = make_observation(open_hand=True, gesture="Unknown")
    # 把横向拉宽 2.5 倍，模拟「手朝镜头、掌宽/掌长失真」
    obs.landmarks = [(x * 2.5, y) for x, y in obs.landmarks]
    quality, notes = quality_gate(obs)
    assert quality == "pose"
    assert notes


def test_quality_low_for_tiny_hand():
    quality, _ = quality_gate(
        make_observation(bbox=(0.0, 0.0, 10.0, 10.0))
    )
    assert quality == "low"


def test_quality_low_for_low_handedness():
    obs = make_observation()
    obs.handedness_score = 0.3
    quality, _ = quality_gate(obs)
    assert quality == "low"


# --------------------------------------------------------------------------- 肤色
@pytest.mark.parametrize(
    "rgb, expected",
    [
        ((210, 180, 160), True),   # 浅肤色
        ((150, 105, 85), True),    # 中等肤色
        ((59, 59, 64), False),     # 深灰袖口
        ((255, 255, 255), False),  # 过曝
    ],
)
def test_looks_like_skin(rgb, expected):
    assert vision._looks_like_skin(rgb) is expected


def test_classify_skin_returns_project_enums():
    result = vision.classify_skin((210, 180, 160))
    assert result["ita_band"] in {"light", "mid", "deep"}
    assert result["warmth"] in {"warm", "neutral", "cool"}
    assert isinstance(result["ita_degrees"], float)


# --------------------------------------------------------------------------- 入口错误
@pytest.fixture()
def scratch_dir():
    """项目内临时目录（DSH 沙箱下系统 tmp 不可写，pytest 的 tmp_path 会 PermissionError）。"""
    path = Path(__file__).resolve().parents[1] / "tests" / "_scratch_vision"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_detect_hand_rejects_missing_image(scratch_dir):
    with pytest.raises(vision.VisionError):
        vision.detect_hand(scratch_dir / "nope.jpg")


def test_ensure_model_raises_when_missing(scratch_dir):
    with pytest.raises(vision.VisionError):
        vision.ensure_model(scratch_dir / "no.task")


def test_vision_error_is_naiffit_error():
    assert issubclass(vision.VisionError, NailFitError)


# --------------------------------------------------------------------------- M12 量测回归
def test_width_at_point_sums_both_directions():
    """宽度要两侧分别走，不能只取一侧最大（M12 修掉的饱和 bug）。"""
    import numpy as np

    mask = np.zeros((60, 100), dtype=np.uint8)
    mask[20:41, 5:95] = 255  # 21px 高的一条带
    assert _width_at_point(np, mask, (50.0, 30.0), (1.0, 0.0)) == 21.0


def test_width_at_point_snaps_to_nearest_foreground():
    import numpy as np

    mask = np.zeros((60, 100), dtype=np.uint8)
    mask[20:41, 5:95] = 255
    # (50, 10) 在带外，但 14px 内能吸附到带子上
    assert _width_at_point(np, mask, (50.0, 10.0), (1.0, 0.0)) == 21.0


def test_width_at_point_stops_at_mask_boundary():
    import numpy as np

    mask = np.zeros((60, 100), dtype=np.uint8)
    mask[20:41, 5:45] = 255  # 半宽 20
    assert _width_at_point(np, mask, (25.0, 30.0), (1.0, 0.0)) == 21.0


def test_width_at_point_returns_zero_outside_mask():
    import numpy as np

    mask = np.zeros((60, 100), dtype=np.uint8)
    assert _width_at_point(np, mask, (50.0, 30.0), (1.0, 0.0)) == 0.0


def test_median_handles_even_and_odd():
    assert _median([3.0]) == 3.0
    assert _median([1.0, 3.0]) == 2.0
    assert _median([5.0, 1.0, 3.0]) == 3.0


def test_robust_mean_drops_outlier():
    assert _robust_mean([80.0, 82.0, 200.0]) == pytest.approx(81.0)
    assert _robust_mean([]) == 0.0


def test_classify_nail_bed_uses_aspect():
    assert classify_nail_bed(0.6) == "slender"
    assert classify_nail_bed(0.8) == "standard"
    assert classify_nail_bed(1.1) == "short_wide"
    assert classify_nail_bed(0.0) == "standard"
