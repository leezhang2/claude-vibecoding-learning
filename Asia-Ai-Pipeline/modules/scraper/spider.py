"""
Selenium browser wrapper and CSV helper for 1688 scraping.
Extracted from GetDatafrom1688/marketSpider.py; paths are now module-relative.
"""
import csv
import json
import os
import re
import time

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_MODULE_DIR))

CHROMEDRIVER_PATH = os.path.join(
    _PROJECT_ROOT, "GetDatafrom1688", "chromedriver", "chromedriver-win64", "chromedriver.exe"
)
DEFAULT_COOKIE_PATH = os.path.join(_PROJECT_ROOT, "GetDatafrom1688", "1688.cookie")


class Spider:
    """CSV writer + runtime metadata for a scraping session."""

    def __init__(self, keywords: str, output_dir: str):
        self.keywords = keywords
        self.output_dir = output_dir
        self.runtime = time.strftime("%Y-%m-%d_%H-%M", time.localtime())
        self._csv_stream = None
        self._csv_writer = None

    def init_csv(self) -> None:
        csv_path = os.path.join(
            self.output_dir, f"{self.keywords}-1688-{self.runtime}.csv"
        )
        self._csv_stream = open(csv_path, "a", encoding="utf-8-sig", newline="")
        fieldnames = ["item_no", "item_name", "item_price", "item_shop", "shop_link", "item_link"]
        self._csv_writer = csv.DictWriter(self._csv_stream, fieldnames=fieldnames)
        self._csv_writer.writerow({
            "item_no": "序号", "item_name": "商品名", "item_price": "商品价格",
            "item_shop": "店铺名称", "shop_link": "店铺链接", "item_link": "商品链接",
        })
        self._csv_stream.flush()

    def write_row(self, row: dict) -> None:
        if self._csv_writer:
            self._csv_writer.writerow(row)
            self._csv_stream.flush()

    def close(self) -> None:
        if self._csv_stream:
            self._csv_stream.close()
            self._csv_stream = None


