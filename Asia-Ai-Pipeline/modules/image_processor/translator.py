"""
Step 2: DeepSeek 批量翻译 OCR 识别出的中文词
结果缓存到 product["image_text_translations"][country]，避免重复调用
"""
import json
import logging
import os

from dotenv import load_dotenv
from json_repair import repair_json
from openai import OpenAI

load_dotenv()
logger = logging.getLogger(__name__)

_client = None

_COUNTRY_META = {
    "SG": ("Singapore",   "English"),
    "TH": ("Thailand",    "Thai"),
    "MY": ("Malaysia",    "Bahasa Malaysia"),
    "ID": ("Indonesia",   "Bahasa Indonesia"),
    "PH": ("Philippines", "Filipino/English"),
}

_PROMPT = """\
将以下中文电商图片文字翻译为 {language}（{country_name} 市场），保持简短口语化，符合本地消费习惯。
只返回 JSON，格式：{{"原文1": "译文1", "原文2": "译文2"}}
词语列表：{words}
"""


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise EnvironmentError("DEEPSEEK_API_KEY 未设置")
        _client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    return _client


def _call_deepseek(words: list[str], country: str) -> dict[str, str] | None:
    """
    调用 DeepSeek 翻译词列表。
    成功返回翻译 dict；失败返回 None（不缓存，允许重试，C4 修复）。
    """
    if country not in _COUNTRY_META:
        logger.error("不支持的国家代码: %s", country)
        return None
    country_name, language = _COUNTRY_META[country]
    prompt = _PROMPT.format(
        language=language,
        country_name=country_name,
        words="、".join(words),
    )
    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        return json.loads(repair_json(raw, return_objects=False))
    except Exception as exc:
        logger.error("DeepSeek 翻译失败 [%s]: %s", country, exc)
        return None


def translate_image_texts(
    words: list[str],
    product: dict,
    country: str,
) -> dict[str, str]:
    """
    翻译 words（中文列表）→ 目标国语言。
    - C2 修复：先 strip 词，防止 OCR 空白导致缓存 key 不匹配
    - C4 修复：API 失败时不写缓存，保留重试机会
    优先读取 product["image_text_translations"][country] 缓存，
    仅对未缓存的词调用 DeepSeek。
    """
    # C2: 去除 OCR 可能带入的首尾空白
    words = [w.strip() for w in words if w.strip()]
    if not words:
        return {}

    cache = (
        product
        .setdefault("image_text_translations", {})
        .setdefault(country, {})
    )
    missing = [w for w in words if w not in cache]
    if missing:
        logger.info("翻译 %d 个新词 → %s: %s", len(missing), country, missing)
        result = _call_deepseek(missing, country)
        if result is not None:          # C4: 只缓存成功结果
            cache.update(result)
    return {w: cache.get(w, w) for w in words}
