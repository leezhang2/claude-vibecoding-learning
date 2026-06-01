"""
1688 product scraper — callable module entry point.
Replaces the interactive GetDatafrom1688/1688Spider.py with a function API.
"""
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime
from urllib.parse import quote

import requests

from .spider import BrowserObj, Spider, DEFAULT_COOKIE_PATH

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, "output")

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _clean_filename(s: str) -> str:
    """Replace * with -, strip other Windows-illegal chars."""
    s = str(s).replace("*", "-")
    return re.sub(r'[\\/:?"<>|\r\n]', "", s).strip()


def _get_ext(url: str) -> str:
    try:
        path = url.split("?")[0].rsplit(".", 1)[-1].lower()
        if path in ("jpg", "jpeg", "png", "gif", "webp"):
            return path
    except Exception:
        pass
    return "jpg"


def _parse_price(raw: str) -> float:
    """Extract the first float from a price string like '¥5.01~¥9.99'."""
    if not raw:
        return 0.0
    cleaned = re.sub(r"[^\d.]", ".", raw)
    m = re.search(r"\d+\.\d+", cleaned)
    return float(m.group()) if m else 0.0


_dl_session = requests.Session()
_dl_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.1688.com",
})


def _download_img(url: str, save_path: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    try:
        resp = _dl_session.get(url, timeout=20)
        if resp.status_code == 200 and resp.content:
            with open(save_path, "wb") as f:
                f.write(resp.content)
            return True
    except Exception as e:
        logger.warning("图片下载失败 %s: %s", url[:60], e)
    return False


# ── public API ────────────────────────────────────────────────────────────────

def run_scraper(
    keyword: str,
    start_page: int,
    end_page: int,
    output_dir: str | None = None,
    cookie_path: str | None = None,
) -> list[dict]:
    """
    Scrape 1688 products for *keyword* from page *start_page* to *end_page* (inclusive).

    Args:
        keyword:     Chinese search keyword.
        start_page:  First page index (1-based).
        end_page:    Last page index (inclusive).
        output_dir:  Root folder for all output.  Defaults to ``output/`` in project root.
        cookie_path: Path to the 1688.cookie JSON file.

    Returns:
        List of ``metadata`` dicts — one per scraped product.
        Each dict is also written to ``{item_dir}/metadata.json``.
    """
    output_dir = output_dir or _DEFAULT_OUTPUT_DIR
    cookie_path = cookie_path or DEFAULT_COOKIE_PATH
    os.makedirs(output_dir, exist_ok=True)

    # ── session directory: output/{keyword}-1688-{date_time}/ ──
    runtime = time.strftime("%Y-%m-%d_%H-%M", time.localtime())
    session_name = f"{_clean_filename(keyword)}-1688-{runtime}"
    session_dir = os.path.join(output_dir, session_name)
    os.makedirs(session_dir, exist_ok=True)

    # ── file logging ──
    log_dir = os.path.join(session_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    fh = logging.FileHandler(os.path.join(log_dir, "1688.log"), mode="a", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)

    def log(msg: str) -> None:
        print(f"[状态] {msg}")
        logger.info(msg)

    log(f"关键词: {keyword}  页面范围: {start_page}-{end_page}  输出目录: {session_dir}")

    spider = Spider(keyword, session_dir)
    spider.init_csv()

    browser = BrowserObj(cookie_path=cookie_path)

    try:
        log("加载首页，注入 Cookie")
        browser.get("https://www.1688.com")
        browser.load_cookies()

        search_url = (
            "https://s.1688.com/selloffer/offer_search.htm"
            f"?keywords={quote(keyword, encoding='gbk')}"
        )
        browser.get(search_url)
        time.sleep(10)
        browser.scroll_to_bottom()
        time.sleep(3)

        all_metadata: list[dict] = []
        item_no = 0

        for page in range(start_page, end_page + 1):
            if page != 1:
                browser.get(search_url + f"&beginPage={page}")

            log(f"获取第 {page} 页")
            for _ in range(4):
                browser.scroll_to_bottom()
                time.sleep(3)

            # ── collect card info from search results (before navigating away) ──
            try:
                from selenium.webdriver.common.by import By
                goods = browser.driver.find_elements(By.CSS_SELECTOR, ".major-offer")
                if not goods:
                    raise ValueError("商品列表为空")
            except Exception as exc:
                log(f"第 {page} 页获取失败 ({exc})，跳过")
                logger.warning("page%d error: %s", page, exc)
                time.sleep(30)
                continue

            page_items = []
            for card in goods:
                try:
                    page_items.append({
                        "item_link": card.get_attribute("href") or "",
                        "item_name": card.find_element(
                            By.CSS_SELECTOR, ".offer-title-row .title-text"
                        ).text,
                        "item_price": browser.driver.execute_script(
                            "var el = arguments[0].querySelector"
                            "('.offer-price-row .col-desc');"
                            "return el ? el.textContent.replace(/\\s+/g,'') : '';",
                            card,
                        ),
                        "item_shop": card.find_element(
                            By.CSS_SELECTOR, ".offer-shop-row .col-left a .desc-text"
                        ).text,
                        "shop_link": card.find_element(
                            By.CSS_SELECTOR, ".offer-shop-row .col-left a"
                        ).get_attribute("href") or "",
                    })
                except Exception:
                    logger.warning("搜索结果页提取商品信息失败，跳过该卡片")
                    page_items.append(None)

            # ── visit each detail page ──
            for item in page_items:
                if not item or not item.get("item_link"):
                    continue

                item_no += 1
                spider.write_row({
                    "item_no": item_no,
                    "item_name": item["item_name"],
                    "item_price": item["item_price"],
                    "item_shop": item["item_shop"],
                    "shop_link": item["shop_link"],
                    "item_link": item["item_link"],
                })

                item_dir = os.path.join(session_dir, str(item_no))
                detail_img_dir = os.path.join(item_dir, "商品详情图片")
                spec_dir = os.path.join(item_dir, "商品规格")
                os.makedirs(detail_img_dir, exist_ok=True)
                os.makedirs(spec_dir, exist_ok=True)

                log(f"[{item_no}] 访问详情页: {item['item_name'][:25]}")
                detail_image_paths: list[str] = []
                spec_metadata: list[dict] = []

                try:
                    browser.get(item["item_link"])
                    detail_imgs, specs = browser.scrape_detail()

                    # download detail images
                    for idx, url in enumerate(detail_imgs, start=1):
                        fname = f"{idx:03d}.{_get_ext(url)}"
                        if _download_img(url, os.path.join(detail_img_dir, fname)):
                            detail_image_paths.append(f"商品详情图片/{fname}")

                    # download spec images
                    for spec in specs:
                        folder = _clean_filename(
                            f'{spec["name"]}——{spec["price"]}' if spec["price"] else spec["name"]
                        )
                        if not folder:
                            continue
                        spec_item_dir = os.path.join(spec_dir, folder)
                        os.makedirs(spec_item_dir, exist_ok=True)

                        first_image_path = ""
                        for idx, url in enumerate(spec["images"], start=1):
                            fname = f"{idx:03d}.{_get_ext(url)}"
                            if _download_img(url, os.path.join(spec_item_dir, fname)):
                                rel = f"商品规格/{folder}/{fname}"
                                if not first_image_path:
                                    first_image_path = rel

                        spec_metadata.append({
                            "name": spec["name"],
                            "price_cny": _parse_price(spec["price"]),
                            "image_path": first_image_path,
                        })

                    log(
                        f"[{item_no}] 完成: 详情图 {len(detail_image_paths)} 张，"
                        f"规格 {len(spec_metadata)} 个"
                    )
                except Exception as exc:
                    logger.warning("item%d detail error: %s", item_no, exc)

                metadata = {
                    "item_no": item_no,
                    "keyword": keyword,
                    "title_cn": item["item_name"],
                    "price_cny": _parse_price(item["item_price"]),
                    "shop_name": item["item_shop"],
                    "item_link": item["item_link"],
                    "shop_link": item["shop_link"],
                    "folder_path": item_dir,
                    "specs": spec_metadata,
                    "detail_images": detail_image_paths,
                    "scraped_at": datetime.now().isoformat(timespec="seconds"),
                    "status": "scraped",
                }
                with open(os.path.join(item_dir, "metadata.json"), "w", encoding="utf-8") as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=2)

                all_metadata.append(metadata)
                time.sleep(random.randint(3, 8))

            if page < end_page:
                delay = random.randint(10, 30)
                log(f"随机延时 {delay} 秒后翻页")
                time.sleep(delay)

    finally:
        browser.close()
        spider.close()
        logger.removeHandler(fh)
        fh.close()

    log(f"爬取完成，共获取 {len(all_metadata)} 个商品，输出目录: {session_dir}")
    return all_metadata
