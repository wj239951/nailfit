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
│   ├── styles.sample.json   # 款式库样例（13 条，替换成真实款式）
│   └── styles.demo.json     # 演示款式库（43 条，autotag 自动生成，仅演示）
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
│   ├── validator.py         # 输出契约校验
│   └── vision.py            # 手照 → MediaPipe 关键点 → 手部特征（M8，可选依赖）
├── api/
│   ├── main.py              # FastAPI 入口
│   ├── routes.py            # /api/recommend /api/styles
│   └── schemas.py           # 请求/响应模型
├── app/
│   └── streamlit_app.py     # Streamlit 网页前端（可选依赖，见 requirements-frontend.txt）
├── scripts/
│   ├── demo.py              # 命令行跑通全链路（无需起服务）
│   ├── manual.py            # 手工录入 7 项手部特征 → 三张推荐卡
│   ├── validate_styles.py   # 款式库数据校验
│   ├── prepare_images.py    # 款式图批量裁切 / 缩放 / 压缩（≤300KB）
│   ├── vision_demo.py       # 手照 → 手部特征（M8，需 mediapipe）
│   └── autotag.py           # 图片 → 结构化款式标签，生成演示款式库
├── tests/                   # pytest：规则 / 选择 / 校验 / 手工录入 / 款式库 / 图片处理 / 视觉层
├── models/                  # MediaPipe 模型缓存（gitignore，首次使用时自动下载）
├── raw_hands/               # 本地手照素材（gitignore）
├── static/styles/           # 款式图片（按 style id 命名）
├── static/demo/             # 演示图片（不入库、不进 git，仅工程演示）
├── static/preview/          # 视觉层关键点标注图（gitignore）
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

# 2.1 用 43 条款式库跑（M7 演示库，图片对应 static/demo/）
python scripts/demo.py --styles data/styles.demo.json --scenario slender_cool

# 3. 跑测试
pytest -q

# 4. 启动 API
uvicorn api.main:app --reload --port 8000
# Swagger: http://127.0.0.1:8000/docs

# 5. 网页前端（可选，Streamlit）
pip install -r requirements-frontend.txt
streamlit run app/streamlit_app.py
# 浏览器打开 http://localhost:8501

# 6. 手照识别（可选，需要 requirements-vision.txt；模型会在首次使用时自动下载）
python scripts/vision_demo.py --dir raw_hands
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

## 网页前端（Streamlit，M14）

命令行之外，也给了一个可交互的网页版本：**手照识别** 或 **手工填 7 项特征**，右侧出三张推荐卡。

```bash
pip install -r requirements-frontend.txt   # 只装前端依赖，不影响核心测试
streamlit run app/streamlit_app.py         # 默认 http://localhost:8501
```

页面能力：

- 输入方式切换：**手照识别**（上传手照 → 自动提特征）或 **手动选择特征**
- 手照识别：模型未下载时页面内一键下载；上传后展示质量、左右手、手势、ITA°，不可靠字段用下拉手动补（M11 回退）
- 场景预设（短宽暖皮 / 纤细冷皮 / 浓郁节日 / 长甲 y2k）+ 7 个下拉逐个微调
- 自由描述（参与语义加权）与「用大模型生成理由」开关（需 `DEEPSEEK_API_KEY`）
- 款式库切换：样例库（13 条，占位图）/ 演示库（43 条，带演示图）
- 三张卡展示：图片、档位、匹配度、推荐理由、避雷提示、命中规则
- 「查看原始 JSON」便于调试和接下游

前端只负责布局，特征校验、推荐编排、视图整理分别复用 `core.features` / `core.pipeline` / `core.ui_view`，手照识别复用 `core.vision`，和 CLI、FastAPI 行为一致。`tests/test_frontend.py` 用 Streamlit 官方 `AppTest` 做冒烟测试，没装 streamlit 时自动跳过。

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

### 自动打标签（M7）

M7 要的是“图片 → 结构化标签”。正式库人工复核前，先用 `scripts/autotag.py` 从演示图生成一份可跑的演示库：

```bash
# 从 static/demo 的 43 张图生成 data/styles.demo.json
python scripts/autotag.py

# 只看看会生成什么，不写文件
python scripts/autotag.py --dry-run

# 校验 + 确认图片都在
python scripts/validate_styles.py --styles data/styles.demo.json --check-images

# 用演示库跑推荐（4 个场景都能出三张卡）
python scripts/demo.py --styles data/styles.demo.json --scenario slender_cool
```

颜色维度（hue / color_family / tone / value / saturation）从图片主色计算；形状、工艺、长度、场景从文件名关键词推测。想人工修正，把字段写进 `data/demo_labels.json`（id → 字段），再 `python scripts/autotag.py --overrides data/demo_labels.json`。

### 视觉层：手照 → 手部特征（M8/M9）

装好 mediapipe 后，用 `scripts/vision_demo.py` 把一张手照变成和手工录入同口径的特征（模型缺失时会自动下载到 `models/`，约 8MB）：

```bash
# 单张 / 整个目录（raw_hands/ 里的手照已被 gitignore）
python scripts/vision_demo.py raw_hands/hand01_right_01.jpg
python scripts/vision_demo.py --dir raw_hands

# 不想自动下载时加 --no-download
python scripts/vision_demo.py --dir raw_hands --no-download

# 输出 JSON（接 API / 攒评测集）
python scripts/vision_demo.py --dir raw_hands --json out_hands.json
```

