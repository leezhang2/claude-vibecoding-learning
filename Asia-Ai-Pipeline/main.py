"""
Asia AI Pipeline — development entry point.
For production use, wire modules through pipeline.py (see DESIGN.md §8).
"""
import torch  # must be first: albumentations + iopaint import torch; pre-caching avoids shm.dll WinError 127
from iopaint.model_manager import ModelManager  # must be before paddle: initializes torch CUDA state before paddle claims GPU
import json
import os

# from modules.scraper import run_scraper
# from modules.translator import localize_products
from modules.image_processor import process_images

SESSION_DIR = r"D:\demo\llm-learning\claude-vibecoding-learning\Asia-Ai-Pipeline\output\包包-1688-2026-05-29_17-02"
ALL_COUNTRIES = ["SG", "TH", "MY", "ID", "PH"]


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


def save_product(product: dict) -> None:
    folder = product.get("folder_path")
    if not folder:
        return
    meta_path = os.path.join(folder, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(product, f, ensure_ascii=False, indent=2)

def main():
    # --- M1 scraper (已完成，暂时注释) ---
    # products = run_scraper(keyword="包包", start_page=1, end_page=2)

    # --- M2 translator (已完成，暂时注释) ---
    # results = localize_products(products, countries=ALL_COUNTRIES)

    # --- M3 image_processor 测试：取第一个商品，仅测 SG ---
    products = load_all_products(SESSION_DIR)
    first = products[:1]
    print(f"测试商品：{first[0].get('title_cn', '')[:20]}（item_no={first[0].get('item_no')}）\n")

    results = process_images(first, countries=["SG"])
    print(f"\nM3 测试完成，输出目录：")
    print(f"  {first[0]['folder_path']}\\localized\\SG\\images\\")


if __name__ == "__main__":
    main()
    os._exit(0)  # bypass torch+paddle atexit conflict on Windows