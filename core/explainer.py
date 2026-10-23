"""解释层：只生成"为什么推荐"和"避雷"，不产图、不改推荐结果。

两种模式：
- LLM 模式：配置了 DEEPSEEK_API_KEY 时调用云端（OpenAI 兼容协议）；
- 模板模式：无 key、未开启或调用失败时，用命中规则的 reason 拼装，保证离线可跑。

LLM 输出会先清洗再校验：style_id 必须来自候选、reason 非空且不超过
`validator.MAX_REASON_CHARS`、avoid 数量/长度受限；不满足的条目自动回退到模板，
并在 `meta.explainer` 里标注 mode / degraded / error，前端可以显示"理由来源"。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from .features import HandFeatures
from .selector import Scored
from .validator import MAX_REASON_CHARS

SYSTEM_PROMPT = """你是一名有十年经验的美甲师，正在为客人做款式推荐。
规则：
1. 只能推荐给定的候选款式；style_id 必须逐字来自候选列表，不得编造款式、颜色或品牌。
2. 每个款式给出 1-2 句中文理由（不超过 160 字），说明它为什么适合这位客人的甲型、甲长、肤色或场景。
3. 理由要具体，不要空话（禁止"很好看""很时尚"这类无信息表达），不要使用 Markdown、代码块或引号包裹。
4. 如果该款式有明显限制（例如需要更长甲床才能做出效果），把提醒写进 caution；没有就写 null。
5. avoid 最多 2 条，每条不超过 60 字，写成给客人的避雷建议。
6. 只输出 JSON 对象，不要任何解释文字。格式：
{"recommendations": [{"style_id": "s001", "reason": "……", "caution": null}], "avoid": ["……"]}"""

OUTPUT_SCHEMA = {
    "recommendations": [
        {"style_id": "string", "reason": "string", "caution": "string or null"}
    ],
    "avoid": ["string"],
}

MAX_AVOID_ITEMS = 2
MAX_AVOID_CHARS = 60
MAX_ERROR_CHARS = 200

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


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
        "constraints": {
            "max_reason_chars": MAX_REASON_CHARS,
            "max_avoid_items": MAX_AVOID_ITEMS,
            "max_avoid_chars": MAX_AVOID_CHARS,
        },
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
    """调用 OpenAI 兼容接口；部分服务（如 Ollama）不支持 response_format，自动重试一次。"""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code in {400, 422}:
            payload.pop("response_format", None)
            resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()
        else:
            raise
    content = resp.json()["choices"][0]["message"]["content"]
    return _parse_json_object(content)


def _parse_json_object(content: Any) -> dict[str, Any]:
    """容错解析：推理模型可能先输出思考过程再给 JSON，从文本里截取第一个 JSON 对象。"""
    text = "" if content is None else str(content)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    text = re.sub(r"<think[^>]*>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(text[start : end + 1])
        if isinstance(data, dict):
            return data
    raise json.JSONDecodeError("模型没有返回 JSON 对象", text, 0)


# --------------------------------------------------------------------------- 清洗与降级
def _clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = _FENCE_RE.sub("", text.strip())
    text = text.replace("`", "").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _clamp_reason(text: Any) -> str:
    reason = _clean_text(text)
    if len(reason) <= MAX_REASON_CHARS:
        return reason
    head = reason[: MAX_REASON_CHARS - 2]
    cut = max(head.rfind("。"), head.rfind("；"))
    if cut >= 60:
        return head[: cut + 1]
    return head + "…"


def _sanitize(data: Any, style_ids: set[str]) -> tuple[dict[str, dict], list[str]]:
    """只保留候选里真实存在的 style_id；reason 清洗+截断；avoid 限量。"""
    recs: dict[str, dict] = {}
    if not isinstance(data, dict):
        return recs, []
    items = data.get("recommendations")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("style_id", "")).strip()
            if sid not in style_ids or sid in recs:
                continue
            reason = _clamp_reason(item.get("reason"))
            if not reason:
                continue
            caution = _clean_text(item.get("caution")) or None
            if caution and len(caution) > MAX_AVOID_CHARS:
                caution = caution[: MAX_AVOID_CHARS - 1] + "…"
            recs[sid] = {"reason": reason, "caution": caution}

    avoid: list[str] = []
    raw_avoid = data.get("avoid")
    if isinstance(raw_avoid, list):
        for item in raw_avoid:
            text = _clean_text(item)
            if not text or text in avoid:
                continue
            avoid.append(text[:MAX_AVOID_CHARS])
            if len(avoid) >= MAX_AVOID_ITEMS:
                break
    return recs, avoid


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
    if features.length == "very_short" and len(avoid) < MAX_AVOID_ITEMS:
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
    """返回 {"recommendations": {id: {reason, caution}}, "avoid": [...], "meta": {...}}。

    meta.explainer: {mode, model, degraded, llm_cards, error}
    - mode: "llm"（至少一条理由来自模型）或 "template"
    - degraded: 是否发生了降级（含“要 LLM 但没 key”与“部分条目回退模板”）
    """
    api_key = api_key if api_key is not None else os.getenv("DEEPSEEK_API_KEY", "")
    base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    style_ids = {p.style["id"] for p in picks}
    template = _template(features, picks, avoided)

    def _meta(mode: str, *, degraded: bool, llm_cards: int, error: str | None) -> dict:
        return {
            "mode": mode,
            "model": model,
            "degraded": degraded,
            "llm_cards": llm_cards,
            "error": error,
        }

    if not use_llm:
        return {
            "recommendations": template["recommendations"],
            "avoid": template["avoid"],
            "meta": _meta("template", degraded=False, llm_cards=0, error=None),
        }

    if not api_key:
        return {
            "recommendations": template["recommendations"],
            "avoid": template["avoid"],
            "meta": _meta(
                "template",
                degraded=True,
                llm_cards=0,
                error="未配置 DEEPSEEK_API_KEY，已降级为模板理由",
            ),
        }

    messages = build_messages(features, picks, avoided, free_text)
    llm_recs: dict[str, dict] = {}
    llm_avoid: list[str] = []
    calls = 0
    try:
        # 最多调用 2 次：第一次不齐/不合法时，把缺失的 style_id 反馈给模型再补一次
        while calls < 2 and len(llm_recs) < len(style_ids):
            data = _call_llm(
                messages,
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout=timeout,
            )
            calls += 1
            recs, avoid = _sanitize(data, style_ids)
            for sid, item in recs.items():
                llm_recs.setdefault(sid, item)
            if avoid and not llm_avoid:
                llm_avoid = avoid
            if len(llm_recs) < len(style_ids) and calls < 2:
                missing = sorted(style_ids - set(llm_recs))
                messages = messages + [
                    {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)},
                    {
                        "role": "user",
                        "content": (
                            f"上一次输出缺少或不合法的 style_id：{', '.join(missing)}。"
                            f"请只输出 JSON 对象，必须包含全部候选 style_id：{', '.join(sorted(style_ids))}。"
                        ),
                    },
                ]
    except Exception as exc:  # noqa: BLE001 - 任何异常都降级，保证推荐可用
        message = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]
        if llm_recs:  # 第二次失败时，保留第一次已通过校验的部分
            merged = {
                sid: llm_recs.get(sid) or template["recommendations"][sid]
                for sid in style_ids
            }
            return {
                "recommendations": merged,
                "avoid": llm_avoid or template["avoid"],
                "meta": _meta("llm", degraded=True, llm_cards=len(llm_recs), error=message),
            }
        return {
            "recommendations": template["recommendations"],
            "avoid": template["avoid"],
            "meta": _meta("template", degraded=True, llm_cards=0, error=message),
        }

    merged = {
        sid: llm_recs.get(sid) or template["recommendations"][sid]
        for sid in style_ids
    }
    llm_cards = len(llm_recs)
    mode = "llm" if llm_cards else "template"
    degraded = llm_cards < len(style_ids)
    error = None
    if degraded:
        error = (
            "部分推荐理由未通过校验，已回退模板"
            if llm_cards
            else "模型未返回可用的推荐理由，已回退模板"
        )
    return {
        "recommendations": merged,
        "avoid": llm_avoid or template["avoid"],
        "meta": _meta(mode, degraded=degraded, llm_cards=llm_cards, error=error),
    }
