"""M17 自检：验证大模型解释链路是否可用（推荐结果固定来自规则引擎）。

用法：
    python scripts/check_llm.py                  # 读 .env / 环境变量，调用 DeepSeek 云端
    python scripts/check_llm.py --json           # 输出完整 payload
    # 也可以拿本地 Ollama 做联调（OpenAI 兼容端点）：
    python scripts/check_llm.py --base-url http://127.0.0.1:11434/v1 --model deepseek-r1:7b

退出码：0 = 大模型 3/3 条理由都通过清洗与契约校验；1 = 降级（会打印原因）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # 方便本地 .env（缺依赖不影响）
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # noqa: BLE001
    pass

from core.features import HandFeatures  # noqa: E402
from core.presets import SCENARIOS  # noqa: E402
from core.pipeline import recommend  # noqa: E402


def _mask(key: str) -> str:
    if not key:
        return "（未配置）"
    return key[:6] + "…" + key[-4:] if len(key) > 12 else "***"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NailFit 解释层自检（M17）")
    parser.add_argument("--scenario", default="short_wide_warm", choices=sorted(SCENARIOS))
    parser.add_argument("--base-url", default=None, help="覆盖 DEEPSEEK_BASE_URL（可指向 Ollama /v1）")
    parser.add_argument("--model", default=None, help="覆盖 DEEPSEEK_MODEL")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--api-key", default=None, help="覆盖 DEEPSEEK_API_KEY（本地 Ollama 可用任意占位值）")
    parser.add_argument("--json", action="store_true", help="输出完整推荐 payload")
    args = parser.parse_args(argv)

    base_url = args.base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = args.model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    key = args.api_key if args.api_key is not None else os.getenv("DEEPSEEK_API_KEY", "")
    if not key and ("127.0.0.1" in base_url or "localhost" in base_url):
        key = "local-ollama"
        print("提示：本地端点未配 Key，使用占位 Key 调用（Ollama 不校验）")

    explainer_kwargs: dict = {"timeout": args.timeout, "api_key": key}
    if args.base_url:
        explainer_kwargs["base_url"] = args.base_url
    if args.model:
        explainer_kwargs["model"] = args.model

    features = HandFeatures.from_dict(SCENARIOS[args.scenario])
    try:
        payload = recommend(features, use_llm=True, explainer_kwargs=explainer_kwargs)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 推荐失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        meta = payload["meta"]["explainer"]
        print("=" * 62)
        print("NailFit · 解释层自检（M17）")
        print("=" * 62)
        print(f"接入点：{base_url}    模型：{model}    Key：{_mask(key)}")
        print(f"模式：{meta['mode']}    降级：{'是' if meta['degraded'] else '否'}    "
              f"模型理由：{meta.get('llm_cards', 0)}/3 条")
        if meta.get("error"):
            print(f"降级原因：{meta['error']}")
        print()
        for idx, card in enumerate(payload["recommendations"], start=1):
            print(f"[{idx}] {card['name']}（{card['style_id']}）")
            print(f"    理由：{card['reason']}")
            if card.get("caution"):
                print(f"    提醒：{card['caution']}")
        print()
        if payload.get("avoid"):
            print("避雷：")
            for tip in payload["avoid"]:
                print(f"  - {tip}")

    ok = payload["meta"]["explainer"]["mode"] == "llm" and not payload["meta"]["explainer"]["degraded"]
    print("\n" + ("✓ 解释层可用：3 条理由均由大模型生成且通过校验" if ok else "! 已降级为模板理由（见上方原因）"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
