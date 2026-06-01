# 东南亚跨境外贸 AI Pipeline — 完整设计方案

## 1. 项目概述

### 1.1 背景与目标

本项目面向东南亚跨境外贸行业，以 1688 平台为商品货源，通过 AI 全链路处理，
将中国商品自动本土化，生成五个东南亚国家的本土化商品资料（文案、图片、营销视频）。

**核心价值**：原本需要运营人员数天手工完成的商品本土化流程，
通过 AI Pipeline 压缩至数小时自动完成。

### 1.2 目标市场

| 国家        | 语言                        | 货币 | 计费代码 |
|-------------|-----------------------------|------|----------|
| 🇸🇬 新加坡  | English（主）/ 中文          | SGD  | SG       |
| 🇹🇭 泰国    | Thai                        | THB  | TH       |
| 🇲🇾 马来西亚 | Bahasa Malaysia             | MYR  | MY       |
| 🇮🇩 印度尼西亚 | Bahasa Indonesia           | IDR  | ID       |
| 🇵🇭 菲律宾  | Filipino / English          | PHP  | PH       |

### 1.3 整体业务流程

```
1688 商品采集
      ↓
商品信息结构化（metadata.json）
      ↓
汇率转换 → 五国定价
      ↓
AI 翻译与本土化文案生成（× 5国）
      ↓
商品图片文字检测与本地化替换
      ↓
营销视频脚本生成（× 5国）
      ↓
AI 视频生成（× 5国）
```

---

## 2. 系统架构

### 2.1 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Pipeline Orchestrator                       │
│                         (pipeline.py — 主调度器)                     │
└────┬────────┬────────┬────────┬────────┬────────────────────────────┘
     │        │        │        │        │
     ▼        ▼        ▼        ▼        ▼
 ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐
 │  M1   │ │  M2   │ │  M3   │ │  M4   │ │  M5   │
 │1688   │ │翻译   │ │图片   │ │汇率   │ │视频   │
 │采集   │ │文案   │ │处理   │ │转换   │ │生成   │
 └───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘
     │         │         │         │         │
     └────┬────┴─────────┴────┬────┘         │
          │                   │              │
          ▼                   ▼              ▼
    ┌──────────┐        ┌──────────────────────┐
    │ SQLite   │        │      本地文件系统      │
    │ 状态管理  │        │  output/{keyword}/   │
    └──────────┘        │  {序号}/localized/   │
                        └──────────────────────┘
```

### 2.2 AI 模型分工

| 模块 | 任务                   | 模型                       | 调用方式               |
|------|------------------------|----------------------------|------------------------|
| M2   | 文字生成 + 多语言本土化 | DeepSeek V3（deepseek-chat）| OpenAI-compatible API  |
| M3   | 图片中文文字检测        | PaddleOCR PP-OCRv4（本地）         | 本地 GPU 推理  |
| M3   | 文字区域消除（背景修复） | LaMa（via IOPaint，本地）          | 本地 GPU 推理  |
| M4   | 营销视频脚本生成         | Claude claude-sonnet-4-6          | Anthropic API  |
| M4   | AI 视频生成             | Kling AI 1.6（主）         | Kling API              |
|      |                        | Runway Gen-3（备）         | Runway API             |
| M4   | TTS 配音                | Microsoft Edge TTS         | edge-tts（免费）       |

### 2.3 数据流向

```
[1688页面]
    │  Selenium 爬取
    ▼
[本地文件系统]                    [SQLite DB]
  output/keyword-date/               products
    {序号}/                          localizations
      metadata.json    ←→            image_tasks
      商品详情图片/                   video_tasks
      商品规格/
      localized/        ← M2/M3 输出
        SG/ TH/ MY/ ID/ PH/
          images/       ← 本地化图片
          video.mp4     ← 生成视频
```

---

## 3. 模块详细设计

### Module 1 — 1688 商品采集

**文件**：`modules/scraper/scraper.py`（入口函数）+ `modules/scraper/spider.py`（Selenium 封装）

**调用接口**：

```python
from modules.scraper import run_scraper

products: list[dict] = run_scraper(
    keyword="儿童玩具",   # 中文关键词，内部自动 GBK 编码
    start_page=1,
    end_page=3,
    output_dir=None,      # 默认 output/（项目根目录下）
    cookie_path=None,     # 默认 GetDatafrom1688/1688.cookie
)
```

**输入**：搜索关键词、起止页码

**输出**：`output/{keyword}-1688-{YYYY-MM-DD_HH-MM}/` 目录 + 每个商品的 `metadata.json`，同时返回 `list[dict]`

#### metadata.json 字段（已验证）

```json
{
  "item_no": 1,
  "keyword": "包包",
  "title_cn": "帆布大容量学生休闲可爱腊肠狗购物袋便当包",
  "price_cny": 8.6,
  "shop_name": "定兴县鑫聚广来箱包制造有限责任公司",
  "item_link": "http://detail.m.1688.com/page/index.html?offerId=863910804068",
  "shop_link": "http://shop4293e773495e2.1688.com/",
  "specs": [
    {
      "name": "白色腊肠狗",
      "price_cny": 8.6,
      "image_path": "商品规格/白色腊肠狗——8.60/001.jpg"
    }
  ],
  "detail_images": [
    "商品详情图片/001.jpg",
    "商品详情图片/002.jpg"
  ],
  "scraped_at": "2026-05-29T17:04:15",
  "status": "scraped"
}
```

> `specs[].image_path` 和 `detail_images` 中的路径均为相对于该商品目录的相对路径，只记录实际下载成功的图片。

#### 两阶段爬取策略

```
第一阶段（搜索结果页）
  └─ 一次性提取当页所有商品的基本信息到内存（title / price / shop / links）
        ↓ 全部提取完毕后再开始跳转，避免 DOM 失效
