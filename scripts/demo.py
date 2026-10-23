"""命令行跑通全链路：不需要启动服务、不需要任何 API Key。

    python scripts/demo.py                 # 默认场景，模板生成理由
    python scripts/demo.py --scenario deep_festival
    python scripts/demo.py --llm           # 有 DEEPSEEK_API_KEY 时走云端
    python scripts/demo.py --json          # 输出原始 JSON

出错时打印一行清晰的中文原因并以退出码 2 结束（不打印 traceback）。
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
from core.features import FeatureError, HandFeatures  # noqa: E402
from core.pipeline import recommend  # noqa: E402
from core.validator import ContractError  # noqa: E402

SCENARIOS: dict[str, dict] = {
    "short_wide_warm": {
        "nail_bed_ratio": "short_wide",
        "nail_shape": "oval",
        "length": "short",
        "ita_band": "light",
        "warmth": "warm",
        "hand_type": "fleshy",
        "scene": "commute",
        "ita_degrees": 48.2,
    },
    "slender_cool": {
        "nail_bed_ratio": "slender",
        "nail_shape": "almond",
        "length": "mid",
        "ita_band": "light",
        "warmth": "cool",
        "hand_type": "slim",
        "scene": "date",
        "ita_degrees": 52.0,
    },
    "deep_festival": {
        "nail_bed_ratio": "standard",
        "nail_shape": "squoval",
        "length": "short",
        "ita_band": "deep",
        "warmth": "warm",
        "hand_type": "standard",
        "scene": "festival",
        "ita_degrees": 5.4,
    },
    "long_y2k": {
        "nail_bed_ratio": "standard",
        "nail_shape": "square",
        "length": "long",
        "ita_band": "mid",
        "warmth": "neutral",
        "hand_type": "standard",
        "scene": "y2k",
        "ita_degrees": 30.0,
    },
}


def _print_human(payload: dict) -> None:
    features = payload["features"]
    print("=" * 62)
    print("NailFit · 推荐结果")
    print("=" * 62)
    print(
        "特征：甲床={nail_bed_ratio}  甲长={length}  肤色={ita_band}/{warmth}  "
        "手型={hand_type}  场景={scene}".format(**features)
    )
    print(f"候选池：{payload['meta']['candidates_considered']} 款可用，"
          f"{payload['meta']['excluded']} 款被规则排除\n")
    for idx, card in enumerate(payload["recommendations"], start=1):
        print(f"[{idx}] {card['name']}  （{card['tier']} 档，匹配度 {card['match_score']:.2f}）")
        print(f"    图：{card['image']}")
        print(f"    理由：{card['reason']}")
        if card.get("caution"):
            print(f"    提醒：{card['caution']}")
        if card.get("matched_rules"):
            print(f"    命中规则：{' / '.join(card['matched_rules'][:3])}")
        print()
    if payload.get("avoid"):
        print("避雷：")
        for tip in payload["avoid"]:
            print(f"  - {tip}")


def main() -> int:
    parser = argparse.ArgumentParser(description="NailFit 命令行 demo")
    parser.add_argument("--scenario", default="short_wide_warm", choices=sorted(SCENARIOS))
    parser.add_argument("--llm", action="store_true", help="有 DEEPSEEK_API_KEY 时调用云端生成理由")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = parser.parse_args()

    try:
        features = HandFeatures.from_dict(SCENARIOS[args.scenario])
        payload = recommend(features, use_llm=args.llm)
    except (FeatureError, ContractError, NailFitError) as exc:
        print(f"✗ 推荐失败：{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
