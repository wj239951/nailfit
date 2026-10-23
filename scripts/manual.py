"""手工录入手部特征 → 输出三张美甲推荐卡。

用途：视觉层接上之前，让项目也能完整演示；同时作为识别不准时的手动兜底。

用法：
    python scripts/manual.py                        # 交互式（回车用默认值）
    python scripts/manual.py --interactive          # 强制交互（stdin 不是终端时也有用）
    python scripts/manual.py --bed short_wide --length short --ita light --warmth warm --hand fleshy --scene commute
    python scripts/manual.py --scenario deep_festival --json
    python scripts/manual.py --llm                  # 有 DEEPSEEK_API_KEY 时用云端生成理由

字段取值见 data/taxonomy.yaml → features。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.data import load_taxonomy  # noqa: E402
from core.errors import NailFitError  # noqa: E402
from core.features import FeatureError, HandFeatures  # noqa: E402
from core.labels import FIELD_TITLES, label, summarize  # noqa: E402
from core.pipeline import recommend  # noqa: E402
from core.presets import DEFAULTS, FEATURE_FIELDS, SCENARIOS  # noqa: E402
from core.validator import ContractError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    enums = load_taxonomy()["features"]
    parser = argparse.ArgumentParser(description="手工录入手部特征，输出三张推荐卡")
    parser.add_argument("--bed", dest="nail_bed_ratio", choices=enums["nail_bed_ratio"], help="甲床比例")
    parser.add_argument("--shape", dest="nail_shape", choices=enums["nail_shape"], help="当前甲型")
    parser.add_argument("--length", dest="length", choices=enums["length"], help="甲长")
    parser.add_argument("--ita", dest="ita_band", choices=enums["ita_band"], help="肤色深浅")
    parser.add_argument("--warmth", dest="warmth", choices=enums["warmth"], help="肤色冷暖")
    parser.add_argument("--hand", dest="hand_type", choices=enums["hand_type"], help="手型")
    parser.add_argument("--scene", dest="scene", choices=enums["scene"], help="使用场景")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), help="使用预设场景（覆盖其他特征参数）")
    parser.add_argument("--free-text", dest="free_text", default=None, help="自由描述，如「想要温柔显白」")
    parser.add_argument("--llm", action="store_true", help="有 DEEPSEEK_API_KEY 时用云端生成理由")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    parser.add_argument("--interactive", action="store_true", help="强制交互填写")
    parser.add_argument("--yes", action="store_true", help="非交互时直接使用默认值")
    return parser


def ask_choice(field: str, options: list[str], default: str) -> str:
    print(f"\n{FIELD_TITLES.get(field, field)}：")
    for index, value in enumerate(options, start=1):
        mark = "  ← 默认" if value == default else ""
        print(f"  {index}) {value:<12} {label(field, value)}{mark}")
    try:
        raw = input("输入序号或取值（回车=默认）: ").strip()
    except EOFError:
        raw = ""
    if not raw:
        return default
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    if raw in options:
        return raw
    print(f"  ! 无法识别 {raw!r}，使用默认值 {default}")
    return default


def features_from_args(args: argparse.Namespace) -> HandFeatures:
    enums = load_taxonomy()["features"]
    payload: dict[str, str] = dict(SCENARIOS[args.scenario]) if args.scenario else {}

    # 只要给了任一特征参数或场景，就按"参数模式"处理，不再反问；
    # 交互模式只在完全没给参数、且 stdin 是终端时启用（--interactive 可强制）。
    gave_flags = any(getattr(args, field, None) for field in FEATURE_FIELDS) or bool(args.scenario)
    interactive = args.interactive or (
        not args.yes and not args.json and not gave_flags and sys.stdin.isatty()
    )

    for field in FEATURE_FIELDS:
        provided = payload.get(field) or getattr(args, field, None)
        if provided:
            payload[field] = provided
        elif interactive:
            payload[field] = ask_choice(field, enums[field], DEFAULTS[field])
        else:
            payload[field] = DEFAULTS[field]

    try:
        return HandFeatures.from_dict(payload)
    except FeatureError as exc:
        raise SystemExit(f"特征非法：{exc}") from exc


def render(payload: dict) -> None:
    print("\n" + "=" * 62)
    print("NailFit · 推荐结果")
    print("=" * 62)
    print("特征：" + summarize(payload["features"]))
    meta = payload.get("meta", {})
    print(f"候选池：{meta.get('candidates_considered', '?')} 款可用 / {meta.get('excluded', '?')} 款被排除\n")

    for index, card in enumerate(payload["recommendations"], start=1):
        print(f"[{index}] {card['name']}  （{card['tier']} 档，匹配度 {card['match_score']:.2f}）")
        print(f"    图：{card['image']}")
        print(f"    理由：{card['reason']}")
        if card.get("caution"):
            print(f"    提醒：{card['caution']}")
        if card.get("matched_rules"):
            print(f"    命中规则：{' / '.join(card['matched_rules'])}")
        print()

    if payload.get("avoid"):
        print("避雷：")
        for tip in payload["avoid"]:
            print(f"  - {tip}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    features = features_from_args(args)
    try:
        payload = recommend(features, free_text=args.free_text, use_llm=args.llm)
    except (ContractError, NailFitError) as exc:
        print(f"✗ 推荐失败：{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        render(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