第二阶段（商品详情页）
  └─ 逐一访问详情链接
        ├─ 慢速滚动触发懒加载
        ├─ 点击「商品详情」Tab，递归穿透 Shadow DOM 提取图片
        ├─ 下载图片（detail + specs），仅记录下载成功的路径
        └─ 写入 metadata.json
```

#### 关键技术点

- **中文关键词 URL 编码**：`urllib.parse.quote(keyword, encoding="gbk")`（1688 使用 GBK，非 UTF-8）
- **Selenium 代理穿透**：`options.ignore_local_proxy_environment_variables()`（解决 Clash/V2Ray 冲突）
- **商品详情图片提取**：点击 Shadow DOM 内「商品详情」Tab，JS 递归穿透 Shadow DOM 搜索 `#offer-template-0` / `#detail`
- **规格图片提取**：慢速滚动（0.3s/步，400px/步）触发懒加载，过滤 `_sum` 缩略图
- **价格解析**：页面返回字符串如 `"¥5.01~¥9.99"`，用 `re.search(r'\d+\.\d+', ...)` 提取首个浮点数
- **规格文件夹命名**：`{spec_name}——{price}`，`*` 替换为 `-`，其余 Windows 非法字符（`\ / : ? " < > |`）直接删除
- **翻页策略**：随机延时 10–30 秒防反爬；详情页间随机延时 3–8 秒
- **Cookie 维护**：登录态失效后运行 `GetDatafrom1688/GetCookie.py` 重新获取，保存为 `GetDatafrom1688/1688.cookie`

---

### Module 2 — 商品文字信息处理与本土化

**文件**：`modules/translator/localize.py`

**输入**：`metadata.json`（`status: scraped`，含 `title_cn`、`specs`、`price_cny`）

**输出**：`metadata.json` 追加 `localization` 字段，`status` 更新为 `text_localized`

#### 处理流程

```
metadata.json (status: scraped)
       │
       ├─ Step 1：汇率获取 + 五国定价
       │     ├─ 调用 ExchangeRate API（每日缓存，避免重复请求）
       │     └─ 按 PRICING_CONFIG：price_cny × 汇率 × markup + shipping → round_price
       │
       └─ Step 2：DeepSeek AI 内容生成（并发调用）
             ├─ 每商品 × 5 国 = 5 个请求（ThreadPoolExecutor 并发，实时返回）
             └─ 每请求一次输出该国全部文字字段：
                  标题 / 描述 / 商品关键词 / 卖点 / Hashtag / 规格名本土化 / CTA
                        ↓
metadata.json (status: text_localized)  ← 写入 localization 字段
```

#### 输出数据结构

