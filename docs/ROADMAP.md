# NailFit 剩余任务清单（Roadmap）

> 状态基线：`1a2d5d1`（2026-10-23，已含 M1–M4）→ `10f640e`（M5 说明 + M6 工具 + 43 张演示图 + M7 演示库）→ `88e2126`（M14 Streamlit 前端）→ `b3a881c`（M8 视觉层 + M9 接进主流程）→ `f610669`（自然拍摄角度适配）→ `175f96b`（M12 校准）→ `653c2dc`（M17 解释层）→ `48badc4`（M17 云端实测文档）→ `379461b`（M18 评测脚本 + 修复 3 条缺口）→ `ccb96cc`（M24 媒体层 + M25 搜索来源文本）→ **本次改动：M26 Openverse 候选图 + M27 样例库占位图 / 首页图廊 + M28 Vue 3 前端与库选择/上传接口（测试 226 个）**
> 已完成：项目骨架、规则引擎（18 条规则）、三选一、输出契约校验、CLI demo、FastAPI、GitHub Actions CI、MIT License、**M1–M4**；**M5 说明、M6 工具 + 43 张演示图、M7 演示库（43 条，`data/styles.demo.json`）就绪**；**M14 Streamlit 单页（`app/streamlit_app.py`）完成**；**M8 视觉层 + M9 主流程接入完成**（`core/vision.py`、`scripts/vision_demo.py`、`/api/vision/extract`、`/api/recommend/from-image`、前端「手照识别」）；**M12 第一版校准完成**（6 张标准手照，依据见 README「M12 第一版校准」）；**M17 解释层完成**（LLM 理由 + 模板降级 + 云端 3/3 实测）；**M18 评测脚本完成**（契约/合理性/多样性/稳定性/抖动）；**M19 评测集完成**（25 条用例 + 视觉层指标，测试 162 个）；**M24 参考图媒体层完成**（schema v2 + 预取/校验脚本，测试 198 个）；**M25 趋势/参考来源文本完成**（`scripts/web_sources.py`：真实 Key 实测 Search 可用、Fetch 无图，图片仍走本地图库 / Pexels）；**M26 Openverse 候选图完成**（`scripts/openverse_candidates.py` + CC 白名单/尺寸/相关性过滤，只产出候选清单，测试 217 个）；**M27 样例库占位图 + 首页图廊完成**（`scripts/make_sample_images.py` 生成 15 张示意图，Streamlit 首页展示当前库 8 张款式图，卡片图宽自适应）；**M28 Vue 3 前端完成**（独立目录 `naifit-fonted/`：工作台 + 款式库两页、三档可解释结果卡、完整 JSON 下载、手照上传识别、样例库/演示库切换；后端配套 `POST /api/vision/upload`、`GET /api/styles?library=`、`POST /api/recommend` 的 `library`，测试 226 个）
> 原则：**规则决定推荐什么，模型只决定怎么说；不生成图片，只从款式库挑图。**

---

## 阶段一：让项目"可演示"（负责人：AI，已完成）

| ID | 任务 | 产出 | 验收标准 | 状态 |
|---|---|---|---|---|
| M1 | 手工特征录入 CLI | `scripts/manual.py` | `python scripts/manual.py` 交互输入 7 项特征 → 输出三张卡；支持 `--json` | ✅ 已完成（`01ea981`） |
| M2 | 款式库校验脚本 | `scripts/validate_styles.py` + `core/styles.py` | 字段/枚举/唯一性/图片存在性可检查 | ✅ 已完成（`01ea981`） |
| M3 | README 补"如何演示" | README 一节 | 面试场景 3 步可复现 | ✅ 已完成（`1a2d5d1`） |
| M4 | 异常与边界处理 | `core/errors.py` + 路由/CLI/测试 | 款式库为空、特征非法、无可用款式时返回清晰错误 | ✅ 已完成（`1a2d5d1`） |

> 阶段一收尾标准：`pytest` 全绿（当前 60 个用例），`demo.py` / `manual.py` / `validate_styles.py` 三条命令都能给出可读输出。

## 阶段二：款式数据（负责人：你，2–3 天）

| ID | 任务 | 产出 | 验收标准 | 状态 |
|---|---|---|---|---|
| M5 | 确定图片来源与授权 | `docs/IMAGE_GUIDE.md` | 自拍 / 可商用图库 / 网络图（需在 README 写明） | ✅ 已完成（含演示图映射，来源待正式确认） |
| M6 | 收集 200 条款式图 | `static/styles/<id>.jpg` | 统一角度与背景，单张 ≤ 300 KB | 🔄 工具 + 43 张演示图就绪（`static/demo/`，仅演示、不进 git），正式库待原图 |
| M7 | 打标签并录入 | `data/styles.demo.json`（演示）/ `data/styles.json`（正式） | 字段见 `data/styles.sample.json`，用 `scripts/validate_styles.py` 校验 | 🔄 演示库已自动生成（43 条，`scripts/autotag.py`，校验+图片检查通过）；正式库待人工复核 |
| M8 | 提供 3–5 张真实手照 | 图片文件 | 用于规则校准，可脱敏（只要手部） | 🔄 已收到 11 张（2 人 × 左右手，握拳/展示角度）+ 6 张标准手背照（`raw_hands/`，gitignore）；随手角度也能用（自动出肤色，甲面特征下拉补选）；M12 已用 6 张标准照完成第一版校准 |

