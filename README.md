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
│   └── styles.sample.json   # 款式库样例（13 条，替换成真实款式）
├── core/
│   ├── data.py              # YAML / JSON 加载（文件缺失/损坏时报清晰错误）
│   ├── errors.py            # 统一异常：数据缺失 / 候选不足 / 契约失败
│   ├── features.py          # HandFeatures 数据契约 + 校验
│   ├── color.py             # sRGB → Lab → ITA°（肤色量化）
│   ├── landmarks.py         # 21 关键点 → 几何特征（启发式）
│   ├── rules.py             # 规则引擎：when / prefer / block
│   ├── selector.py          # 排序 + 三档 + 多样性
│   ├── styles.py            # 款式库校验（字段 / 枚举 / 唯一性 / 图片）
│   ├── labels.py            # 中文标签（特征名 / 甲型 / 场景）
│   ├── retriever.py         # 可选语义加权（bge-m3）
│   ├── explainer.py         # LLM 生成理由（无 key 时模板降级）
│   └── validator.py         # 输出契约校验
├── api/
│   ├── main.py              # FastAPI 入口
│   ├── routes.py            # /api/recommend /api/styles
│   └── schemas.py           # 请求/响应模型
├── scripts/
│   ├── demo.py              # 命令行跑通全链路（无需起服务）
│   ├── manual.py            # 手工录入 7 项手部特征 → 三张推荐卡
│   ├── validate_styles.py   # 款式库数据校验
│   └── prepare_images.py    # 款式图批量裁切 / 缩放 / 压缩（≤300KB）
├── tests/                   # pytest：规则 / 选择 / 校验 / 手工录入 / 款式库 / 图片处理
├── static/styles/           # 款式图片（按 style id 命名）
├── static/demo/             # 演示图片（不入库、不进 git，仅工程演示）
└── docs/
    ├── design.md            # 设计说明
    ├── IMAGE_GUIDE.md       # 图片来源、选图标准与入库流程
    └── ROADMAP.md           # 剩余任务清单（M1–M23）
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

---

## 演示：手工录入版（还不接视觉时怎么跑）

手照提取还没做，先用 7 项手工填写的特征跑完整推荐链路：

```bash
# 交互式录入：逐项选择，回车取默认值
python scripts/manual.py

# 直接给参数：一条命令出三张卡
python scripts/manual.py --bed short_wide --length short --ita light --warmth warm --hand fleshy --scene commute

# 场景预设：short_wide_warm / slender_cool / deep_festival / long_y2k
python scripts/manual.py --scenario deep_festival

# JSON 输出（接前端 / 评测脚本）
python scripts/manual.py --yes --json
```

输出示例：

```
==============================================================
NailFit · 推荐结果
==============================================================
特征：甲床偏短宽、椭圆、短甲、肤色偏浅、暖调、手型偏肉感、通勤
候选池：4 款可用 / 9 款被排除

[1] 奶茶裸粉 · 细法式  （safe 档，匹配度 0.92）
    图：static/styles/s001.jpg
    理由：甲床偏短宽，杏仁或椭圆甲型能拉长视觉比例；短甲优先选短甲友好款式，手绘与贴钻需要留长。
    命中规则：bed_short_wide / length_short / skin_light_warm

[2] 短甲猫眼 · 浆果  （highlight 档，匹配度 0.64）
    ...

避雷：
  - 「浆果紫 · 猫眼」该款式需要 mid 甲长，与当前甲长不匹配
```

参数说明：

| 参数 | 取值 | 说明 |
|---|---|---|
| `--bed` | `short_wide` / `standard` / `slender` | 甲床比例 |
| `--shape` | `round` / `square` / `oval` / `almond` / `squoval` | 当前甲型 |
| `--length` | `very_short` / `short` / `mid` / `long` | 当前甲长 |
| `--ita` | `light` / `mid` / `deep` | 肤色深浅 |
| `--warmth` | `warm` / `neutral` / `cool` | 肤色冷暖 |
| `--hand` | `slim` / `standard` / `fleshy` | 手型 |
| `--scene` | `commute` / `date` / `wedding` / `festival` / `cool` / `y2k` | 场景 |

其他参数：`--free-text "想要温柔显白"`（自由描述，参与语义加权）、`--llm`（有 Key 时用云端生成理由）、`--json`（机器可读）、`--interactive`（强制逐项填写）、`--yes`（用默认值，不反问）。

## 款式库校验

给 `data/styles.json` 打标前/后都跑一遍，避免脏数据进推荐链路：

```bash
# 字段完整性 + 枚举合法性 + id 唯一性
python scripts/validate_styles.py

# 额外检查图片是否存在（打图阶段用）
python scripts/validate_styles.py --check-images

# 校验真实款式库（默认读 data/styles.sample.json）
python scripts/validate_styles.py --styles data/styles.json
```

---

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
款式库列表（用于前端展示与调试）。库为空或数据损坏时返回 `503`。

## 错误处理

所有失败路径都返回**一行能看懂的中文原因**，不用翻 traceback：

| 场景 | CLI 表现 | API 表现 |
|---|---|---|
| 特征值非法（如 `length=eternal`） | `特征非法：...`，退出码 1 | `422`，`detail` 说明哪个字段不合法 |
| 款式库文件缺失 / JSON 损坏 | `✗ 推荐失败：...`，退出码 2 | `503`，`款式库不可用: ...` |
| 款式库为空（`styles: []`） | 同上 | `503`，`款式库不可用: ...` |
| 规则过滤后无候选 | `✗ 推荐失败：没有通过硬性过滤的款式...` | `422`，`无法生成推荐: ...` |
| 过滤后不足 3 款（凑不齐三档） | 同上 | `422`，`过滤后只剩 N 款，至少需要 3 款` |
| 输出契约失败（模型编了不存在的款式） | `✗ 推荐失败：...` | `502`，`推荐结果校验失败: ...` |

自测这些边界（不需要真实数据）：

```bash
python scripts/demo.py                            # 正常路径
python scripts/validate_styles.py --check-images  # 数据完整性
pytest -q tests/test_edge_cases.py -v             # 14 个边界用例
```

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

正式款式库优先用**自拍 / 可商用图库**（Pexels、Unsplash 等）；小红书等平台截图只作本地演示参考，版权归原作者。
完整规范（授权优先级、选图标准、裁剪压缩、免责声明）见 [docs/IMAGE_GUIDE.md](docs/IMAGE_GUIDE.md)。

另有 43 张处理好的**演示图**在 `static/demo/`（来源为平台截图，仅工程演示：README 截图 / 前端占位 / 面试示意；**不登记进款式库、不进 git**）。映射表与逐张处理命令见 IMAGE_GUIDE 第 6 节。

处理命令：

```bash
# 原图放 raw_images/ → 自动裁 3:4、压到 ≤300KB → 输出 static/styles/
python scripts/prepare_images.py --src raw_images --out static/styles --prefix s --start 14

# 截图类：先用 --box 框掉状态栏/评论区；宽图用 --fit pad 补边
python scripts/prepare_images.py --src raw_images/0816.jpg --out static/styles/s014.jpg --box 0,400,1206,2008

# 校验图片是否齐
python scripts/validate_styles.py --check-images
```

> 页面需标注：**「风格参考，非本手模拟效果」**。若使用公开平台图片，请同时注明来源与非商用声明，并准备随时替换。

## License

MIT