```json
{
  "localization": {
    "SG": {
      "title": "Canvas Tote Bag with Cute Dachshund Print | Large Capacity",
      "description": "Spacious canvas bag for school, work or daily errands. Durable material with an adorable dachshund print — doubles as a great gift!",
      "keywords": ["canvas tote bag", "dachshund bag", "large capacity bag", "cute school bag"],
      "selling_points": [
        "Fits A4 books, lunchbox & more — seriously roomy",
        "Heavy-duty canvas, easy to wipe clean",
        "Unique dachshund print you won't find at every shop"
      ],
      "hashtags": ["#CanvasBag", "#ToteBag", "#TikTokShopSG", "#CuteBag", "#DailyCarry"],
      "specs": [
        {"name_cn": "白色腊肠狗", "name_local": "White Dachshund"},
        {"name_cn": "黑色腊肠狗", "name_local": "Black Dachshund"},
        {"name_cn": "卡其色腊肠狗", "name_local": "Khaki Dachshund"}
      ],
      "price_local": 15.90,
      "currency": "SGD",
      "exchange_rate": 0.185,
      "markup": 3.0,
      "cta": "Add to cart now — limited stock! 🛍️",
      "generated_at": "2026-05-29T18:00:00"
    },
    "TH": {
      "title": "กระเป๋าผ้าแคนวาสลายน้องหมาน่ารัก ความจุใหญ่มาก",
      "description": "กระเป๋าผ้าแคนวาสลายดัชชุนด์ จุของได้เยอะ เหมาะใส่หนังสือ กล่องข้าว ใช้งานทนทาน...",
      "keywords": ["กระเป๋าผ้า", "กระเป๋าแคนวาส", "กระเป๋าน่ารัก", "กระเป๋านักเรียน"],
      "selling_points": ["จุของได้เยอะมาก ใส่ได้ทุกอย่าง", "ผ้าแคนวาสคุณภาพดี ทำความสะอาดง่าย", "ลายน้องหมาน่ารัก ไม่ซ้ำใคร"],
      "hashtags": ["#กระเป๋าผ้า", "#กระเป๋าน่ารัก", "#TikTokShopTH", "#ของน่ารัก", "#กระเป๋าแคนวาส"],
      "specs": [
        {"name_cn": "白色腊肠狗", "name_local": "หมาสีขาว"},
        {"name_cn": "黑色腊肠狗", "name_local": "หมาสีดำ"},
        {"name_cn": "卡其色腊肠狗", "name_local": "หมาสีกากี"}
      ],
      "price_local": 189,
      "currency": "THB",
      "exchange_rate": 5.18,
      "markup": 3.5,
      "cta": "สั่งเลย ของมีจำนวนจำกัด! 🔥",
      "generated_at": "2026-05-29T18:00:00"
    },
    "MY": { "...": "同结构，Bahasa Malaysia" },
    "ID": { "...": "同结构，Bahasa Indonesia" },
    "PH": { "...": "同结构，Filipino/English" }
  },
  "status": "text_localized"
}
```

#### 定价策略配置（config.py）

```python
PRICING_CONFIG = {
    # markup:   利润倍率（含物流损耗）
    # shipping: 固定运费缓冲（本地货币）
    # round_to: 心理定价取整（0.90 → x.90；9 → xx9；1000 → 千位取整）
    "SG": {"currency": "SGD", "markup": 3.0, "shipping": 2.0,  "round_to": 0.90},
    "TH": {"currency": "THB", "markup": 3.5, "shipping": 30,   "round_to": 9},
    "MY": {"currency": "MYR", "markup": 3.0, "shipping": 3.0,  "round_to": 0.90},
    "ID": {"currency": "IDR", "markup": 3.8, "shipping": 5000, "round_to": 1000},
    "PH": {"currency": "PHP", "markup": 3.2, "shipping": 20,   "round_to": 9},
}
# 定价公式：round_price(price_cny × exchange_rate × markup + shipping, round_to)
```

#### Claude Prompt 设计

```python
LOCALIZE_PROMPT = """\
你是一位资深的东南亚跨境电商本土化专家，精通 {country_name} 的消费文化和 TikTok Shop 营销。

# 原始商品信息（来自1688）
- 中文原标题：{title_cn}
- 规格列表：{specs_cn}        （各规格名用逗号分隔）
- 批发价（人民币）：¥{price_cny}
- 本地售价：{price_local} {currency}

# 任务
请用 {language} 为 {country_name} 市场生成商品文字资料，以 JSON 格式返回：

{{
  "title": "商品标题（≤80字符，含核心搜索关键词）",
  "description": "商品描述（100~150字，突出使用场景和情感价值，禁止流水账）",
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4"],
  "selling_points": [
    "卖点1（具体可感知，禁用'高质量''物美价廉'等泛化表达）",
    "卖点2",
    "卖点3"
  ],
  "hashtags": ["#标签1", "#标签2", "#标签3", "#标签4", "#标签5"],
  "specs": [
    {{"name_cn": "原中文规格名", "name_local": "本地语言规格名"}}
  ],
  "cta": "行动号召语（≤20字，制造紧迫感，TikTok 风格）"
}}

# 各国本土化风格要求
- SG（新加坡）：轻松自然的英式英语，适合 25-40 岁都市白领，可带轻幽默
- TH（泰国）：活泼可爱的泰语，多用礼貌助词 ค่ะ/ครับ，年轻人喜欢的网感表达
- MY（马来西亚）：Bahasa Malaysia 为主，可夹杂少量英语（Manglish 风格），接地气
- ID（印尼）：现代 Bahasa Indonesia，适当加入流行网络语，亲和力强
- PH（菲律宾）：英语为主，可夹杂 Tagalog 感叹词（如 "Grabe!", "Sulit!"），TikTok 感强

严禁直译中文原标题；所有内容须针对目标市场文化重新创作。
"""
```

#### 并发调用（ThreadPoolExecutor）

使用 DeepSeek API（兼容 OpenAI SDK），`ThreadPoolExecutor` 并发发送所有商品 × 国家请求，实时返回结果，无需轮询等待。

