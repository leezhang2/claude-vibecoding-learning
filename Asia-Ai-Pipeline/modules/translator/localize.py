"""
Module 2 — 商品文字信息处理与多语言本土化

Flow:
  metadata.json (status: scraped)
    → Step 1: exchange-rate fetch + 5-country pricing
    → Step 2: DeepSeek API concurrent content generation
              (title / description / keywords / selling_points / hashtags / specs / cta)
    → metadata.json (status: text_localized, localization field added)
"""

import json
import logging
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import requests as http_requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from config import (  # noqa: E402
    AI_CONFIG,
    COUNTRIES,
    COUNTRY_NAMES,
    LANGUAGES,
    PRICING_CONFIG,
)

logger = logging.getLogger(__name__)

# ── DeepSeek client ───────────────────────────────────────────────────────────

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise EnvironmentError(
                "DEEPSEEK_API_KEY 未设置。"
                "请复制 .env.example 为 .env 并填入 DeepSeek API Key。"
                "获取地址：platform.deepseek.com"
            )
        _client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    return _client


# ── Prompt ────────────────────────────────────────────────────────────────────

LOCALIZE_PROMPT = """\
你是一位资深的东南亚跨境电商本土化专家，精通 {country_name} 的消费文化和 TikTok Shop 营销。

# 原始商品信息（来自1688）
- 中文原标题：{title_cn}
- 规格列表：{specs_cn}
- 批发价（人民币）：¥{price_cny}
- 本地售价：{price_local} {currency}

# 任务
请用 {language} 为 {country_name} 市场生成商品文字资料，只返回 JSON，不要加任何说明文字：

{{
  "title": "商品标题（≤80字符，含核心搜索关键词）",
  "description": "商品描述（100~150字，突出使用场景和情感价值，禁止流水账）",
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4"],
  "selling_points": [
    "卖点1（具体可感知，禁用高质量/物美价廉等泛化表达）",
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


# ── Pricing ───────────────────────────────────────────────────────────────────

_FALLBACK_RATES: dict[str, float] = {
    "SG": 0.185,
    "TH": 5.00,
    "MY": 0.63,
    "ID": 2200.0,
    "PH": 8.00,
}


@lru_cache(maxsize=16)
def _fetch_rates(date: str) -> dict[str, float]:
    """Fetch CNY→local exchange rates, cached per calendar day."""
    api_key = os.getenv("EXCHANGE_RATE_API_KEY", "")
    if not api_key:
        logger.warning("EXCHANGE_RATE_API_KEY 未设置，使用内置备用汇率（定价仅供参考）")
        return _FALLBACK_RATES
    try:
        resp = http_requests.get(
            f"https://v6.exchangerate-api.com/v6/{api_key}/latest/CNY",
            timeout=10,
        )
        resp.raise_for_status()
        cr = resp.json()["conversion_rates"]
        return {
            "SG": cr["SGD"], "TH": cr["THB"], "MY": cr["MYR"],
            "ID": cr["IDR"], "PH": cr["PHP"],
        }
    except Exception as exc:
        logger.warning("汇率 API 请求失败（%s），使用备用汇率", exc)
        return _FALLBACK_RATES


def _round_price(price: float, round_to: float) -> float:
    """Apply psychological pricing rounding.

    round_to < 1  → x.90 style  (15.90, 29.90)
    round_to == 9 → ends-in-9   (189, 299)
    round_to >= 10 → round up to nearest N  (77000 for N=1000)
    """
    if round_to < 1:
        base = math.floor(price)
        candidate = base + round_to
        return round(candidate if candidate >= price else base + 1 + round_to, 2)
    if round_to == 9:
        n = math.ceil((price - 9) / 10)
        return float(max(0, n) * 10 + 9)
    return float(math.ceil(price / round_to) * round_to)


def calculate_price(price_cny: float, country: str) -> dict:
    """Return pricing dict for one product in one country."""
    today = datetime.now().strftime("%Y-%m-%d")
    rates = _fetch_rates(today)
    cfg = PRICING_CONFIG[country]
    raw = price_cny * rates[country] * cfg["markup"] + cfg["shipping"]
    return {
        "price_local":   _round_price(raw, cfg["round_to"]),
        "currency":      cfg["currency"],
        "exchange_rate": rates[country],
        "markup":        cfg["markup"],
    }


# ── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Robustly extract a JSON object from model response text."""
    from json_repair import repair_json
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    repaired = repair_json(text, return_objects=True)
    if isinstance(repaired, dict) and repaired:
        return repaired
    raise ValueError(f"无法从模型响应中解析 JSON：{text[:300]}")


