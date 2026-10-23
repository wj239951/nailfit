# 图片来源与选图规范（M5 / M6）

> 款式库图片是项目里唯一"非代码"的对外资产：既影响观感，也涉及版权。
> 本文定三件事：**能用什么图、图要长什么样、怎么处理入库。**

## 1. 授权优先级（从高到低）

| 优先级 | 来源 | 说明 |
|---|---|---|
| ✅ 最稳 | 自己 / 朋友的真实手照 | 授权清晰，还能用于视觉层校准（M8） |
| ✅ 推荐 | 可商用图库（Pexels / Unsplash / Pixabay） | 搜 `manicure`、`nail art`、`gel nails`，注意图库许可 |
| ⚠️ 可用 | 美甲师合作、博主明确授权 | 在 README 写明「已获授权用于作品集展示」 |
| ❌ 谨慎 | 小红书 / 微博等平台截图 | 版权归原作者。**仅限本地演示**，不要放进公开仓库；如放进仓库，README 必须标注来源与非商用声明，并准备随时替换 |

**结论**：这个项目是求职 demo，公开仓库会被面试官看到。正式库优先自拍 + 可商用图库；平台截图只当"打标参考"。

## 2. 选图标准

- **单款**：一张图只出现一款美甲；四宫格/多图拼贴要先拆图。
- **无界面**：不能有手机状态栏、App 顶栏/评论区、小红书水印、贴纸、文字。
- **手部完整**：至少露出 4 指，甲面清晰；角度统一（俯拍或 45° 斜拍）。
- **背景干净**：纯色、毛绒、布料、桌面；避免杂乱环境。
- **构图**：竖构图，比例 3:4 优先；短边 ≥ 600 px。
- **光线**：均匀不过曝，同一批色温尽量一致。
- **体积**：压缩后单张 ≤ 300 KB。

## 3. 处理流程

```bash
# 0) 原图放 raw_images/（该目录不进 git）

# 1) 先看计划，不写文件
python scripts/prepare_images.py --src raw_images --out static/styles --dry-run --prefix s --start 14

# 2) 批量处理：居中裁 3:4 → 缩放 768x1024 → JPEG 质量自适应压到 ≤300KB
python scripts/prepare_images.py --src raw_images --out static/styles --prefix s --start 14

# 3) 检查图片是否齐、字段是否合法
python scripts/validate_styles.py --check-images
```

截图类原图先框出照片区域（去掉状态栏和评论区），再用 `--box`；手部偏上时也可用 `--focus top`：

```bash
# 推荐：手动框选照片区域（左上 x1,y1 + 右下 x2,y2）
python scripts/prepare_images.py --src raw_images/0816.jpg --out static/styles/s014.jpg --box 0,180,1206,1410

# 或只保留偏上的手部区域
python scripts/prepare_images.py --src raw_images/shot1.jpg --out static/styles/s015.jpg --focus top
```

## 4. 命名与入库

- 文件名即 `style_id`：`static/styles/s014.jpg` ↔ `styles.json` 里 `"id": "s014", "image": "static/styles/s014.jpg"`。
- 打标字段见 README「数据契约」；新增款式后先跑 `validate_styles.py --check-images`。
- 同一款式有多种手/甲长时选一张主图，其余作为备选不重复入库。

## 5. 免责声明模板（放 README 与页面角落）

> 款式图片仅作风格参考，非本手模拟效果。部分图片来自公开平台，版权归原作者所有；本项目仅用于学习与求职演示，不用于商业用途，如有侵权请联系删除。

## 6. 演示图片（demo，2026-10-23）

用户先后提供的 49 张平台截图 / 素材 → 处理出 43 张单款演示图，放 `static/demo/`（三批，均为 2026-10-23）。