```python
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

def _localize_one(product: dict, country: str) -> tuple:
    price_info = calculate_price(product["price_cny"], country)
    prompt = LOCALIZE_PROMPT.format(...)
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500,
        temperature=1.0,
    )
    return product["item_no"], country, _extract_json(resp.choices[0].message.content)

def localize_products(products: list[dict], countries: list[str]) -> list[dict]:
    tasks = [(p, c) for p in products for c in countries]
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_localize_one, p, c): (p, c) for p, c in tasks}
        for future in as_completed(futures):
            item_no, country, result = future.result()
            # 合并定价信息，写入 product["localization"][country]
            ...
    # 写回各商品 metadata.json，status → text_localized
    return products

# 汇率获取（每日缓存）
@lru_cache(maxsize=16)
def _fetch_rates(date: str) -> dict:
    resp = requests.get(f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/CNY", timeout=10)
    rates = resp.json()["conversion_rates"]
    return {"SG": rates["SGD"], "TH": rates["THB"], "MY": rates["MYR"],
            "ID": rates["IDR"], "PH": rates["PHP"]}
```

> **为何选 DeepSeek：** 价格约为 Claude Sonnet 的 1/10，支持中文和东南亚语言翻译，对本土化文案生成场景性价比极高。

---

### Module 3 — 商品图片信息处理与本土化

**文件**：`modules/image_processor/process.py`（入口）、`detector.py`、`translator.py`、`inpainter.py`、`renderer.py`

**运行环境**：本地 GPU（RTX 3080 16GB），OCR + Inpainting 全程离线；翻译调用 DeepSeek API

**输入**：`metadata.json`（`status: text_localized`）+ 商品图片目录

**输出**：本地化图片写入 `{item_dir}/localized/{country}/images/`，`status` 更新为 `images_processed`

#### 工具栈

| 步骤 | 工具 | 说明 |
|------|------|------|
| 中文文字检测 + 定位 | **PaddleOCR PP-OCRv4**（本地） | 专为中文设计，返回精确像素级四边形坐标，GPU 推理快 |
| 图片文字翻译 | **DeepSeek V3**（API） | 批量翻译 OCR 识别出的中文词，复用 M2 客户端，带缓存 |
| 文字区域消除 | **LaMa**（via IOPaint，本地） | 专攻文字/水印消除，背景修复自然，模型仅 200MB |
| 本地化文字渲染 | **Pillow + Noto 字体** | 覆盖泰文/马来/印尼/菲律宾文全字符集 |

**VRAM 占用**：PaddleOCR ≈ 1GB + LaMa ≈ 2GB，总计约 3GB，RTX 3080 16GB 充裕

#### 完整处理流程

```
metadata.json (status: text_localized)
    │
    ▼
遍历所有图片（detail_images + spec images）
    │
    ▼
Step 1: PaddleOCR 检测（本地 GPU）
    ├─ 识别图中所有文字及其四边形像素坐标
    ├─ 过滤：仅保留含中文字符的区域（unicode 一–鿿）
    ├─ [无中文] → 直接复制到输出目录，跳过后续步骤（省 ~80% 时间）
    └─ [有中文] → 汇总本张图片中的所有中文词列表
    │
    ▼
Step 2: DeepSeek 批量翻译（API）
    ├─ 先查 metadata.json 中 image_text_translations[country] 缓存
    ├─ 缓存未命中的词 → 一次性打包发送 DeepSeek，获取本土化译文
    │   Prompt：将词语译为 {language}({country_name}) 电商常用表达，返回 JSON {"原文":"译文"}
    └─ 翻译结果写回 metadata.json image_text_translations[country]（持久缓存，避免重复调用）
    │
    ▼
Step 3: LaMa Inpainting 消除原文字（本地 GPU）
    ├─ 将所有中文区域四边形转为二值 mask（外扩 3px 确保完整覆盖）
    └─ LaMa 根据 mask 修复背景（复杂背景/渐变/图案均可自然填充）
    │
    ▼
Step 4: Pillow 渲染本地化文字
    ├─ 在原坐标叠加 Step 2 的译文
    ├─ 自动缩小字号直到文字宽度 ≤ bounding box 宽度
    ├─ 自动选前景色（感知亮度 > 128 → 深色字；否则 → 浅色字）
    └─ 输出到 localized/{country}/images/{原文件名}
    │
    ▼
metadata.json (status: images_processed)
```

#### 难点与解决方案

**难点 1：OCR 识别词与 localization 字段的对应**

PaddleOCR 识别出的是图片里的原始词（如 `"防水面料"`），这些词不一定在 M2 生成的 localization 里。引入 `image_text_translations` 字段作持久缓存，仅对新词调用 DeepSeek：

```python
def translate_image_texts(words: list[str], product: dict, country: str) -> dict[str, str]:
    cache = product.setdefault("image_text_translations", {}).setdefault(country, {})
    missing = [w for w in words if w not in cache]
    if missing:
        # 打包调用一次 DeepSeek，节省 API 次数
        result = deepseek_translate_batch(missing, country)
        cache.update(result)
    return {w: cache[w] for w in words}

# DeepSeek Prompt（复用 M2 客户端）
TRANSLATE_PROMPT = """\
将以下中文电商词语翻译为 {language}（{country_name} 市场），保持简短口语化。
只返回 JSON：{{"原文1": "译文1", "原文2": "译文2"}}
词语列表：{words}
"""
```

