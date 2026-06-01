"""
Module 3 入口 — 商品图片本土化处理
流程：PaddleOCR检测 → DeepSeek翻译 → LaMa消除 → Pillow渲染
"""
import json
import logging
import os
import shutil

from PIL import Image

from config import COUNTRIES
from .detector import detect_chinese_regions
from .inpainter import erase_regions
from .renderer import annotate_regions_with_style, render_text
from .translator import translate_image_texts

logger = logging.getLogger(__name__)


def _collect_images(product: dict) -> list[tuple[str, str]]:
    """
    收集商品所有图片，返回 (abs_path, rel_path) 元组列表。
    保留 rel_path 避免在 _process_product_country 中用 os.path.relpath 重新推导，
    防止 folder_path 为空时产生含 .. 的危险路径（F5 修复）。
    """
    folder = product.get("folder_path", "")
    images: list[tuple[str, str]] = []
    for rel in product.get("detail_images", []):
        abs_path = os.path.join(folder, rel)
        if os.path.exists(abs_path):
            images.append((abs_path, rel))
    for spec in product.get("specs", []):
        rel = spec.get("image_path", "")
        if rel:
            abs_path = os.path.join(folder, rel)
            if os.path.exists(abs_path):
                images.append((abs_path, rel))
    return images


def _process_single_image(
    src_path: str,
    dst_path: str,
    product: dict,
    country: str,
) -> bool:
    """
    处理一张图片。
    无中文 → 直接复制（返回 False）。
    有中文 → OCR + 翻译 + LaMa + Pillow（返回 True）。
    """
    dst_dir = os.path.dirname(dst_path)
    if dst_dir:
        os.makedirs(dst_dir, exist_ok=True)

    regions = detect_chinese_regions(src_path)
    if not regions:
        shutil.copy2(src_path, dst_path)
        return False

    words        = [r["text"] for r in regions]
    translations = translate_image_texts(words, product, country)

    image = Image.open(src_path).convert("RGB")
    annotate_regions_with_style(image, regions)  # 消除前采样原图文字颜色
    image = erase_regions(image, regions)
    image = render_text(image, regions, translations, country)
    image.save(dst_path, quality=92)

    logger.info("[%s_%s] 替换 %d 处文字: %s",
                product.get("item_no"), country,
                len(regions), os.path.basename(src_path))
    return True


def _process_product_country(product: dict, country: str) -> None:
    folder = product.get("folder_path", "")
    images = _collect_images(product)
    if not images:
        logger.warning("[%s] 未找到任何图片", product.get("item_no"))
        return

    replaced = copied = 0
    for src_path, rel in images:          # F5: 直接使用已知 rel，无需 relpath
        dst_path = os.path.join(folder, "localized", country, "images", rel)
        try:
            if _process_single_image(src_path, dst_path, product, country):
                replaced += 1
            else:
                copied += 1
        except Exception as exc:
            logger.error("[%s_%s] 处理失败 %s: %s",
                         product.get("item_no"), country,
                         os.path.basename(src_path), exc)

    logger.info("[%s_%s] 完成：%d 张替换 / %d 张复制",
                product.get("item_no"), country, replaced, copied)


def _save_product(product: dict) -> None:
    folder = product.get("folder_path", "")
    if not folder:
        return
    meta_path = os.path.join(folder, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(product, f, ensure_ascii=False, indent=2)


def process_images(
    products: list[dict],
    countries: list[str] | None = None,
) -> list[dict]:
    """
    Module 3 公开接口：对所有商品图片执行本土化处理。

    Args:
        products:  metadata dict 列表（须含 folder_path）
        countries: 目标国家列表，默认全部五国

    Returns:
        更新后的 products（image_text_translations 已写入，status → images_processed）
    """
    countries = countries or COUNTRIES
    logger.info("开始图片本土化：%d 个商品 × %d 国", len(products), len(countries))

    for idx, product in enumerate(products, 1):
        item_no = product.get("item_no")
        for country in countries:
            logger.info("[%d/%d] item_no=%s → %s", idx, len(products), item_no, country)
            _process_product_country(product, country)

        product["status"] = "images_processed"
        _save_product(product)
        print(f"[{item_no}] 完成 {countries}")

    logger.info("全部图片处理完成：%d 个商品", len(products))
    return products