| 文件 | 来源原图 | 定位 |
|---|---|---|
| `demo01_nude_french.jpg` | IMG_0816 | 裸色 + 白法式，safe / 婚礼·通勤 |
| `demo02_nude_polka_bow.jpg` | IMG_9527 | 裸粉 + 白法式 + 波点，safe |
| `demo03_sheer_nude.jpg` | IMG_9524 | 裸色细闪，safe / 通勤 |
| `demo04_olive_green.jpg` | image_6b91 | 橄榄绿纯色短方，bold / 暖秋 |
| `demo05_sheer_star.jpg` | image_f38b | 透色 + 金属星星，highlight / y2k |
| `demo06_pink_gradient.jpg` | IMG_9520 | 粉渐变，highlight / 甜 |
| `demo07_brown_cateye.jpg` | image_d5cf | 深棕猫眼 + 金箔，bold / 酷 |
| `demo08_yellow_daisy.jpg` | IMG_9516 | 黄渐变 + 小白花，highlight / 春夏 |
| `demo09_glitter_cartoon.jpg` | IMG_9518 | 细闪 + 卡通贴片短甲，甜酷 / 学生 |
| `demo10_nude_french_dots.jpg` | IMG_9525 | 裸色白法式 + 波点，safe / 通勤 |
| `demo11_blue_almond_stars.jpg` | 0097（单图） | 蓝渐变杏仁 + 星星/波点，highlight / y2k |
| `demo12_sheer_glitter_heart.jpg` | 0098（2/10） | 透色 + 心形银箔长杏仁，highlight / 甜酷 |
| `demo13_blue_star_satin.jpg` | 0099（3/10） | 裸粉 + 蓝白星星法式，highlight |
| `demo14_glitter_lines_nude.jpg` | 0100（4/10） | 裸色 + 银色线条闪，safe / highlight |
| `demo15_bow_star_nude.jpg` | 0101（5/10） | 透粉 + 蝴蝶结/星星手绘，highlight / 甜 |
| `demo16_glitter_checker.jpg` | 0102（6/10） | 银闪 + 棋盘格拼接，bold / y2k |
| `demo17_flower_stone_nude.jpg` | 0103（7/10） | 裸粉 + 立体花朵/钻饰，safe / 约会 |
| `demo18_glitter_ombre_nude.jpg` | 0104（9/10） | 裸色 + 银色亮片渐变长杏仁，highlight |
| `demo19_white_lace_long.jpg` | 0105（6/13） | 白色蕾丝长尖甲，bold / 婚礼 |
| `demo20_french_bow_long.jpg` | 0106（13/13） | 裸透 + 白法式 + 蝴蝶结长甲，highlight / 婚礼 |
| `demo21_brown_velvet_floral.jpg` | 0107（10/10） | 棕猫眼 + 碎花长杏仁，bold / 暖秋 |
| `demo22_nude_beige_oval.jpg` | 0108（2/16） | 裸杏色短椭圆，safe / 通勤 |
| `demo23_brown_cream_two_tone.jpg` | 0109（2/10） | 深棕 + 奶油双色短方，bold / 暖秋 |
| `demo24_pink_sheer_squoval.jpg` | 0110（4/10） | 裸粉透色方圆，safe / 温柔 |
| `demo25_pastel_pink_blue.jpg` | 0111（6/10） | 粉蓝撞色短圆，highlight / 甜 |
| `demo26_cream_taupe_square.jpg` | 0112（7/10） | 奶油 + 灰褐短方，safe / 通勤 |
| `demo27_sage_olive_square.jpg` | 0113（9/10） | 鼠尾草绿短方，highlight / 清新 |
| `demo28_dark_red_cream_square.jpg` | 0114（10/10） | 酒红 + 奶油短方，bold / 酷 |
| `demo29_blue_doodle_long.jpg` | 0115（2/3） | 亮蓝长椭圆（手绘涂鸦），bold / y2k |
| `demo30_blue_white_cool.jpg` | 0116（1/3） | 蓝白撞色短方，bold / y2k |
| `demo31_dusty_blue_long.jpg` | 0117（3/3） | 灰蓝长椭圆，bold / 冷调 |
| `demo32_mauve_cateye_square.jpg` | 0118（2/9） | 藕紫猫眼 + 白短方，highlight / 气质 |
| `demo33_nude_french_round.jpg` | 0119（3/9） | 裸粉法式短圆，safe / 婚礼 |
| `demo34_mauve_star_glitter.jpg` | 0120（4/9） | 藕紫 + 星星亮片短方，highlight / 甜 |
| `demo35_navy_cateye_almond.jpg` | 0121（3/16） | 藏蓝猫眼长杏仁，bold / 酷 |
| `demo36_light_blue_metal.jpg` | 0122（5/16） | 浅蓝金属长杏仁，bold / y2k |
| `demo37_plum_cateye_almond.jpg` | 0123（6/16） | 梅子紫猫眼长杏仁，bold / 气质 |
| `demo38_berry_cateye_almond.jpg` | 素材（10/16） | 莓果紫猫眼长杏仁，bold / 气质 |
| `demo39_olive_cateye_almond.jpg` | 素材（13/16） | 橄榄金猫眼长杏仁，bold / 特色 |
| `demo40_greige_lilac_cateye.jpg` | 素材（10/16） | 灰紫猫眼长杏仁，bold / 冷调 |
| `demo41_lilac_cream_almond.jpg` | 素材（8/16） | 丁香紫奶油长杏仁，highlight / 温柔 |
| `demo42_gold_green_metallic.jpg` | 素材（9/16） | 金属橄榄金长杏仁，bold / y2k |
| `demo43_red_gloss_almond.jpg` | 素材（7/16） | 酒红亮面长杏仁，bold / 气场 |