**难点 2：自动选前景色（亮/暗背景自适应）**

```python
def get_foreground_color(image: Image.Image, box: list) -> tuple:
    xs, ys = [p[0] for p in box], [p[1] for p in box]
    region = image.crop((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))))
    pixels = np.array(region.convert("RGB")).reshape(-1, 3).astype(float)
    luminance = (0.299 * pixels[:, 0] + 0.587 * pixels[:, 1] + 0.114 * pixels[:, 2]).mean()
    return (20, 20, 20) if luminance > 128 else (240, 240, 240)
```

**难点 3：无中文图片直接跳过**

```python
def has_chinese(text: str) -> bool:
    return any('一' <= c <= '鿿' for c in text)

# 进入 Step 3/4 前的门控判断
chinese_regions = [r for r in ocr_result if has_chinese(r["text"])]
if not chinese_regions:
    shutil.copy(src_path, dst_path)
    return  # 直接跳过 LaMa + Pillow，节省资源
```

#### 字体文件

```
modules/image_processor/fonts/
    NotoSans-Regular.ttf          # SG / MY / ID / PH
    NotoSansThai-Regular.ttf      # TH（泰文专用）
```

下载：https://fonts.google.com/noto → 搜索 "Noto Sans"，按语言下载

#### metadata.json 新增字段

```json
{
  "image_text_translations": {
    "SG": {"防水面料": "Waterproof Material", "大容量": "Large Capacity"},
    "TH": {"防水面料": "วัสดุกันน้ำ",         "大容量": "ความจุขนาดใหญ่"}
  },
  "status": "images_processed"
}

---

### Module 4 — 商品视频信息处理与本土化

**文件**：`modules/video_generator/script_writer.py` + `modules/video_generator/video_gen.py` + `modules/video_generator/assembler.py`

**输入**：`metadata.json`（`status: images_processed`，含 `localization` + 本地化图片路径）

**输出**：`localized/{country}/video.mp4`，`status` 更新为 `video_done`

#### 处理流程（三阶段）

```
localization[country] + 商品图片
       │
       ├─ Stage 1：Claude 生成视频脚本（script_writer.py）
       │     ├─ 输入：标题 / 卖点 / 价格 / 图片数量
       │     └─ 输出：结构化脚本 JSON（场景编排 + 配音文本 + 转场特效）
       │
       ├─ Stage 2：Kling AI 图生视频（video_gen.py，异步并发）
       │     ├─ 每个 scene → Kling image-to-video API → 视频片段
       │     └─ 备选：Runway Gen-3（Kling 不可用时切换）
       │
       └─ Stage 3：视频合成（assembler.py）
             ├─ moviepy 拼接各场景片段
             ├─ edge-tts 生成本地语言配音
             ├─ 叠加字幕（TextClip）
             └─ 混入 BGM（音量 20%）→ 输出 video.mp4
```

#### Stage 1：视频脚本 JSON 结构

```json
{
  "total_duration": 30,
  "hook": "开场吸引语（前3秒抓住眼球）",
  "scenes": [
    {
      "scene_no": 1,
      "duration_sec": 5,
      "image_index": 0,
      "motion_effect": "zoom_in",
      "voiceover_text": "配音文字（目标语言）",
      "caption_text": "字幕文字",
      "caption_style": "bold_bottom",
      "transition": "cut"
    }
  ],
  "bgm_style": "upbeat",
  "full_voiceover_script": "完整旁白文本（供 TTS 合成）",
  "cta_text": "行动号召"
}
```

#### Stage 1：Claude Prompt 设计

```python
SCRIPT_PROMPT = """\
你是一位顶级 TikTok 短视频营销专家，专注 {country_name} 市场。

# 商品信息
- 本地化标题：{title_local}
- 核心卖点：{selling_points}
- 售价：{price_local} {currency}
- 可用图片：{image_count} 张（商品详情图 + 规格图）

# 任务
生成一个 {duration} 秒的 TikTok 竖版（9:16）视频脚本，要求：
1. 开头 3 秒必须有强力 hook（提问 / 痛点 / 视觉冲击）
2. 中间场景与图片编号对应，展示核心卖点
3. 结尾强调价格 + CTA，制造紧迫感
4. 语言风格：{language}，{country_name} 本土口语，接地气

以 JSON 格式返回，字段同脚本结构定义。
"""
```

#### Stage 2：Kling API 调用（异步）

```python
import httpx, asyncio

