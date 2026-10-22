"""可选的语义加权：用户自由描述（"想要温柔显白"）与款式描述的相似度。

默认关闭（USE_SEMANTIC=false）。Ollama 未启动、模型未拉取或网络异常时
**静默降级为 0 分**——规则分永远是主排序依据，语义分只是锦上添花。
"""

from __future__ import annotations

import math

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "bge-m3"


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def style_text(style: dict) -> str:
    parts = [
        style.get("name", ""),
        style.get("color_family", ""),
        style.get("style", ""),
    ]
    parts += [str(t) for t in style.get("tags", [])]
    return " ".join(p for p in parts if p)


class SemanticScorer:
    def __init__(
        self,
        *,
        enabled: bool = False,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 5.0,
    ):
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _embed(self, texts: list[str]) -> list[list[float]]:
        resp = httpx.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": texts},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]

    def score(self, query: str | None, styles: list[dict]) -> dict[str, float]:
        """返回 style_id → 0~1 相似度；任何异常都返回空字典（降级）。"""
        if not self.enabled or not query or not styles:
            return {}
        try:
            vectors = self._embed([query] + [style_text(s) for s in styles])
        except Exception:  # noqa: BLE001 - 显式降级
            return {}

        query_vec, style_vecs = vectors[0], vectors[1:]
        raw = {s["id"]: max(0.0, _cosine(query_vec, vec)) for s, vec in zip(styles, style_vecs)}
        if not raw:
            return {}
        low, high = min(raw.values()), max(raw.values())
        if high - low < 1e-6:
            return {k: 0.5 for k in raw}
        return {k: (v - low) / (high - low) for k, v in raw.items()}
