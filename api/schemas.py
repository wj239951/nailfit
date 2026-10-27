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
    library: str = Field(
        default="sample",
        description="款式库：sample（15 款样例）/ demo（43 款演示库）",
        examples=["sample", "demo"],
    )


class ReferenceImage(BaseModel):
    """网络参考图（M32）：CC 授权、预取缓存，展示在推荐卡下方。"""

    image: str = Field(description="static/ 下的本地路径")
    title: str | None = None
    author: str | None = None
    license: str = Field(description="cc0 / pdm / by / by-sa")
    license_label: str | None = None
    source_url: str | None = Field(default=None, description="原始页面（授权/作者出处）")
    provider: str = "openverse"


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
    media: dict[str, Any] | None = Field(
        default=None,
        description="参考图与来源（image/source_url/license/provider/relevance），失败时为占位",
    )
    references: list[ReferenceImage] = Field(
        default_factory=list,
        description="网络参考图（CC 授权，M32；无预取清单时为空列表）",
    )


class RecommendResponse(BaseModel):
    features: dict[str, Any]
    recommendations: list[StyleCard]
    avoid: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class VisionExtractRequest(BaseModel):
    image_path: str = Field(..., description="本地手照路径（演示用；正式环境应改成上传接口）")
    scene: str = Field(default="commute", description="场景，手照推断不出来，由前端传入")
    overrides: dict[str, str] = Field(
        default_factory=dict, description="人工修正的特征，优先级高于视觉结果（M11 回退）"
    )
    auto_download: bool = Field(default=False, description="模型缺失时是否自动下载（约 8MB）")


class VisionExtractResponse(BaseModel):
    features: dict[str, Any] = Field(description="识别出的特征（可能缺项，见 unreliable）")
    quality: str = Field(description="ok / clenched / pose / low")
    handedness: str = ""
    handedness_score: float = 0.0
    gesture: str = ""
    gesture_score: float = 0.0
    confidences: dict[str, float] = Field(default_factory=dict)
    unreliable: list[str] = Field(default_factory=list, description="不可靠/缺失的特征字段")
    notes: list[str] = Field(default_factory=list)
    ita_degrees: float = 0.0
    metrics: dict[str, Any] = Field(default_factory=dict)
    preview: str | None = None


class RecommendFromImageRequest(VisionExtractRequest):
    free_text: str | None = Field(default=None, description="用户自由描述")
    use_llm: bool = Field(default=False, description="是否用大模型生成理由")


class RecommendFromImageResponse(RecommendResponse):
    vision: dict[str, Any] = Field(default_factory=dict, description="视觉层元信息（质量/置信度）")