async def generate_clips(script: dict, images: list[str]) -> list[str]:
    clips = []
    async with httpx.AsyncClient() as client:
        for scene in script["scenes"]:
            resp = await client.post(
                "https://api.klingai.com/v1/videos/image2video",
                headers={"Authorization": f"Bearer {KLING_API_KEY}"},
                json={
                    "model_name": "kling-v1-6",
                    "image": encode_b64(images[scene["image_index"]]),
                    "prompt": scene["voiceover_text"],
                    "negative_prompt": "blurry, low quality, watermark",
                    "cfg_scale": 0.5,
                    "duration": str(scene["duration_sec"]),
                    "aspect_ratio": "9:16",
                    "camera_control": {"type": scene["motion_effect"]},
                }
            )
            task_id = resp.json()["data"]["task_id"]
            clips.append(await poll_clip(client, task_id))
    return clips
```

#### Stage 3：视频合成

```python
from moviepy.editor import VideoFileClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip

def assemble(clips: list[str], script: dict, country: str, output_path: str) -> str:
    tts_path = generate_tts(script["full_voiceover_script"], country)
    video = concatenate_videoclips([VideoFileClip(c) for c in clips], method="compose")
    audio = CompositeAudioClip([
        AudioFileClip(tts_path).volumex(1.0),
        AudioFileClip(get_bgm(script["bgm_style"])).volumex(0.2),
    ])
    video = video.set_audio(audio)
    video = add_captions(video, script["scenes"])
    video.write_videofile(output_path, fps=30, codec="libx264")
    return output_path

TTS_VOICES = {
    "SG": "en-SG-WayneNeural",
    "TH": "th-TH-PremwadeeNeural",
    "MY": "ms-MY-YasminNeural",
    "ID": "id-ID-ArdiNeural",
    "PH": "en-PH-RosaNeural",
}
```

---

## 4. 数据库设计

### 4.1 Schema

```sql
-- 商品主表
CREATE TABLE products (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_no      INTEGER NOT NULL,
    keyword      TEXT NOT NULL,
    title_cn     TEXT NOT NULL,
    price_cny    REAL NOT NULL,
    item_link    TEXT,
    shop_link    TEXT,
    folder_path  TEXT NOT NULL,
    status       TEXT DEFAULT 'scraped',
    -- status: scraped | text_localized | images_processed | video_done
    scraped_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 各国本土化内容表
CREATE TABLE localizations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id       INTEGER NOT NULL,
    country          TEXT NOT NULL,   -- SG/TH/MY/ID/PH
    title_local      TEXT,
    description      TEXT,
    selling_points   TEXT,            -- JSON array
    hashtags         TEXT,            -- JSON array
    price_local      REAL,
    currency         TEXT,
    exchange_rate    REAL,
    cta_text         TEXT,
    status           TEXT DEFAULT 'pending',
    -- status: pending | text_done | images_done | video_done
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(product_id) REFERENCES products(id),
    UNIQUE(product_id, country)
);

-- 规格本土化表
CREATE TABLE spec_localizations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id   INTEGER NOT NULL,
    country      TEXT NOT NULL,
    name_cn      TEXT NOT NULL,
    name_local   TEXT NOT NULL,
    price_local  REAL,
    image_path   TEXT,
    FOREIGN KEY(product_id) REFERENCES products(id)
);

-- 图片处理任务表
CREATE TABLE image_tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id   INTEGER NOT NULL,
    country      TEXT NOT NULL,
    source_path  TEXT NOT NULL,
    output_path  TEXT,
    has_text     INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'pending',
    -- status: pending | skipped | processing | done | failed
    error_msg    TEXT,
    FOREIGN KEY(product_id) REFERENCES products(id)
);