输出：左右手、手势、肤色（ITA° → `ita_band`/`warmth`）、甲床比例/甲型/甲长/手型，以及每项的置信度和原始几何量；同时在 `static/preview/` 生成关键点标注图。

手照直接出推荐（M9）有三条入口，行为一致：`core.pipeline.recommend_from_image()`、`POST /api/recommend/from-image`、Streamlit 前端「手照识别」。

**拍图规范（按省事程度排，前两种就能全自动）**：

1. **最省事（推荐）**：手背朝上平放在桌面/腿上，手机从正上方拍。手指自然并拢或微开都行，不用刻意把指甲怼向镜头。
2. **自然展开**：手背朝向镜头、手指自然伸开站着拍（指尖略朝上）；整只手入画，占画面 ≥ 15%。
3. **随手角度（握拳、展示美甲）**：也能用——自动出肤色，甲床比例/甲型/甲长/手型在页面上用下拉补选即可（M11），不需要重拍。
4. 光线均匀，避免逆光和强反光。

**分级质量门槛**（`core/vision.py: quality_gate`）：`ok`（平放/自然展开，7 项全自动）→ `relaxed`（手略扣，只出肤色）→ `clenched`（握拳/展示角度，只出肤色）→ `pose`（手朝镜头、透视过重）→ `low`（手太小/置信度低）。不用摆标准手势：手势模型给 `Open_Palm` 或几何伸展度 ≥ 0.88 都算 `ok`。

**M12 第一版校准（2026-10-23）**：用 6 张「手背平放、正上方」的标准手照实测：

- 像素量测路径：GrabCut 整手掩膜（关键点骨架做前景种子）→ 垂直手指轴向双向量宽 → 三指中位数剔离群值；甲板长 ≈ DIP→指尖 × 0.85，甲宽 ≈ 该处指宽 × 0.85（`core/vision.py: NAIL_LENGTH_FACTOR / NAIL_WIDTH_FACTOR`）。
- 6 张结果自洽：`aspect` 0.77–0.86、`taper` 0.84–0.91，6/6 判 `ok`；阈值据此定为 `NAIL_BED_THRESHOLDS=(0.72, 0.95)`、`TAPER_ALMOND=0.78`、`TAPER_SQUARE=0.92`、`HAND_TYPE_THRESHOLDS=(0.88, 1.05)`（同一只手 2D 掌宽/掌长会波动 ±0.09，所以手型只做宽档判断）。
- 量测异常（单指宽 > 图宽 22%，或 aspect/taper 超出 0.4–1.6）会自动丢弃，按「不可靠」处理，交给下拉补选。

已知限制：甲长/甲型/甲床比例是基于指节几何的**估算**，不是真实的甲板分割；手型可能在相邻档之间跳 ±1 档。要在**任意角度全自动**量甲面，需要训练一个「甲面分割模型」（要标注数据，记在后续可选任务），不是这版范围。正式校准建议攒 20–30 张多手照片再跑一轮。

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

### `POST /api/vision/extract`（M8/M9）

手照路径 → 手部特征（只识别，不推荐）：

```json
{
  "image_path": "raw_hands/hand01_right_01.jpg",
  "scene": "commute",
  "overrides": {"nail_shape": "oval"},
  "auto_download": false
}
```

返回 `features`、`quality`（`ok` / `relaxed` / `clenched` / `pose` / `low`）、`handedness`、`gesture`、`confidences`、`unreliable`（不可靠/缺失字段）、`notes`、`ita_degrees`、`metrics`、`preview`（关键点标注图路径）。

### `POST /api/recommend/from-image`（M9）

手照直接出三张推荐卡（响应在 `POST /api/recommend` 基础上多一个 `vision` 元信息）。照片质量不达标或缺特征时返回 `422`，提示可用下拉补选，或改用 `POST /api/recommend` 手工补齐。

> 说明：当前 `image_path` 是本地路径，只适合本机演示；公网部署时应改成上传接口并加鉴权。

## 错误处理

所有失败路径都返回**一行能看懂的中文原因**，不用翻 traceback：

| 场景 | CLI 表现 | API 表现 |
|---|---|---|
| 特征值非法（如 `length=eternal`） | `特征非法：...`，退出码 1 | `422`，`detail` 说明哪个字段不合法 |
| 款式库文件缺失 / JSON 损坏 | `✗ 推荐失败：...`，退出码 2 | `503`，`款式库不可用: ...` |
| 款式库为空（`styles: []`） | 同上 | `503`，`款式库不可用: ...` |
| 规则过滤后无候选 | `✗ 推荐失败：没有通过硬性过滤的款式...` | `422`，`无法生成推荐: ...` |
| 过滤后不足 3 款（凑不齐三档） | 同上 | `422`，`过滤后只剩 N 款，至少需要 3 款` |
| 手照没检测到手 / 模型缺失 | `✗ ...`，退出码 2 | `422`，`手照识别失败: ...` |
| 手照是随手角度（握拳/半握） | 只输出肤色，甲面字段标「不可靠」，前端下拉补选即可 | `422`，`手照信息不足: ...`，提示补选或手工补齐 |
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

`data/styles.demo.json` 是同一 schema 的 43 条演示库（`autotag` 生成，额外带 `autotag: true` 与 `name`，图片指向 `static/demo/`），只用于工程演示；正式库仍为 `data/styles.json`。

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