# ── Single request ────────────────────────────────────────────────────────────

def _localize_one(product: dict, country: str) -> tuple[str, str, dict | None]:
    """Call DeepSeek for one product × one country.
    Returns (item_no_str, country, result_dict | None).
    """
    price_info = calculate_price(product["price_cny"], country)
    specs_cn = ", ".join(s["name"] for s in product.get("specs", []))

    prompt = LOCALIZE_PROMPT.format(
        country_name=COUNTRY_NAMES[country],
        language=LANGUAGES[country],
        title_cn=product["title_cn"],
        specs_cn=specs_cn if specs_cn else "（无规格）",
        price_cny=product["price_cny"],
        price_local=price_info["price_local"],
        currency=price_info["currency"],
    )

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            client = _get_client()
            resp = client.chat.completions.create(
                model=AI_CONFIG["text_model"],
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8192,
                temperature=1.0,
                response_format={"type": "json_object"},
            )
            raw_text = resp.choices[0].message.content
            ai_data = _extract_json(raw_text)
            break
        except Exception as exc:
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning("[%s_%s] 第%d次失败，%ds后重试: %s",
                               product["item_no"], country, attempt, wait, exc)
                time.sleep(wait)
            else:
                logger.error("[%s_%s] 请求失败（已重试%d次）: %s",
                             product["item_no"], country, max_retries, exc)
                return str(product["item_no"]), country, None

    result = {
        **ai_data,
        "price_local":   price_info["price_local"],
        "currency":      price_info["currency"],
        "exchange_rate": price_info["exchange_rate"],
        "markup":        price_info["markup"],
        "generated_at":  datetime.now().isoformat(timespec="seconds"),
    }
    logger.info("[%s] %s 完成，售价 %s %s",
                product["item_no"], country,
                price_info["price_local"], price_info["currency"])
    return str(product["item_no"]), country, result


# ── Public API ────────────────────────────────────────────────────────────────

def localize_products(
    products: list[dict],
    countries: list[str] | None = None,
) -> list[dict]:
    """Localize text fields for *products* into each of *countries*.

    Calls DeepSeek API concurrently (up to ``text_max_workers`` threads).
    Results are written back to ``{folder_path}/metadata.json``.

    Args:
        products:  List of metadata dicts (must include ``folder_path``).
        countries: Target countries. Defaults to all five SEA countries.

    Returns:
        Updated product list with ``localization`` field populated.
    """
    countries = countries or COUNTRIES
    if not products:
        logger.info("没有商品需要处理")
        return products

    product_map = {str(p["item_no"]): p for p in products}
    tasks = [(p, c) for p in products for c in countries]
    max_workers = int(AI_CONFIG.get("text_max_workers", 5))

    logger.info("开始本土化：%d 个商品 × %d 个国家 = %d 个请求（并发数 %d）",
                len(products), len(countries), len(tasks), max_workers)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_localize_one, p, c): (p, c) for p, c in tasks}
        for future in as_completed(futures):
            item_no_str, country, result = future.result()
            if result is None:
                continue
            product = product_map[item_no_str]
            if "localization" not in product:
                product["localization"] = {}
            product["localization"][country] = result

    # Write updated metadata.json for each product
    completed = 0
    for product in products:
        if not product.get("localization"):
            continue
        folder = product.get("folder_path")
        if not folder:
            logger.warning("item_no=%s 缺少 folder_path，无法写回", product.get("item_no"))
            continue
        product["status"] = "text_localized"
        meta_path = os.path.join(folder, "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(product, f, ensure_ascii=False, indent=2)
        completed += 1
        logger.info("已写入 %s", meta_path)

    logger.info("本土化完成：%d / %d 个商品", completed, len(products))
    return products