-- 视频任务表
CREATE TABLE video_tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id   INTEGER NOT NULL,
    country      TEXT NOT NULL,
    script_json  TEXT,
    video_path   TEXT,
    kling_task_id TEXT,
    status       TEXT DEFAULT 'pending',
    -- status: pending | scripting | generating | assembling | done | failed
    error_msg    TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(product_id) REFERENCES products(id)
);
```

---

## 5. 项目目录结构

> ✅ 已完成  ⬜ 待开发

```
project-root/
│
├── DESIGN.md                          # 本设计文档
├── main.py                            # 开发入口（示例调用）
├── pyproject.toml                     # 依赖声明（uv 管理）
│
├── modules/                           ✅
│   ├── __init__.py
│   │
│   ├── scraper/                       ✅ Module 1（已测试）
│   │   ├── __init__.py                # 导出 run_scraper
│   │   ├── spider.py                  # BrowserObj + Spider 类（Selenium 封装）
│   │   └── scraper.py                 # run_scraper() 函数入口
│   │
│   ├── translator/                    ⬜ Module 2
│   │   ├── __init__.py
│   │   └── localize.py               # 翻译 + 文案生成
│   │
│   ├── currency/                      ⬜ Module 4
│   │   ├── __init__.py
│   │   └── converter.py              # 汇率获取 + 定价计算
│   │
│   ├── image_processor/               ⬜ Module 3
│   │   ├── __init__.py
│   │   ├── text_translate.py         # 图片文字检测 + 翻译
│   │   └── fonts/                    # 各国字体文件
│   │       ├── NotoSans-Regular.ttf
│   │       ├── NotoSansThai-Regular.ttf
│   │       └── ...
│   │
│   └── video_generator/               ⬜ Module 4
│       ├── __init__.py
│       ├── script_writer.py          # Claude 生成视频脚本
│       ├── video_gen.py              # Kling/Runway API 调用
│       ├── assembler.py              # moviepy 视频合成
│       └── bgm/                      # 背景音乐素材
│           ├── upbeat_01.mp3
│           └── ...
│
├── pipeline.py                        ⬜ 主调度器（串联所有模块）
├── database.py                        ⬜ SQLite 封装
├── config.py                          ⬜ 全局配置（倍率/语言/模型等）
├── .env                               ⬜ API Keys（不提交 git）
├── .env.example                       ⬜ Key 模板
│
├── GetDatafrom1688/                   # 原始独立脚本（保留，勿删）
│   ├── GetCookie.py                   # 手动获取 1688 登录 Cookie
│   ├── 1688.cookie                    # Cookie 文件（需定期手动刷新）
│   ├── 1688Spider.py                  # 原交互式爬虫脚本（已被 scraper 模块取代）
│   ├── marketSpider.py                # 原 Selenium 封装（已被 spider.py 取代）
│   └── chromedriver/
│       └── chromedriver-win64/
│           └── chromedriver.exe
│
└── output/                            # run_scraper 自动创建
    └── {keyword}-1688-{YYYY-MM-DD_HH-MM}/
        ├── {keyword}-1688-{datetime}.csv   # 商品列表汇总
        ├── logs/
        │   └── 1688.log
        └── {序号}/
            ├── metadata.json               # 供后续模块消费的结构化数据
            ├── 商品详情图片/
            │   ├── 001.jpg
            │   └── ...
            ├── 商品规格/
            │   └── {规格名}——{价格}/
            │       └── 001.jpg
            └── localized/                  # M2/M3/M4 输出（待开发）
                ├── SG/
                │   ├── images/
                │   └── video.mp4
                ├── TH/
                ├── MY/
                ├── ID/
                └── PH/
```

---

## 6. 配置文件

### 6.1 config.py

```python
# config.py

COUNTRIES = ["SG", "TH", "MY", "ID", "PH"]

COUNTRY_NAMES = {
    "SG": "Singapore",
    "TH": "Thailand",
    "MY": "Malaysia",
    "ID": "Indonesia",
    "PH": "Philippines",
}

LANGUAGES = {
    "SG": "English",
    "TH": "Thai",
    "MY": "Bahasa Malaysia",
    "ID": "Bahasa Indonesia",
    "PH": "Filipino/English",
}

PRICING_CONFIG = {
    "SG": {"currency": "SGD", "markup": 3.0, "shipping_buffer": 2.0,  "round_to": 0.90},
    "TH": {"currency": "THB", "markup": 3.5, "shipping_buffer": 30,   "round_to": 9},
    "MY": {"currency": "MYR", "markup": 3.0, "shipping_buffer": 3.0,  "round_to": 0.90},
    "ID": {"currency": "IDR", "markup": 3.8, "shipping_buffer": 5000, "round_to": 1000},
    "PH": {"currency": "PHP", "markup": 3.2, "shipping_buffer": 20,   "round_to": 9},
}

TTS_VOICES = {
    "SG": "en-SG-WayneNeural",
    "TH": "th-TH-PremwadeeNeural",
    "MY": "ms-MY-YasminNeural",
    "ID": "id-ID-ArdiNeural",
    "PH": "en-PH-RosaNeural",
}

AI_CONFIG = {
    "text_model":    "deepseek-chat",      # M2: DeepSeek-V3，性价比高
    "vision_model":  "claude-sonnet-4-6",  # M3: Claude Vision 图片文字检测
    "script_model":  "claude-sonnet-4-6",  # M4: Claude 视频脚本生成
    "video_provider": "kling",             # kling | runway
    "video_duration": 30,                  # 秒
    "text_max_workers": 5,                 # M2 并发请求数
}
```

### 6.2 .env.example

```env
# DeepSeek API — Module 2 文字处理与本土化
# 获取地址：platform.deepseek.com
DEEPSEEK_API_KEY=sk-xxx

# Anthropic Claude API — Module 3 图片处理 / Module 4 视频脚本
# 获取地址：console.anthropic.com
ANTHROPIC_API_KEY=sk-ant-xxx

# 汇率 API（选填，不填使用内置备用汇率）
EXCHANGE_RATE_API_KEY=

# 视频生成（选一个）
KLING_API_KEY=
RUNWAY_API_KEY=
```

---

## 7. 完整依赖清单

```
# requirements.txt

# ── 爬虫 ──
selenium>=4.44.0
requests>=2.31.0

# ── AI 核心 ──
anthropic>=0.50.0         # Claude API（翻译/OCR/脚本）

