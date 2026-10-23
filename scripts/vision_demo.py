"""手照 → 手部特征（M8 视觉层）命令行入口。

用法：

    # 首次先下载关键点模型（约 7.5MB）
    python scripts/vision_demo.py --download-model

    # 跑单张
    python scripts/vision_demo.py raw_hands/hand01_right_01.jpg

    # 跑整个目录
    python scripts/vision_demo.py --dir raw_hands

    # 输出 JSON（接 API / 评测）
    python scripts/vision_demo.py --dir raw_hands --json out/vision.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.errors import NailFitError  # noqa: E402
from core.labels import summarize  # noqa: E402
from core.vision import VisionError, ensure_model, extract  # noqa: E402

FEATURE_NAMES = ["nail_bed_ratio", "nail_shape", "length", "ita_band", "warmth", "hand_type"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="手照 → 手部特征（MediaPipe 视觉层）")
    parser.add_argument("images", nargs="*", type=Path, help="一张或多张手照路径")
    parser.add_argument("--dir", type=Path, help="跑整个目录下的 jpg/png")
    parser.add_argument("--model", type=Path, default=None, help="手部关键点模型路径")
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="模型缺失时不自动下载（默认会自动下载到 models/）",
    )
    parser.add_argument("--no-preview", action="store_true", help="不生成关键点标注图")
    parser.add_argument("--scene", default="commute", help="补进 HandFeatures 的场景（手照推断不出来）")
    parser.add_argument("--json", type=Path, default=None, help="把结果写到 JSON 文件")
    return parser


def collect_images(args: argparse.Namespace) -> list[Path]:
    images = list(args.images)
    if args.dir:
        images.extend(
            sorted(
                p
                for p in args.dir.iterdir()
                if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
            )
        )
    if not images:
        default = ROOT / "raw_hands"
        if default.exists():
            images = sorted(p for p in default.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    return images


def print_result(path: Path, result, scene: str) -> None:
    observation = result.observation
    print("=" * 62)
    print(
        f"{path.name}  →  {observation.handedness} 手  "
        f"(置信度 {observation.handedness_score:.2f}，手势 {observation.gesture} "
        f"{observation.gesture_score:.2f}，手占画面 {observation.bbox_area_ratio:.1%}，"
        f"照片质量 {result.quality})"
    )
    features = result.features
    for name in FEATURE_NAMES:
        if name in features:
            confidence = result.confidences.get(name, 0.0)
            print(f"  {name:<15}{features[name]:<12}（置信度 {confidence:.2f}）")
        else:
            print(f"  {name:<15}{'—':<12}（不可靠，需张开五指重拍）")
    if result.metrics.get("ita_degrees") is not None:
        print(f"  ITA°            {result.metrics['ita_degrees']:.1f}")
    for key in ("hand_extension", "finger_travel", "palm_ratio", "aspect", "taper"):
        if key in result.metrics:
            print(f"  {key:<15}{result.metrics[key]:.2f}")
    for note in result.notes:
        print(f"  · {note}")
    try:
        features_obj = result.to_hand_features(scene=scene)
        print(f"  特征摘要：{summarize(features_obj.to_dict())}")
    except NailFitError as exc:  # 缺字段时提示，不影响其它图
        print(f"  · 暂不能组装 HandFeatures：{exc}")
    if result.preview:
        print(f"  标注图：{result.preview}")


def main() -> int:
    args = build_parser().parse_args()
    try:
        model = ensure_model(args.model, download=not args.no_download)
    except VisionError as exc:
        print(f"✗ {exc}")
        return 2
    print(f"模型：{model}")

    images = collect_images(args)
    if not images:
        print("✗ 没找到手照：传路径、--dir，或把图片放进 raw_hands/")
        return 2

    payload: list[dict] = []
    ok = 0
    declined = 0
    qualities: dict[str, int] = {}
    for path in images:
        try:
            result = extract(
                path, model, preview=not args.no_preview, auto_download=not args.no_download
            )
        except VisionError as exc:
            print("=" * 62)
            print(f"{path.name}  →  ✗ {exc}")
            payload.append({"image": str(path), "error": str(exc)})
            continue
        ok += 1
        if result.quality != "ok":
            declined += 1
        qualities[result.quality] = qualities.get(result.quality, 0) + 1
        print_result(path, result, args.scene)
        payload.append(
            {
                "image": str(path),
                "quality": result.quality,
                "handedness": result.observation.handedness,
                "handedness_score": round(result.observation.handedness_score, 3),
                "gesture": result.observation.gesture,
                "features": result.features,
                "confidences": result.confidences,
                "metrics": {k: round(v, 2) for k, v in result.metrics.items()},
                "unreliable": result.unreliable,
                "notes": result.notes,
                "preview": str(result.preview) if result.preview else None,
            }
        )

    print("=" * 62)
    print(f"完成 {ok}/{len(images)} 张；照片质量分布：{qualities or '—'}")
    if declined:
        print(
            f"其中 {declined} 张不是标准手背照（握拳/侧位/手朝镜头），只输出肤色，"
            "甲型/甲长/手型按「不可靠」处理 —— 拍法见 README「视觉层」一节。"
        )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON → {args.json}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