- **用途**：仅工程演示（README 截图、前端联调占位、面试讲解示意）。
- **不登记进款式库**：不写入 `data/styles.json`、不占 `s0xx` 编号；`static/demo/` 已加入 `.gitignore`，不进仓库。
- 四宫格拼图（IMG_0043 / 0044 / 0045 / 0046）未保留；2 张双拼 / 内嵌 App UI 的截图未使用。
- 第二、三批的图集截图（共 32 张）版式统一：顶栏 `0–505`、底栏 `2113–2622` 为黑色 UI，统一用 `--box 0,505,1206,2113` 裁成 3:4（无需 padding）；`0097` 单图本身接近 3:4，直接缩放。
- 个别图仍带平台角标（`demo04` 的 `8/100`、相机图标；`demo07` 的 `22/100`）和博主水印，保留作为"来源就是平台截图"的直观说明；正式库请换成自拍 / 图库图。

处理命令（人工框选照片区域 → 3:4 → 768×1024 → ≤300 KB；宽图用 `--fit pad`）：

```bash
# 竖图：框掉状态栏 / 评论区后裁 3:4
python scripts/prepare_images.py --src raw_images/9527_polka_bow.jpg ^
  --out static/demo/demo02_nude_polka_bow.jpg --box 0,400,1206,2008

# 宽图 / 比例差太多：整图放进 3:4 画布，补底色
python scripts/prepare_images.py --src raw_images/9524_sheer_nude.jpg ^
  --out static/demo/demo03_sheer_nude.jpg --box 0,704,1206,1608 --fit pad --pad-color "#f5f2ec"

# 第二批图集截图：统一裁掉黑色顶栏 / 底栏
python scripts/prepare_images.py --src raw_images/0103_flower_stone_nude.jpg ^
  --out static/demo/demo17_flower_stone_nude.jpg --box 0,505,1206,2113
```

**演示库（M7）：** 这 43 张演示图对应 `data/styles.demo.json`（`scripts/autotag.py` 从 `static/demo/` 自动生成，颜色维度算自图片、形状/工艺/长度/场景按文件名推断；`python scripts/demo.py --styles data/styles.demo.json --scenario slender_cool` 可跑通三张卡）。演示库**只用于工程演示**：不替代正式 `data/styles.json`，也不参与 git（图片目录 `static/demo/` 已 gitignore）。
