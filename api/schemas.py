from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RecommendRequest(BaseModel):
    features: dict[str, Any] = Field(
        default_factory=dict,
        description="手部特征，字段见 data/taxonomy.yaml → features",
        examples=[
            {
                "nail_bed_ratio": "short_wide",
                "length": "short",
                "ita_band": "light",
                "warmth": "warm",
                "hand_type": "fleshy",
                "scene": "commute",
            }
        ],
    )
    free_text: str | None = Field(default=None, description="用户自由描述，如「想要温柔显白」")
    use_llm: bool = Field(default=True, description="是否有 DEEPSEEK_API_KEY 时调用云端生成理由")


class StyleCard(BaseModel):
    style_id: str
    name: str | None = None
    image: str | None = None
    color_family: str | None = None
    style: str | None = None
    shape: list[str] | None = None
    length_fit: str | None = None
    tier: str | None = None
    match_score: float = 0.0
    matched_rules: list[str] = Field(default_factory=list, description="命中的规则 id")
    matched_reasons: list[str] = Field(default_factory=list, description="命中规则的可读原因")
    reason: str = ""
    caution: str | None = None


class RecommendResponse(BaseModel):
    features: dict[str, Any]
    recommendations: list[StyleCard]
    avoid: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