class BrowserObj:
    """Selenium Chrome wrapper for 1688 with anti-detection settings."""

    def __init__(self, cookie_path: str = DEFAULT_COOKIE_PATH):
        self.cookie_path = cookie_path
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
        )
        options.add_experimental_option("excludeSwitches", ["enable-logging"])
        options.ignore_local_proxy_environment_variables()
        service = Service(executable_path=CHROMEDRIVER_PATH)
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.implicitly_wait(8)

    def load_cookies(self) -> None:
        self.driver.delete_all_cookies()
        try:
            with open(self.cookie_path, "r") as f:
                for cookie in json.load(f):
                    self.driver.add_cookie(cookie)
            self.driver.refresh()
        except Exception:
            print("[警告] 未找到 Cookie 文件，将以未登录状态运行")

    def get(self, url: str) -> None:
        self.driver.get(url)

    def scroll_to_bottom(self) -> None:
        self.driver.execute_script("document.documentElement.scrollTop=100000")

    def find(self, css: str):
        return self.driver.find_element(By.CSS_SELECTOR, css)

    def scrape_detail(self) -> tuple[list[str], list[dict]]:
        """Slow-scroll to trigger lazy-load; return (detail_img_urls, specs)."""
        page_h = self.driver.execute_script(
            "return Math.max(document.body.scrollHeight,"
            "               document.documentElement.scrollHeight)"
        )
        for pos in range(0, page_h + 600, 400):
            self.driver.execute_script(f"window.scrollTo(0, {pos})")
            time.sleep(0.3)
        time.sleep(4)

        new_h = self.driver.execute_script(
            "return Math.max(document.body.scrollHeight,"
            "               document.documentElement.scrollHeight)"
        )
        if new_h > page_h:
            for pos in range(page_h, new_h + 600, 400):
                self.driver.execute_script(f"window.scrollTo(0, {pos})")
                time.sleep(0.3)
            time.sleep(3)

        self.driver.execute_script(
            "document.querySelectorAll('img[data-src]').forEach(function(i){"
            "  i.src=i.getAttribute('data-src')||i.src;});"
            "window.dispatchEvent(new Event('scroll'));"
        )
        time.sleep(2)

        specs = self._get_specs()
        detail_imgs = self._get_detail_images()
        return detail_imgs, specs

    def _get_detail_images(self) -> list[str]:
        """Click the '商品详情' tab then recursively extract images via Shadow DOM."""
        try:
            tab = self.driver.execute_script("""
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    if (el.children.length === 0 &&
                        el.textContent.trim() === '商品详情') {
                        var p = el;
                        for (var j = 0; j < 6; j++) {
                            if (!p || !p.parentElement) break;
                            p = p.parentElement;
                            var tag = p.tagName.toLowerCase();
                            var cls = (p.className||'').toString().toLowerCase();
                            if (tag.includes('tab') || tag === 'li' || tag === 'a' ||
                                cls.includes('tab') || cls.includes('nav') || p.onclick)
                                return p;
                        }
                        return el.parentElement;
                    }
                }
                return null;
            """)
            if tab:
                self.driver.execute_script(
                    "arguments[0].scrollIntoView(true); arguments[0].click();", tab
                )
                time.sleep(6)
                for pos in range(0, 20000, 400):
                    self.driver.execute_script(f"window.scrollTo(0, {pos})")
                    time.sleep(0.15)
                time.sleep(3)
                self.driver.execute_script(
                    "document.querySelectorAll('img[data-src]').forEach(function(i){"
                    "  i.src=i.getAttribute('data-src')||i.src;});"
                )
                time.sleep(2)
        except Exception:
            pass

        urls = self.driver.execute_script("""
            function getImgsFromEl(el) {
                var imgs = [];
                var all = el.querySelectorAll ? el.querySelectorAll('img') : [];
                for (var k = 0; k < all.length; k++) {
                    var s = all[k].getAttribute('data-src') ||
                            all[k].getAttribute('src') || '';
                    if (s && s.startsWith('http')) imgs.push(s);
                }
                return imgs;
            }
            function searchShadow(root) {
                var found = [];
                var els = root.querySelectorAll ? root.querySelectorAll('*') : [];
                for (var i = 0; i < els.length; i++) {
                    var el = els[i];
                    if (el.id === 'offer-template-0' || el.id === 'detail')
                        found = found.concat(getImgsFromEl(el));
                    if (el.shadowRoot)
                        found = found.concat(searchShadow(el.shadowRoot));
                }
                return found;
            }
            return searchShadow(document);
        """)
        return list(dict.fromkeys(urls or []))

    def _get_specs(self) -> list[dict]:
        """Extract product specs: name, price string, and image URL list."""
        price_str = ""
        try:
            raw = self.find(".price-info").text.replace("\n", "")
            m = re.search(r"\d+\.\d+", re.sub(r"[^\d.]", "", raw))
            if m:
                price_str = m.group()
        except Exception:
            pass

        spec_data = self.driver.execute_script("""
            var items = document.querySelectorAll('.expand-view-item');
            var results = [];
            for (var i = 0; i < items.length; i++) {
                var item = items[i];
                var label = item.querySelector('.item-label');
                if (!label || !label.textContent.trim()) continue;
                var name = label.textContent.trim();
                var imgSrc = '';
                var imgEl = item.querySelector('img');
                if (imgEl) {
                    imgSrc = imgEl.getAttribute('data-src') ||
                             imgEl.getAttribute('src') || '';
                }
                if (!imgSrc) {
                    var els = item.querySelectorAll('*');
                    for (var j = 0; j < els.length; j++) {
                        var bg = window.getComputedStyle(els[j]).backgroundImage;
                        if (bg && bg !== 'none' && bg.indexOf('url') === 0) {
                            var m = bg.match(/url\\(["\']?(.+?)["\']?\\)/);
                            if (m) { imgSrc = m[1]; break; }
                        }
                    }
                }
                results.push({name: name, img: imgSrc});
            }
            return results;
        """)

        full_imgs = []
        try:
            for img in self.driver.find_elements(By.CSS_SELECTOR, 'img[src*="cbu01.alicdn.com"]'):
                src = img.get_attribute("src") or ""
                if "ibank" in src and "_sum" not in src and src not in full_imgs:
                    full_imgs.append(src)
        except Exception:
            pass

        specs = []
        if spec_data:
            for i, item in enumerate(spec_data):
                img_url = item.get("img", "")
                if not img_url or not img_url.startswith("http"):
                    img_url = full_imgs[i] if i < len(full_imgs) else ""
                specs.append({
                    "name": item.get("name", ""),
                    "price": price_str,
                    "images": [img_url] if img_url and img_url.startswith("http") else [],
                })
            return specs

        try:
            cells = self.driver.find_elements(By.CSS_SELECTOR, "td.field-value")
            for i, cell in enumerate(cells):
                name = cell.text.strip()
                if name:
                    img_url = full_imgs[i] if i < len(full_imgs) else ""
                    specs.append({
                        "name": name,
                        "price": price_str,
                        "images": [img_url] if img_url else [],
                    })
        except Exception:
            pass
        return specs

    def close(self) -> None:
        self.driver.close()
