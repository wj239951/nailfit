"""解释层：只生成"为什么推荐"和"避雷"，不产图、不改推荐结果。

两种模式：
- LLM 模式：有 DEEPSEEK_API_KEY 时调用云端（OpenAI 兼容协议）；
- 模板模式：无 key 或调用失败时，用命中规则的 reason 拼装，保证离线可跑。

无论哪种模式，输出都必须通过 validator 校验（style_id 真实存在、三条不重复）。
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .features import HandFeatures
from .selector import Scored

SYSTEM_PROMPT = """你是一名有十年经验的美甲师，正在为客人做款式推荐。
规则：
1. 只能推荐给定的候选款式，不得编造款式名、颜色或品牌。
2. 每个款式给出 1-2 句中文理由，说明它为什么适合这位客人的甲型、甲长、肤色或场景。
3. 理由要具体，不要空话（禁止"很好看""很时尚"这类无信息表达）。
4. 如果该款式有明显限制（例如需要更长甲床），写一句提醒。
5. 只输出 JSON，不要 Markdown 代码块。"""

OUTPUT_SCHEMA = {
    "recommendations": [
        {"style_id": "string", "reason": "string", "caution": "string or null"}
    ],
    "avoid": ["string"],
}


def _feature_summary(features: HandFeatures) -> str:
    mapping = {
        "nail_bed_ratio": {"short_wide": "甲床偏短宽", "standard": "甲床比例标准", "slender": "甲床偏细长"},
        "length": {"very_short": "甲长极短", "short": "短甲", "mid": "中等甲长", "long": "长甲"},
        "ita_band": {"light": "肤色偏浅", "mid": "肤色中等", "deep": "肤色偏深"},
        "warmth": {"cool": "冷调", "neutral": "中性调", "warm": "暖调"},
        "hand_type": {"slim": "手指纤细", "standard": "手型标准", "fleshy": "手型偏肉感"},
        "scene": {
            "commute": "通勤场景", "date": "约会场景", "wedding": "婚礼场景",
            "festival": "节日场景", "cool": "酷感风格", "y2k": "Y2K 风格",
        },
    }
    parts = []
    for key, labels in mapping.items():
        value = getattr(features, key)
        parts.append(labels.get(value, value))
    return "，".join(parts)


def build_messages(
    features: HandFeatures,
    picks: list[Scored],
    avoided: list[dict],
    free_text: str | None = None,
) -> list[dict[str, str]]:
    candidates = [
        {
            "style_id": p.style["id"],
            "name": p.style.get("name"),
            "color": p.style.get("color_family"),
            "style": p.style.get("style"),
            "shape": p.style.get("shape"),
            "length_fit": p.style.get("length_fit"),
            "matched_reasons": list(p.reasons[:3]),
        }
        for p in picks
    ]
    user = {
        "guest": _feature_summary(features),
        "free_text": free_text,
        "candidates": candidates,
        "must_avoid": [a["reason"] for a in avoided[:3]],
        "output_schema": OUTPUT_SCHEMA,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def _call_llm(
    messages: list[dict[str, str]],
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout: float,
) -> dict[str, Any]:
    resp = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def _template(
    features: HandFeatures, picks: list[Scored], avoided: list[dict]
) -> dict[str, Any]:
    recs = {}
    for pick in picks:
        reasons = list(pick.reasons[:2])
        reason = "；".join(reasons) if reasons else "与你的甲型、甲长和肤色匹配，日常不挑场合"
        caution = None
        if features.length in {"very_short", "short"} and pick.style.get("length_fit") in {"mid", "long"}:
            caution = "这个款式最好留长一点再做，效果更完整"
        recs[pick.style["id"]] = {"reason": reason + "。", "caution": caution}
    avoid: list[str] = []
    seen: set[str] = set()
    for item in avoided:
        text = f"「{item.get('name', item['style_id'])}」{item['reason']}"
        key = item["reason"]
        if key in seen:
            continue
        seen.add(key)
        avoid.append(text)
        if len(avoid) >= 2:
            break
    if features.length == "very_short":
        avoid.append("甲长偏短时，手绘与贴钻容易显得拥挤，建议先养甲")
    return {"recommendations": recs, "avoid": avoid}


def explain(
    features: HandFeatures,
    picks: list[Scored],
    avoided: list[dict],
    *,
    use_llm: bool = True,
    free_text: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """返回 {"recommendations": {id: {reason, caution}}, "avoid": [...]}"""
    api_key = api_key if api_key is not None else os.getenv("DEEPSEEK_API_KEY", "")
    base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    if use_llm and api_key:
        try:
            data = _call_llm(
                build_messages(features, picks, avoided, free_text),
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout=timeout,
            )
            if isinstance(data.get("recommendations"), list) and data["recommendations"]:
                return {
                    "recommendations": {
                        str(item["style_id"]): {
                            "reason": str(item.get("reason", "")).strip(),
                            "caution": item.get("caution"),
                        }
                        for item in data["recommendations"]
                        if item.get("style_id")
                    },
                    "avoid": [str(x) for x in data.get("avoid", [])],
                }
        except Exception:  # noqa: BLE001 - 降级到模板，保证可用
            pass

    return _template(features, picks, avoided)