# ── 图片处理 ──
Pillow>=10.0.0
numpy>=1.24.0
paddlepaddle-gpu             # PaddleOCR GPU 版（需 CUDA 11.8+）
paddleocr>=2.7.0             # PP-OCRv4 中文文字检测
iopaint>=1.3.0               # LaMa inpainting（文字消除）
json-repair>=0.25.0          # 健壮 JSON 解析（M2/M3 共用）

# ── 视频合成 ──
moviepy>=1.0.3
edge-tts>=6.1.9           # 免费多语言 TTS
pydub>=0.25.1

# ── 数据与工具 ──
python-dotenv>=1.0.0
tqdm>=4.65.0
httpx>=0.26.0             # 异步 HTTP（Kling API）

# ── 可选：高质量图片重绘 ──
# diffusers>=0.27.0
# torch>=2.1.0
```

---

## 8. pipeline.py 主调度器

```python
# pipeline.py
import argparse
from modules.scraper import run_scraper
from modules.translator import localize_products
from modules.image_processor import process_images
from modules.video_generator import generate_videos
from database import Database

def run_pipeline(keyword: str, start_page: int, end_page: int,
                 countries: list = None, skip_to: str = None):
    db = Database()
    countries = countries or ["SG", "TH", "MY", "ID", "PH"]

    steps = {
        "scrape":  lambda: run_scraper(keyword, start_page, end_page),
        "text":    lambda: localize_products(db.get_scraped(), countries),
        "images":  lambda: process_images(db.get_text_localized(), countries),
        "video":   lambda: generate_videos(db.get_images_processed(), countries),
    }

    start = list(steps.keys()).index(skip_to) if skip_to else 0
    for name, fn in list(steps.items())[start:]:
        print(f"\n{'='*50}\n▶  {name.upper()}\n{'='*50}")
        fn()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword",   required=True)
    parser.add_argument("--pages",     default="1-3")
    parser.add_argument("--countries", default="SG,TH,MY,ID,PH")
    parser.add_argument("--skip-to",   default=None,
                        choices=["scrape", "text", "images", "video"])
    args = parser.parse_args()

    start_p, end_p = map(int, args.pages.split("-"))
    run_pipeline(
        keyword=args.keyword,
        start_page=start_p,
        end_page=end_p,
        countries=args.countries.split(","),
        skip_to=args.skip_to,
    )
```

**使用示例：**
```bash
# 完整流程
python pipeline.py --keyword "儿童玩具" --pages 1-5

# 从文字本土化步骤重跑（跳过已完成的爬取）
python pipeline.py --keyword "儿童玩具" --pages 1-5 --skip-to text

# 只处理泰国和新加坡
python pipeline.py --keyword "儿童玩具" --pages 1-5 --countries SG,TH
```

---

## 9. 成本估算

| 模块 | 项目 | 单价 | 每个商品 × 5国 |
|------|------|------|----------------|
| M2 | DeepSeek V3 文字生成（deepseek-chat） | $0.28/MTok（输出） | ~$0.001 |
| M2 | ExchangeRate API | 免费层 | $0 |
| M3 | PaddleOCR 文字检测（本地 GPU） | 免费 | $0 |
| M3 | LaMa Inpainting 文字消除（本地 GPU） | 免费 | $0 |
| M3 | DeepSeek 图片词语翻译（按词缓存） | $0.28/MTok | ~$0.0005/图 |
| M4 | Claude 视频脚本生成（claude-sonnet-4-6） | $0.15/MTok | ~$0.003 |
| M4 | Kling AI 视频生成（30s × 5国） | ~$0.14/视频 | ~$0.70 |
| M4 | Edge TTS 配音 | 免费 | $0 |
| — | **每个商品总成本（约）** | | **~$0.71** |

> M2 切换至 DeepSeek 后文字处理成本降低约 90%；Kling AI 视频仍是最大开销。若预算有限，可先跳过 Module 4，用 moviepy 生成图片轮播视频（成本接近 $0）。

---

## 10. 实施路线图

```
✅ Week 0   Module 1  1688 商品采集（已完成，测试通过）
   Week 1   Module 2  商品文字信息处理与本土化（DeepSeek API 并发调用）
   Week 2   Module 3  商品图片信息处理与本土化（PaddleOCR + DeepSeek翻译 + LaMa + Pillow）
   Week 3   Module 4  视频脚本生成（Claude，Stage 1）
   Week 4   Module 4  AI 视频生成 + 合成（Kling + moviepy，Stage 2-3）
   Week 5   Pipeline  端到端联调 + database.py + 异常重试
   Week 6   优化       成本优化 + 并发调优 + 监控
```

---

## 11. 风险与备选方案

| 风险 | 影响 | 备选方案 |
|------|------|----------|
| Kling API 不稳定 | 视频无法生成 | 切换 Runway Gen-3 |
| 1688 反爬升级 | 采集失败 | 增加随机 UA + 代理池 |
| DeepSeek API 限速 | 翻译延迟 | 降低 max_workers + 错误重试 |
| 汇率波动剧烈 | 定价异常 | 设置每日价格变更上限 |