> M6 快速流程：原图放 `raw_images/` → `prepare_images.py` 自动裁 3:4、压到 ≤300KB → `validate_styles.py --check-images` 校验。截图类先用 `--box x1,y1,x2,y2` 框掉状态栏/评论区，宽图用 `--fit pad` 补边。

## 阶段三：视觉层（负责人：AI，1–2 天；依赖 M8）

| ID | 任务 | 产出 | 验收标准 | 状态 |
|---|---|---|---|---|
| M9 | MediaPipe 关键点接入 + 接进主流程 | `core/vision.py`、`scripts/vision_demo.py`、`api/routes.py`、前端 | 手照 → 21 关键点 → 合法 HandFeatures；`/api/vision/extract`、`/api/recommend/from-image`、前端「手照识别」可用 | ✅ 已完成（gesture_recognizer + 21 点 + 几何特征 + 分级质量门槛；手背平放/自然展开全自动，握拳等自然角度只出肤色 + 下拉补选） |
| M10 | 肤色采样与 ITA° | `core/vision.py` | 取色区 → Lab → ITA° 与冷暖，口径与手动录入一致 | ✅ 已完成（掌心中位色 + 肤色掩膜；实测 ITA° 可用） |
| M11 | 甲长/甲型兜底输入 | API/CLI | 关键点测不准的量由用户选择 | ✅ 已完成（视觉层标 `unreliable`；前端手动补 + API `overrides`） |
| M12 | 阈值校准 | `core/vision.py` | 用真实手照校准，依据写入 docs | ✅ 第一版已完成（6 张标准手照：修掉宽度饱和 bug、换 GrabCut 整手掩膜、按实测定 `aspect/taper/hand_type` 阈值；依据见 README「M12 第一版校准」。正式版建议 20–30 张多手数据） |
| M13 | 视觉层测试 | `tests/test_vision.py` | 固定关键点数据单测，不依赖真实图片 | ✅ 已完成（`test_vision.py` 29 个含 M12 量测回归 + `test_vision_pipeline.py` 10 个） |

## 阶段四：前端（负责人：AI，1–2 天）

| ID | 任务 | 产出 | 验收标准 |
|---|---|---|---|
| M14 | 极简单页 | `web/index.html` | 上传/选参数 → 三卡（图 + 理由 + 命中规则） ✅ 已完成（Streamlit 版 `app/streamlit_app.py`，支持 7 项特征 + 场景预设 + 样例库/演示库切换） |
| M15 | 或 Vue3 版本 | `frontend/` | 与 llmops-frontend 风格统一（2–3 天） |
| M16 | 联调 | 配置 | CORS 通过，端到端可用 |

## 阶段五：解释层与评测（负责人：共同，~1 天）

| ID | 任务 | 产出 | 验收标准 | 状态 |
|---|---|---|---|---|
| M17 | 解释层：LLM 生成理由 + 模板降级 | `core/explainer.py`、`scripts/check_llm.py`、README | LLM 3/3 条理由通过清洗与契约校验；无 Key/超时自动降级并在 `meta.explainer` 标注 | ✅ 已完成（`653c2dc`；云端 `deepseek-chat` 实测 3/3、无降级；本地 Ollama 小模型 2–3/3 用于验证降级路径；测试 140 个） |
| M18 | 评测脚本 | `eval/run.py`、`eval/cases.json` | 批量跑 cases → 合理率/多样性/稳定性 | ✅ 已完成（契约 100%、合理性 100%、多样性 100%、top-1 稳定 100%、单特征抖动 16%；首轮 3 条缺口已修复，`known_gap` 0 条） |
| M19 | 评测集 | `eval/cases.json` | 真实手照 + 人工期望 | ✅ 已完成（25 条用例 = 8 手工 + 17 手照；新增 `--vision`：检测率 88%、肤色 73%、甲床 100%、甲型 71%、甲长 100%、手型 50%；演示库 43 条：契约 100%、合理性 92%、多样性 12%（autotag 标签噪声）；修掉放宽步骤选同色系的契约 bug；测试 162 个） |

## 阶段六：媒体完善 + 求职包装（负责人：共同，媒体 M24–M27，包装 M20–M23）

