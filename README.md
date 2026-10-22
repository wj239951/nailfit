# NailFit — Hand-aware nail style recommendation

> 甲适 · 基于手部特征的美甲推荐
>
> 从手部照片提取甲型 / 甲长 / 肤色特征 → 规则引擎筛选 → 款式库检索 → 三档推荐 + 可解释理由

**核心立场：推荐结果只从款式库中挑选，不做生成式试戴。** 每一张推荐图都对应款式库中的真实条目，可溯源、可评测。

---

## 为什么不让大模型自由推荐

| 做法 | 结果 |
|---|---|
| 把 200 条款式和 20 条规则全塞进 prompt | 模型漏规则、无法单测、token 爆炸 |
| 让 VLM 看图后自由发挥 | "建议你试试奶茶色" ——正确但无用，且不可复现 |
| **规则决定推荐什么，模型只决定怎么说** | 可解释、可配置、可评测 |

---

## 架构

```
手照 ──► 特征提取 (MediaPipe + 规则 / Lab 色彩)
           │
           ▼
        HandFeatures {甲床比例, 甲型, 甲长, ITA°, 冷暖, 手型, 场景}
           │
           ├──► RuleEngine  硬过滤(排除不可行) + 加权打分
           ├──► 语义加权(可选, bge-m3)
           ▼
        Selector  三档(稳妥/亮点/大胆) + 色相去重
           │
           ▼
        Explainer  只生成理由与避雷(不产图)
           │
           ▼
        Validator  style_id 必须存在 + 三档不重复
```

## 目录

```
nailfit/
├── data/
│   ├── taxonomy.yaml        # 特征枚举 + 打分权重 + 多样性约束
│   ├── rules.yaml           # 匹配规则（改规则不改代码）
│   └── styles.sample.json   # 款式库样例（10 条，替换成真实款式）
├── core/
│   ├── data.py              # YAML / JSON 加载
│   ├── features.py          # HandFeatures 数据契约 + 校验
│   ├── color.py             # sRGB → Lab → ITA°（肤色量化）
│   ├── landmarks.py         # 21 关键点 → 几何特征（启发式）
│   ├── rules.py             # 规则引擎：when / prefer / block
│   ├── selector.py          # 排序 + 三档 + 多样性
│   ├── retriever.py         # 可选语义加权（bge-m3）
│   ├── explainer.py         # LLM 生成理由（无 key 时模板降级）
│   └── validator.py         # 输出契约校验
├── api/
│   ├── main.py              # FastAPI 入口
│   ├── routes.py            # /api/recommend /api/styles
│   └── schemas.py           # 请求/响应模型
├── scripts/
│   └── demo.py              # 命令行跑通全链路（无需起服务）
├── tests/                   # pytest：规则 / 选择 / 校验
├── static/styles/           # 款式图片（按 style id 命名）
└── docs/design.md           # 设计说明
```

## 快速开始

```bash
# 1. 环境（建议 Python 3.11，mediapipe 暂不支持过新的版本）
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# 可选：视觉层（mediapipe，需要 Python 3.11/3.12）
# pip install -r requirements-vision.txt

# 2. 命令行跑通（不需要启动服务、不需要 API Key）
python scripts/demo.py

# 3. 跑测试
pytest -q

# 4. 启动 API
uvicorn api.main:app --reload --port 8000
# Swagger: http://127.0.0.1:8000/docs
```

## API

### `POST /api/recommend`

```json
{
  "features": {
    "nail_bed_ratio": "short_wide",
    "length": "short",
    "ita_band": "light",
    "warmth": "warm",
    "hand_type": "fleshy",
    "scene": "commute"
  },
  "free_text": "想要温柔一点、显白",
  "use_llm": true
}
```

返回三张推荐卡（含 `matched_rules` 与 `reason`）、以及 `avoid` 避雷提示。

### `GET /api/styles`
款式库列表（用于前端展示与调试）。

## 数据契约

`styles.sample.json` 每条款式：

| 字段 | 说明 |
|---|---|
| `id` | 唯一 ID，与图片文件名一致 |
| `shape` | 推荐甲型列表（杏仁/椭圆/方圆形…） |
| `color_family` / `tone` / `value` / `saturation` | 色彩属性 |
| `style` | 款式（纯色/法式/渐变/猫眼/手绘…） |
| `length_fit` | 该款式所需的最短甲长 |
| `nail_bed_fit` | 适配的甲床类型 |
| `scene` | 适用场景 |
| `hue` | 色相角（0–360），用于三档去重 |
| `tags` | 自由标签（显白/通勤/温柔…） |

## 评测（TODO）

- 30 张真实手照 → 人工判断「3 个推荐里至少 1 个合理」的比例
- 多样性：3 个推荐是否出现同色系 / 同款式
- 理由准确性：`matched_rules` 是否真的对应推荐结果

## 图片来源

> 模板交付时请替换为可商用图片，并在页面标注「风格参考，非本手模拟效果」。

## License

MIT
