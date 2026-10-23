"""手照 → 手部特征（M8 视觉层）。

链路：

    手照 ──MediaPipe HandLandmarker──► 21 关键点 ──几何启发式──► 甲型 / 甲长 / 手型
                                      └─皮肤色块──► ITA° / 冷暖

设计原则（和项目其它部分一致）：

- **规则可解释**：每个特征都保留原始几何量（metrics）和置信度，前端/文档能追溯。
- **不硬猜**：手指弯曲、手太小、检测置信度低时，相关特征降级为「不可靠」，由调用方
  回退到手工录入（M11），而不是编一个看起来合理的值。
- **纯函数优先**：几何换算、阈值分类、ITA° 都不依赖 cv2 / mediapipe，方便单测；
  只有真正读图和跑模型的两个函数需要可选依赖。

注意：这里的阈值是**启发式初值**，必须用真实手照校准（M12），不要当成医学测量。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .color import ita_band, ita_degrees, srgb_to_lab, warmth_from_lab
from .errors import NailFitError
from .features import HandFeatures

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "gesture_recognizer.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
    "gesture_recognizer/float16/1/gesture_recognizer.task"
)
PREVIEW_DIR = ROOT / "static" / "preview"

# MediaPipe 21 点索引
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
FINGERS = {
    "index": (5, 6, 7, 8),
    "middle": (9, 10, 11, 12),
    "ring": (13, 14, 15, 16),
    "pinky": (17, 18, 19, 20),
}
INDEX_MCP = 5
MIDDLE_MCP = 9
RING_MCP = 13
PINKY_MCP = 17
MIDDLE_TIP = 12

# 质量门槛（启发式）
MIN_BBOX_AREA = 0.03          # 手部检测框面积占整图比例
MIN_HANDEDNESS = 0.65         # MediaPipe 左右手置信度
# 自然角度支持：多数人随手拍的是「握拳/半握展示美甲」，这种角度只出肤色；
# 手势是 Open_Palm，或几何伸展度 ≥ OPEN_EXTENSION（手背平放 / 自然展开）时才全自动量甲面。
OPEN_EXTENSION = 0.88
RELAXED_EXTENSION = 0.60      # 0.60–0.88：手略扣，甲面量测不可靠，只出肤色
OPEN_GESTURES = ("Open_Palm",)  # 手势模型给「张开手掌」时直接放行
CLENCHED_GESTURES = (
    "Closed_Fist",
    "Thumb_Up",
    "Thumb_Down",
    "Pointing_Up",
    "Victory",
    "ILoveYou",
)
# 手势模型没识别出姿势时，用「指尖到指根的平均距离 / 掌长」兜底（仅作参考量）
MIN_FINGER_TRAVEL = 0.55
# 手掌透视：掌宽/掌长超过这个值，说明手朝镜头/侧位，2D 量甲面没有意义
MAX_PALM_RATIO = 1.35

# 手型阈值：palm_width / palm_length（M12 用真实数据校准）
HAND_TYPE_THRESHOLDS = (0.82, 0.98)   # <0.82 slim，<0.98 standard，其余 fleshy

# 甲床比例阈值：nail_width / nail_length
NAIL_BED_THRESHOLDS = (0.75, 0.95)    # <0.75 slender，<0.95 standard，其余 short_wide

# 甲型阈值（taper = tip_width / dip_width；aspect = nail_width / nail_length）
TAPER_ALMOND = 0.72
TAPER_SQUARE = 0.90
ASPECT_SQUARE = 0.88
ASPECT_SQUOVAL = 0.80
ASPECT_ROUND = 0.72

# 甲长阈值：nail_length / dip_width
LENGTH_VERY_SHORT = 0.85
LENGTH_MID = 1.10


class VisionError(NailFitError):
    """视觉层不可用 / 手照不可用。"""


# --------------------------------------------------------------------------- 数据结构
@dataclass
class HandObservation:
    """一张图里选中的那只手。"""

    image: Path
    handedness: str                     # "Left" / "Right"
    handedness_score: float
    landmarks: list[tuple[float, float]]  # 像素坐标
    image_size: tuple[int, int]         # (width, height)
    bbox: tuple[float, float, float, float]
    gesture: str = "Unknown"            # MediaPipe 手势分类（Open_Palm / Closed_Fist …）
    gesture_score: float = 0.0

    @property
    def bbox_area_ratio(self) -> float:
        _, _, w, h = self.bbox
        iw, ih = self.image_size
        return (w * h) / max(1.0, iw * ih) if iw and ih else 0.0


@dataclass
class VisionResult:
    """视觉层输出：可用特征 + 置信度 + 原始几何量 + 说明。"""

    observation: HandObservation
    quality: str = "ok"                 # ok / clenched / pose / low
    features: dict[str, str] = field(default_factory=dict)
    confidences: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    unreliable: list[str] = field(default_factory=list)
    preview: Path | None = None

    def to_hand_features(self, scene: str = "commute") -> HandFeatures:
        """补齐 scene 并转成项目统一的 HandFeatures（不可靠字段用契约默认值）。"""
        payload: dict[str, Any] = dict(self.features)
        payload["scene"] = scene
        if "ita_degrees" in self.metrics:
            payload["ita_degrees"] = round(float(self.metrics["ita_degrees"]), 1)
        return HandFeatures.from_dict(payload)


# --------------------------------------------------------------------------- 纯几何
def distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _unit(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    norm = math.hypot(dx, dy) or 1.0
    return dx / norm, dy / norm


def finger_extension(landmarks: Sequence[Sequence[float]]) -> float:
    """四指平均伸展度：弦长 / 三段骨长。伸直≈1，握拳明显小于 1。"""
    ratios: list[float] = []
    for mcp, pip, dip, tip in FINGERS.values():
        chord = distance(landmarks[mcp], landmarks[tip])
        bones = (
            distance(landmarks[mcp], landmarks[pip])
            + distance(landmarks[pip], landmarks[dip])
            + distance(landmarks[dip], landmarks[tip])
        )
        if bones > 1e-6:
            ratios.append(chord / bones)
    return sum(ratios) / len(ratios) if ratios else 0.0


def finger_travel(landmarks: Sequence[Sequence[float]]) -> float:
    """四指「指尖到指根距离 / 掌长」的平均值（手势模型失效时的兜底姿态指标）。"""
    palm_length = distance(landmarks[WRIST], landmarks[MIDDLE_MCP])
    if palm_length <= 1e-6:
        return 0.0
    ratios = [
        distance(landmarks[mcp], landmarks[tip]) / palm_length
        for mcp, _, _, tip in FINGERS.values()
    ]
    return sum(ratios) / len(ratios)


def palm_ratio(landmarks: Sequence[Sequence[float]]) -> float:
    """手型代理：掌宽 / 掌长（腕点→中指根）。越大越"肉"。"""
    palm_width = distance(landmarks[INDEX_MCP], landmarks[PINKY_MCP])
    palm_length = distance(landmarks[WRIST], landmarks[MIDDLE_MCP])
    return palm_width / palm_length if palm_length > 1e-6 else 0.0


def classify_hand_type(ratio: float) -> str:
    slim, standard = HAND_TYPE_THRESHOLDS
    if ratio <= 0:
        return "standard"
    if ratio < slim:
        return "slim"
    if ratio < standard:
        return "standard"
    return "fleshy"


def nail_bed_ratio(nail_width: float, nail_length: float) -> str:
    ratio = nail_width / nail_length if nail_length > 1e-6 else 0.0
    slender, standard = NAIL_BED_THRESHOLDS
    if ratio <= 0:
        return "standard"
    if ratio < slender:
        return "slender"
    if ratio < standard:
        return "standard"
    return "short_wide"


def classify_shape(aspect: float, taper: float) -> str:
    """甲型分类：aspect=甲宽/甲长，taper=指尖宽/甲根宽。"""
    if aspect <= 0 or taper <= 0:
        return "oval"
    if taper < TAPER_ALMOND:
        return "almond"
    if aspect >= ASPECT_SQUARE and taper >= TAPER_SQUARE:
        return "square"
    if aspect >= ASPECT_SQUOVAL:
        return "squoval"
    if aspect >= ASPECT_ROUND:
        return "round"
    return "oval"


def classify_length(nail_length: float, dip_width: float) -> str:
    ratio = nail_length / dip_width if dip_width > 1e-6 else 0.0
    if ratio <= 0:
        return "short"
    if ratio < LENGTH_VERY_SHORT:
        return "very_short"
    if ratio < LENGTH_MID:
        return "short"
    if ratio < 1.35:
        return "mid"
    return "long"


def classify_skin(rgb: tuple[int, int, int]) -> dict[str, Any]:
    """肤色分类：返回 ita_band / warmth / ita_degrees / lab。"""
    lab = srgb_to_lab(rgb)
    ita = ita_degrees(lab)
    return {
        "ita_band": ita_band(ita),
        "warmth": warmth_from_lab(lab),
        "ita_degrees": ita,
        "lab": tuple(round(v, 1) for v in lab),
    }


def quality_gate(observation: HandObservation) -> tuple[str, list[str]]:
    """返回 (quality, notes)。quality ∈ {"ok", "relaxed", "clenched", "pose", "low"}。

    设计原则：不强迫用户摆拍。随手把「握拳/半握展示美甲」的照片发上来是常态，
    这种角度只自动出肤色，其余特征让用户用下拉补（M11）；
    只有手背平放/自然展开（伸展度够，或手势模型判为 Open_Palm）时才全自动量甲面。
    """
    notes: list[str] = []
    if observation.bbox_area_ratio < MIN_BBOX_AREA:
        notes.append(f"手在画面里偏小（占 {observation.bbox_area_ratio:.1%}）")
        return "low", notes
    if observation.handedness_score < MIN_HANDEDNESS:
        notes.append(f"左右手识别置信度低（{observation.handedness_score:.2f}）")
        return "low", notes

    palm = palm_ratio(observation.landmarks)
    extension = finger_extension(observation.landmarks)
    gesture = observation.gesture

    # 掌宽/掌长过大：手朝镜头或侧位，2D 量甲面没有意义
    if palm > MAX_PALM_RATIO:
        notes.append(
            f"手掌透视过重（掌宽/掌长 {palm:.2f} > {MAX_PALM_RATIO}），手可能朝镜头或侧着；"
            "甲面量测不可靠，建议手背平放、从正上方拍一张"
        )
        return "pose", notes

    if gesture in OPEN_GESTURES or extension >= OPEN_EXTENSION:
        if gesture in OPEN_GESTURES:
            notes.append(f"手势：{gesture}（{observation.gesture_score:.2f}）")
        else:
            notes.append(f"手背自然展开（伸展度 {extension:.2f}）")
        return "ok", notes

    if extension >= RELAXED_EXTENSION:
        notes.append(
            f"手有点扣（伸展度 {extension:.2f}），甲型/甲长/甲床量不准；只自动出肤色，"
            "其余特征用下拉补选，或把手背平放在桌面从正上方拍一张"
        )
        return "relaxed", notes

    notes.append(
        f"手势：{gesture}（{observation.gesture_score:.2f}）、伸展度 {extension:.2f}；"
        "握拳/展示美甲的角度只自动出肤色，甲面与手型请用下拉补选（或手背平放重拍）"
    )
    return "clenched", notes


# --------------------------------------------------------------------------- 图像处理（可选依赖）
def _require_imaging():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - 依赖缺失分支
        raise VisionError(
            "未安装视觉依赖，无法读图/跑模型：pip install -r requirements-vision.txt"
        ) from exc
    return cv2, np


def _require_mediapipe():
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
    except ImportError as exc:  # pragma: no cover - 依赖缺失分支
        raise VisionError(
            "未安装 mediapipe，无法提取手部关键点：pip install -r requirements-vision.txt"
        ) from exc
    return mp, mp_python, mp_vision


def ensure_model(model_path: str | Path | None = None, download: bool = False) -> Path:
    """确认手势识别模型存在；download=True 时从官方地址下载（约 8MB）。"""
    path = Path(model_path) if model_path else DEFAULT_MODEL
    if path.exists():
        return path
    if not download:
        raise VisionError(
            f"缺少手部手势模型：{path}\n"
            f"运行 python scripts/vision_demo.py --download-model 自动下载，"
            f"或手动下载：{MODEL_URL}"
        )
    import urllib.request

    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"下载手势模型（约 8MB）→ {path}")
    urllib.request.urlretrieve(MODEL_URL, path)  # noqa: S310 - 固定的官方 https 地址
    return path


def model_status(model_path: str | Path | None = None) -> dict:
    """给前端/状态页用：模型是否已就绪。"""
    path = Path(model_path) if model_path else DEFAULT_MODEL
    return {
        "path": str(path),
        "installed": path.exists(),
        "size_mb": round(path.stat().st_size / 1024 / 1024, 1) if path.exists() else 0.0,
        "url": MODEL_URL,
    }


_DETECTOR_CACHE: dict[str, Any] = {}


def _recognizer(model_path: Path, num_hands: int = 2, min_confidence: float = 0.3):
    """按模型路径缓存 GestureRecognizer（建一次约 0.3s，批量处理时复用）。

    用 GestureRecognizer 而不是 HandLandmarker：它同时给出 21 点关键点和手势分类，
    手势（Open_Palm / Closed_Fist …）是判断「能不能量甲面」最可靠的信号。
    """
    _, mp_python, mp_vision = _require_mediapipe()
    key = f"{model_path}|{num_hands}|{min_confidence}"
    if key not in _DETECTOR_CACHE:
        options = mp_vision.GestureRecognizerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_hands=num_hands,
            min_hand_detection_confidence=min_confidence,
            min_hand_presence_confidence=min_confidence,
        )
        _DETECTOR_CACHE[key] = mp_vision.GestureRecognizer.create_from_options(options)
    return _DETECTOR_CACHE[key]


def _load_rgb(image_path: str | Path):
    cv2, np = _require_imaging()
    bgr = cv2.imread(str(image_path))
    if bgr is None:
        raise VisionError(f"图片读不出来：{image_path}")
    return cv2, np, bgr


def detect_hand(
    image_path: str | Path,
    model_path: str | Path | None = None,
    auto_download: bool = False,
) -> HandObservation:
    """检测图中主手并返回像素坐标关键点（多手时取检测框面积最大的那只）。"""
    path = Path(image_path)
    if not path.exists():
        raise VisionError(f"图片不存在：{path}")
    model = ensure_model(model_path, download=auto_download)
    mp, _, _ = _require_mediapipe()
    cv2, _, bgr = _load_rgb(path)
    height, width = bgr.shape[:2]

    image = mp.Image.create_from_file(str(path))
    result = _recognizer(model, num_hands=2).recognize(image)
    if not result.hand_landmarks:
        raise VisionError(f"没检测到手：{path.name}（手要完整入镜、光线充足）")

    candidates: list[HandObservation] = []
    for index, landmarks in enumerate(result.hand_landmarks):
        category = result.handedness[index][0]
        gesture = result.gestures[index][0] if result.gestures and result.gestures[index] else None
        xs = [lm.x * width for lm in landmarks]
        ys = [lm.y * height for lm in landmarks]
        bbox = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        candidates.append(
            HandObservation(
                image=path,
                handedness=str(category.category_name or "Unknown"),
                handedness_score=float(category.score or 0.0),
                landmarks=[(float(x), float(y)) for x, y in zip(xs, ys)],
                image_size=(width, height),
                bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                gesture=str(gesture.category_name or "Unknown") if gesture else "Unknown",
                gesture_score=float(gesture.score or 0.0) if gesture else 0.0,
            )
        )
    return max(candidates, key=lambda obs: obs.bbox_area_ratio)


# --------------------------------------------------------------------------- 皮肤与甲面测量
def _skin_mask(cv2, np, bgr):
    """YCrCb 近似肤色掩膜（只用于量手指宽度，不追求通用分割）。"""
    ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    y, cr, cb = cv2.split(ycrcb)
    mask = (
        (y > 40)
        & (y < 250)
        & (cr > 128)
        & (cr < 185)
        & (cb > 70)
        & (cb < 140)
    ).astype(np.uint8) * 255
    kernel = np.ones((3, 3), np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)


def _width_at_point(np, mask, point: tuple[float, float], axis: tuple[float, float],
                    max_half: int = 45) -> float:
    """沿垂直于手指轴线的方向，量穿过 point 的肤色连续区间长度（像素）。

    point 不在肤色掩膜上时，先在附近找最近的肤色像素再量（关键点常压在指甲/高光上）。
    """
    height, width = mask.shape[:2]

    def skin(x: float, y: float) -> bool:
        xi, yi = int(round(x)), int(round(y))
        return 0 <= xi < width and 0 <= yi < height and mask[yi, xi] > 0

    px, py = point
    if not skin(px, py):
        found = None
        for radius in (2, 4, 6, 8, 10, 12):
            for dx in range(-radius, radius + 1, 2):
                for dy in range(-radius, radius + 1, 2):
                    if skin(px + dx, py + dy):
                        found = (px + dx, py + dy)
                        break
                if found:
                    break
            if found:
                break
        if found is None:
            return 0.0
        px, py = found

    perp_x, perp_y = -axis[1], axis[0]
    half = 0.0
    for sign in (1.0, -1.0):
        step = 1.0
        while step <= max_half and skin(px + perp_x * step * sign, py + perp_y * step * sign):
            half = step
            step += 1.0
    return 2.0 * half + 1.0


def measure_fingers(cv2, np, bgr, observation: HandObservation) -> dict[str, float]:
    """量指宽/甲宽/甲长等像素量（握拳时数值不可信，由 quality_gate 负责标注）。"""
    mask = _skin_mask(cv2, np, bgr)
    landmarks = observation.landmarks
    dip_widths: list[float] = []
    nail_widths: list[float] = []
    tip_widths: list[float] = []
    nail_lengths: list[float] = []
    for finger in ("index", "middle", "ring"):
        _, pip, dip, tip = FINGERS[finger]
        axis = _unit(landmarks[pip], landmarks[tip])
        dip_point = landmarks[dip]
        tip_point = landmarks[tip]
        # 甲面大致位于 DIP → 指尖 的 55%～85% 区间
        nail_mid = (
            dip_point[0] + (tip_point[0] - dip_point[0]) * 0.55,
            dip_point[1] + (tip_point[1] - dip_point[1]) * 0.55,
        )
        tip_mid = (
            dip_point[0] + (tip_point[0] - dip_point[0]) * 0.85,
            dip_point[1] + (tip_point[1] - dip_point[1]) * 0.85,
        )
        dip_w = _width_at_point(np, mask, dip_point, axis)
        nail_w = _width_at_point(np, mask, nail_mid, axis)
        tip_w = _width_at_point(np, mask, tip_mid, axis)
        if dip_w > 2 and nail_w > 2:
            dip_widths.append(dip_w)
            nail_widths.append(nail_w)
            tip_widths.append(tip_w if tip_w > 2 else nail_w)
            nail_lengths.append(max(1.0, distance(dip_point, tip_point)))

    metrics: dict[str, float] = {}
    if dip_widths:
        metrics["dip_width_px"] = sum(dip_widths) / len(dip_widths)
        metrics["nail_width_px"] = sum(nail_widths) / len(nail_widths)
        metrics["tip_width_px"] = sum(tip_widths) / len(tip_widths)
        metrics["nail_length_px"] = sum(nail_lengths) / len(nail_lengths)
        metrics["aspect"] = metrics["nail_width_px"] / max(1.0, metrics["nail_length_px"])
        metrics["taper"] = metrics["tip_width_px"] / max(1.0, metrics["dip_width_px"])
    return metrics


def _looks_like_skin(rgb: tuple[int, int, int]) -> bool:
    """用 Lab 亮度和彩度粗筛皮肤（排除深色袖口、灰背景、过曝高光）。"""
    lab = srgb_to_lab(rgb)
    lightness, a, b = lab
    chroma = math.hypot(a, b)
    return 22.0 <= lightness <= 93.0 and 4.0 <= chroma <= 45.0


def _patch_rgb(np, bgr, x: float, y: float, half: int = 6) -> tuple[int, int, int] | None:
    height, width = bgr.shape[:2]
    x0, x1 = max(0, int(x) - half), min(width, int(x) + half)
    y0, y1 = max(0, int(y) - half), min(height, int(y) + half)
    patch = bgr[y0:y1, x0:x1]
    if patch.size == 0:
        return None
    b, g, r = np.median(patch.reshape(-1, 3), axis=0)
    return (int(r), int(g), int(b))


def sample_skin(cv2, np, bgr, observation: HandObservation) -> tuple[int, int, int]:
    """取手背/指根附近的皮肤中位色（避开指甲、高光、深色袖口和指缝阴影）。

    在掌心和指根周围撒一串小采样点，先过肤色 Lab 粗筛，再按亮度中位数过滤掉
    明显偏暗的阴影点，最后取中位色——自然角度（握拳、手朝镜头）下也尽量稳。
    """
    landmarks = observation.landmarks
    mask = _skin_mask(cv2, np, bgr)
    wrist = landmarks[WRIST]
    mcp_points = [landmarks[i] for i in (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)]
    center = (
        sum(p[0] for p in mcp_points) / 4.0,
        sum(p[1] for p in mcp_points) / 4.0,
    )
    candidates: list[tuple[float, float]] = []
    for t in (0.35, 0.5, 0.65):
        candidates.append(
            (
                wrist[0] + (center[0] - wrist[0]) * t,
                wrist[1] + (center[1] - wrist[1]) * t,
            )
        )
    candidates.append(center)
    for mcp in mcp_points:
        for t in (0.2, 0.4):
            candidates.append(
                (
                    mcp[0] + (center[0] - mcp[0]) * t,
                    mcp[1] + (center[1] - mcp[1]) * t,
                )
            )
    # 相邻指根连线的中点（指蹼/手背），光更均匀
    for first, second in zip(mcp_points, mcp_points[1:]):
        candidates.append(((first[0] + second[0]) / 2.0, (first[1] + second[1]) / 2.0))

    height, width = bgr.shape[:2]
    samples: list[tuple[int, int, int]] = []
    for x, y in candidates:
        xi, yi = int(round(x)), int(round(y))
        if not (0 <= xi < width and 0 <= yi < height) or mask[yi, xi] == 0:
            continue
        rgb = _patch_rgb(np, bgr, x, y)
        if rgb and _looks_like_skin(rgb):
            samples.append(rgb)

    if samples:
        lumas = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in samples]
        threshold = float(np.median(lumas)) * 0.85
        lit = [rgb for rgb, luma in zip(samples, lumas) if luma >= threshold]
        samples = lit or samples
        r = int(round(float(np.median([s[0] for s in samples]))))
        g = int(round(float(np.median([s[1] for s in samples]))))
        b = int(round(float(np.median([s[2] for s in samples]))))
        return (r, g, b)

    # 候选点都不合格：退回「手部检测框内的肤色像素」，同样先去掉阴影再取中位色
    x, y, w, h = (int(round(v)) for v in observation.bbox)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(bgr.shape[1], x + w), min(bgr.shape[0], y + h)
    region_mask = mask[y0:y1, x0:x1]
    region = bgr[y0:y1, x0:x1][region_mask > 0]
    if region.size:
        region = region.reshape(-1, 3)
        lumas = region[:, 0] * 0.114 + region[:, 1] * 0.587 + region[:, 2] * 0.299
        threshold = float(np.median(lumas)) * 0.85
        lit = region[lumas >= threshold]
        pixels = lit if len(lit) else region
        b_channel, g_channel, r_channel = np.median(pixels, axis=0)
        rgb = (int(r_channel), int(g_channel), int(b_channel))
        if _looks_like_skin(rgb):
            return rgb
    fallback = _patch_rgb(np, bgr, center[0], center[1])
    if fallback and _looks_like_skin(fallback):
        return fallback
    return (200, 170, 150)


def draw_preview(cv2, np, bgr, observation: HandObservation, result_features: dict[str, str],
                 preview_path: Path) -> Path:
    """关键点标注 + 特征摘要，存到 static/preview/（不入库）。"""
    canvas = bgr.copy()
    landmarks = observation.landmarks
    connections = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (5, 9), (9, 10), (10, 11), (11, 12),
        (9, 13), (13, 14), (14, 15), (15, 16),
        (13, 17), (17, 18), (18, 19), (19, 20),
        (0, 17),
    ]
    for a, b in connections:
        p1 = tuple(int(round(v)) for v in landmarks[a])
        p2 = tuple(int(round(v)) for v in landmarks[b])
        cv2.line(canvas, p1, p2, (0, 255, 0), 3, cv2.LINE_AA)
    for x, y in landmarks:
        cv2.circle(canvas, (int(round(x)), int(round(y))), 6, (0, 128, 255), -1, cv2.LINE_AA)
    x, y, w, h = (int(round(v)) for v in observation.bbox)
    cv2.rectangle(canvas, (x, y), (x + w, y + h), (255, 128, 0), 3)

    lines = [
        f"{observation.handedness} ({observation.handedness_score:.2f})",
        f"gesture: {observation.gesture} ({observation.gesture_score:.2f})",
    ]
    lines += [f"{key}: {value}" for key, value in result_features.items()]
    y0 = 30
    for line in lines:
        cv2.putText(canvas, line, (15, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(canvas, line, (15, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        y0 += 38

    preview_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(preview_path), canvas)
    return preview_path


# --------------------------------------------------------------------------- 主入口
def extract(
    image_path: str | Path,
    model_path: str | Path | None = None,
    preview: bool = True,
    preview_dir: str | Path | None = None,
    auto_download: bool = False,
) -> VisionResult:
    """一张手照 → VisionResult（可用特征 + 置信度 + 原始量 + 说明）。"""
    cv2, np, bgr = _load_rgb(image_path)
    observation = detect_hand(image_path, model_path, auto_download=auto_download)
    quality, notes = quality_gate(observation)
    metrics: dict[str, float] = {}
    features: dict[str, str] = {}
    confidences: dict[str, float] = {}
    unreliable: list[str] = []

    metrics["hand_extension"] = round(finger_extension(observation.landmarks), 3)
    metrics["finger_travel"] = round(finger_travel(observation.landmarks), 3)
    metrics["palm_ratio"] = round(palm_ratio(observation.landmarks), 3)

    # 肤色：任何手势都能测皮肤（避开袖口/指甲后取中位色）
    rgb = sample_skin(cv2, np, bgr, observation)
    skin = classify_skin(rgb)
    features["ita_band"] = skin["ita_band"]
    features["warmth"] = skin["warmth"]
    metrics["ita_degrees"] = skin["ita_degrees"]
    metrics["skin_luma"] = round(sum(rgb) / 3.0, 1)
    confidences["ita_band"] = 0.75 if quality != "low" else 0.5
    confidences["warmth"] = 0.55 if quality != "low" else 0.35
    notes.append(f"皮肤采样 RGB={rgb}，Lab={skin['lab']}")

    # 逆光/欠曝时肤色会被判深：降置信度并提示，别让用户以为是自己肤色问题
    if metrics["skin_luma"] < 140:
        for key in ("ita_band", "warmth"):
            confidences[key] = round(confidences[key] * 0.6, 2)
        notes.append(
            f"照片偏暗/逆光（手部亮度 {metrics['skin_luma']:.0f}），肤色可能被判深，建议顺光拍"
        )

    # 手型：palm_width / palm_length，需要手掌平面基本正对镜头
    if quality == "ok":
        hand_type = classify_hand_type(metrics["palm_ratio"])
        features["hand_type"] = hand_type
        confidences["hand_type"] = 0.6
    else:
        unreliable.append("hand_type")
        if quality in {"relaxed", "clenched"}:
            notes.append(
                "手型没自动量：手掌没放平/正对镜头时掌宽掌长不可比，可用下拉补选"
            )
        else:
            notes.append("手型没自动量：透视过重或手太小，可用下拉补选")

    # 甲面量测：只接受「手背平放 / 自然展开」的 ok 质量
    finger_metrics = measure_fingers(cv2, np, bgr, observation)
    metrics.update(finger_metrics)
    if quality == "ok" and "nail_width_px" in finger_metrics:
        features["nail_bed_ratio"] = nail_bed_ratio(
            finger_metrics["nail_width_px"], finger_metrics["nail_length_px"]
        )
        features["nail_shape"] = classify_shape(
            finger_metrics.get("aspect", 0.0), finger_metrics.get("taper", 0.0)
        )
        features["length"] = classify_length(
            finger_metrics["nail_length_px"], finger_metrics["dip_width_px"]
        )
        confidences.update({"nail_bed_ratio": 0.55, "nail_shape": 0.5, "length": 0.5})
    else:
        unreliable.extend(["nail_bed_ratio", "nail_shape", "length"])
        if quality == "ok":
            notes.append("甲面量测失败：手部轮廓没取到，建议光线更均匀、指甲不要贴边")
        elif quality in {"relaxed", "clenched"}:
            notes.append(
                "甲床/甲型/甲长用当前这个角度量不准，先用下拉补选即可；"
                "想要全自动的话，把手背平放在桌面、手机从正上方拍一张"
            )
        else:
            notes.append("甲床/甲型/甲长未输出：照片角度或清晰度不够，建议手背平放、从正上方拍")

    result = VisionResult(
        observation=observation,
        quality=quality,
        features=features,
        confidences=confidences,
        metrics=metrics,
        notes=notes,
        unreliable=unreliable,
    )
    if preview:
        out_dir = Path(preview_dir) if preview_dir else PREVIEW_DIR
        result.preview = draw_preview(
            cv2, np, bgr, observation, features, out_dir / f"vision_{observation.image.stem}.jpg"
        )
    return result