| ID | 任务 | 产出 | 验收标准 |
|---|---|---|---|
| M20 | README 截图/GIF | README 顶部 | 一屏看懂项目做什么 | 🔄 部分完成（首页款式库图廊截图已入 README：`docs/screenshots/home-gallery.jpg`；推荐结果图 / GIF 待补） |
| M21 | 2–3 分钟演示视频 | 视频 | 从手照到三卡的完整流程 |
| M22 | 面试讲解稿 | `docs/pitch.md` | 3 分钟版：问题 → 方案 → 取舍 → 结果 |
| M23 | 简历条目（STAR） | 简历 | 一句话说清技术点与量化结果 |
| M24 | 参考图媒体层：款式 → 授权参考图 + 来源 | `core/media.py`、`scripts/migrate_styles_v2.py` / `prefetch_media.py` / `validate_media.py` | 演示库 43/43 有图；推荐请求不联网；无图降级为纯文字；每张图带 license + source_url；测试 198 个 | ✅ 已完成（schema v2 + 本地 Provider 已跑通；Pexels 需 API Key；DeepSeek Search 实测 Fetch 无图，已移出默认图片链） |
| M25 | 趋势/参考来源文本：DeepSeek Search → 链接与摘要 | `scripts/web_sources.py`、`core/media.py` 的 `search_sources()` | 输出 title / url / site / date / summary；不下载图片；缺 Key 时报错清晰；测试 +3 | ✅ 已完成（2026-10-26 真实 Key 实测：Search 可用、Fetch 只返回纯文本） |
| M26 | Openverse（免 Key CC）候选图清单 | `scripts/openverse_candidates.py`、`core/media.py` 的 `OpenverseProvider` | CC0/PDM/BY/BY-SA 白名单；长边 ≥600；标题/tags 含美甲词；查询逐级降级；只产出候选清单 + `candidates.json`，人工复核后入库；测试 +9 | ✅ 已完成（真实 Openverse 实测：短查询可用、长查询常 0 结果；本机访问需代理） |
| M27 | 样例库占位图 + 首页图廊 | `scripts/make_sample_images.py`、`core/ui_view.py` 的 `gallery_styles()`、`app/streamlit_app.py` | 样例库 15 条都有示意占位图；首页未推荐时先展示当前库 8 张款式图（缺图跳过）；卡片图宽自适应；测试 +7 | ✅ 已完成（15 张 768×1024 占位图随仓库提交；浏览器实测首页 8 图 + 图注正常） |
| M28 | Vue 3 前端（独立目录）+ 后端配套 | `naifit-fonted/`（Vue 3 + Vite + TS）、`api/main.py` 的 `StaticFiles` 挂载、`POST /api/vision/upload`、`GET /api/styles?library=`、`POST /api/recommend` 的 `library` | 工作台/款式库两页；三档结果卡 + 理由 + 避雷 + 完整 JSON 下载；手照上传识别回填；样例库/演示库切换；`vue-tsc` 与 `vite build` 通过；浏览器实测可用 | ✅ 已完成（2026-10-26；浏览器实测：演示库 43 款三档推荐、图廊 43 图、上传识别回填；测试 226 个） |

---

## 依赖关系

```
M5 → M6 → M7 ──► 真实数据可用于验证 M1/M2
M8 ──► M9/M10/M12
M1 ──► M14（前端先接手工录入，再接视觉层）
M17 ──► M19（LLM 理由参与评测）✅
M19 ──► 真实用户反馈 / 正式款式库评测（后续可选）
M20/M21 依赖 M1 或 M14（要有可演示入口）
```

## 建议的第一周

| 天 | 做什么 |
|---|---|
| D1 | M1 + M2（手工录入 CLI + 数据校验脚本）——✅ 已完成 |
| D2–D3 | M5–M7（图片说明 + 图片工具 + 43 张演示图 + autotag 演示库已就绪）；正式款式库等你出图 |
| D4 | M14（极简前端）——✅ 已完成（Streamlit 版 `app/streamlit_app.py`，测试 `tests/test_frontend.py`） |
| D5 | M8 + M9 + M12（手照 + 视觉层 + 主流程接入 + 第一版校准）——✅ 已完成（`f610669` 自然角度适配 + 本次 M12 校准：6 张标准手照，测试 130 个） |
| 周末 | M20/M21（截图 + 演示视频） |

## 可选增强

- 语义检索：`core/retriever.py` 已写好，开 `USE_SEMANTIC=true` 接本地 bge-m3（不需要 Chroma）
- 规则可视化配置页
- 多场景话术模板（通勤 / 约会 / 婚礼 / 节日各一套）
- 公网部署（Render / Railway），注意当前接口无鉴权
- 参考图联网预取：`scripts/prefetch_media.py --provider pexels|search`（需 `PEXELS_API_KEY` / `DEEPSEEK_API_KEY`），缓存进 `data/media_cache.json` 后可随项目分发
- 媒体层二期：把 `data/media_cache.json` 中 `unknown` 授权的图逐张人工确认，替换成 Pexels / 自摄来源
