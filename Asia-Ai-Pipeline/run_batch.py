"""
M3 全量批处理：72 商品 × 5 国图片本土化
支持断点续跑：输出目录已存在且有文件则跳过。
用法：uv run .venv/Scripts/python.exe run_batch.py [--force]
  --force  忽略已有输出，强制重新处理所有商品
"""
import os
import sys
import json
import time
import logging
import traceback

import torch  # must be first
from iopaint.model_manager import ModelManager  # must be before paddle

from modules.image_processor import process_images
from modules.image_processor.renderer import shutdown_worker

# ── 配置 ──────────────────────────────────────────────────────────────────────
SESSION_DIR  = r"D:\demo\llm-learning\claude-vibecoding-learning\Asia-Ai-Pipeline\output\包包-1688-2026-05-29_17-02"
ALL_COUNTRIES = ["SG", "TH", "MY", "ID", "PH"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── 辅助函数 ──────────────────────────────────────────────────────────────────
def load_all_products(session_dir: str) -> list[dict]:
    products = []
    for item_no in sorted(os.listdir(session_dir)):
        meta_path = os.path.join(session_dir, item_no, "metadata.json")
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                p = json.load(f)
            if "folder_path" not in p:
                p["folder_path"] = os.path.join(session_dir, str(p["item_no"]))
            products.append(p)
    return products


def _output_exists(product: dict, country: str) -> bool:
    """输出目录存在且至少有一张图片则视为已完成。"""
    out_dir = os.path.join(product["folder_path"], "localized", country, "images")
    if not os.path.isdir(out_dir):
        return False
    return any(
        f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        for f in os.listdir(out_dir)
    )


def _fmt_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    force = "--force" in sys.argv

    products = load_all_products(SESSION_DIR)
    total    = len(products)
    pairs    = total * len(ALL_COUNTRIES)   # 72 × 5 = 360

    print(f"\n{'='*60}")
    print(f"  M3 全量批处理：{total} 商品 × {len(ALL_COUNTRIES)} 国 = {pairs} 任务")
    print(f"  SESSION_DIR: {SESSION_DIR}")
    print(f"  模式: {'强制重处理' if force else '断点续跑（已完成自动跳过）'}")
    print(f"{'='*60}\n")

    stats = {"done": 0, "skipped": 0, "failed": 0}
    batch_start = time.time()

    for prod_idx, product in enumerate(products, 1):
        item_no   = product.get("item_no", "?")
        title     = product.get("title_cn", "")[:18]
        to_run    = []

        for country in ALL_COUNTRIES:
            if not force and _output_exists(product, country):
                stats["skipped"] += 1
            else:
                to_run.append(country)

        if not to_run:
            print(f"[{prod_idx:02d}/{total}] item={item_no} 《{title}》 — 全部已完成，跳过")
            continue

        skipped_countries = [c for c in ALL_COUNTRIES if c not in to_run]
        skip_note = f"（跳过 {skipped_countries}）" if skipped_countries else ""
        print(f"\n[{prod_idx:02d}/{total}] item={item_no} 《{title}》 → {to_run} {skip_note}")

        t0 = time.time()
        try:
            process_images([product], countries=to_run)
            elapsed = time.time() - t0
            stats["done"] += len(to_run)
            print(f"  ✓ 完成 {to_run}  耗时 {_fmt_elapsed(elapsed)}"
                  f"  总进度 {stats['done'] + stats['skipped']}/{pairs}"
                  f"  已用 {_fmt_elapsed(time.time() - batch_start)}")
        except Exception as exc:
            elapsed = time.time() - t0
            stats["failed"] += len(to_run)
            logger.error("  ✗ item=%s 失败（%s）: %s\n%s",
                         item_no, _fmt_elapsed(elapsed), exc, traceback.format_exc())

    shutdown_worker()

    total_elapsed = time.time() - batch_start
    print(f"\n{'='*60}")
    print(f"  批处理完成  总耗时 {_fmt_elapsed(total_elapsed)}")
    print(f"  完成: {stats['done']}  跳过: {stats['skipped']}  失败: {stats['failed']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
    os._exit(0)  # bypass torch+paddle atexit conflict on Windows

