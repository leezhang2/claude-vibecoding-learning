import csv
import json
import sys
import time
import tkinter
from threading import Thread
from tkinter import filedialog, messagebox
from playsound import playsound
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
import os

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CHROMEDRIVER_PATH = os.path.join(_BASE_DIR, 'chromedriver', 'chromedriver-win64', 'chromedriver.exe')


class Spider:
    def __init__(self, keywords):
        self.csvWriter = None
        self.csvStream = None
        self.runtime = time.strftime("%Y-%m-%d_%H-%M", time.localtime())
        self.keywords = keywords

    def init_csv_file(self,market, fieldnames, cn_name):
        self.csvStream = open(f'{self.keywords}-{market}-{self.runtime}.csv', 'a', encoding='utf-8-sig', newline='')
        self.csvWriter = csv.DictWriter(self.csvStream,fieldnames=fieldnames)
        self.csvWriter.writerow(cn_name)
        self.csvStream.flush()

    def write_new_line(self, text):
        self.csvWriter.writerow(text)
        self.csvStream.flush()

    def catch_err(self):
        playsound('error.wav')

    def close_exit(self):
        self.csvStream.close()


class browserObj:
    def __init__(self):
        self.options = webdriver.ChromeOptions()

        # # 获取当前脚本所在目录的绝对路径
        # current_dir = os.path.dirname(os.path.abspath(__file__))
        # # 指定用户数据目录
        # chrome_profile = os.path.join(current_dir, "chrome_profile")
        #
        # # 确保目录存在
        # if not os.path.exists(chrome_profile):
        #     print(f"创建用户数据目录: {chrome_profile}")
        #     os.makedirs(chrome_profile)
        # else:
        #     print(f"使用已存在的用户数据目录: {chrome_profile}")
        #
        # self.options.add_argument(f'--user-data-dir={chrome_profile}')

        # 如需使用无头模式，可取消下面一行注释
        # options.headless = True
        # 添加更多反爬虫配置
        self.options.add_argument('--disable-blink-features=AutomationControlled')  # 关闭自动化标记
        self.options.add_argument('--disable-gpu')
        self.options.add_argument('--no-sandbox')
        self.options.add_argument('--disable-dev-shm-usage')
        self.options.add_argument('--window-size=1920,1080')
        self.options.add_argument(
            'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 ')

        # self.options.add_argument("--disable-blink-features=AutomationControlled")
        self.options.add_experimental_option('excludeSwitches', ['enable-logging'])
        self.options.ignore_local_proxy_environment_variables()
        service = Service(executable_path=_CHROMEDRIVER_PATH)
        self.browserWin = webdriver.Chrome(service=service, options=self.options)
        self.browserWin.implicitly_wait(8)

    def add_cookie(self):
        self.browserWin.delete_all_cookies()
        try:
            with open('1688.cookie', 'r') as f:
                cookie_list = json.load(f)
                for cookie in cookie_list:
                    self.browserWin.add_cookie(cookie)
        except:
            print('未找到Cookie')
        self.browserWin.refresh()

    def navi_to(self, url):
        self.browserWin.get(url)

    def return_javascript(self, command):
        js_return = self.browserWin.execute_script(f'return {command}')
        return js_return

    def scroll_page(self):
        self.browserWin.execute_script("document.documentElement.scrollTop=100000")

    def find_css(self, css):
        return self.browserWin.find_element(By.CSS_SELECTOR, css)

    def scrape_detail(self):
        """慢速滚动整页（触发懒加载），返回 (detail_imgs, specs)。"""
        page_h = self.browserWin.execute_script(
            'return Math.max(document.body.scrollHeight,'
            '               document.documentElement.scrollHeight)')
        for pos in range(0, page_h + 600, 400):
            self.browserWin.execute_script(f'window.scrollTo(0, {pos})')
            time.sleep(0.3)
        time.sleep(4)
        new_h = self.browserWin.execute_script(
            'return Math.max(document.body.scrollHeight,'
            '               document.documentElement.scrollHeight)')
        if new_h > page_h:
            for pos in range(page_h, new_h + 600, 400):
                self.browserWin.execute_script(f'window.scrollTo(0, {pos})')
                time.sleep(0.3)
            time.sleep(3)
        self.browserWin.execute_script(
            "document.querySelectorAll('img[data-src]').forEach(function(i){"
            "  i.src=i.getAttribute('data-src')||i.src;});"
            "window.dispatchEvent(new Event('scroll'));")
        time.sleep(2)
        specs = self._get_specs()
        detail_imgs = self._get_detail_images()
        return detail_imgs, specs

    def _get_detail_images(self):
        """点击「商品详情」Tab，用 Shadow DOM 递归提取 #offer-template-0/#detail 下的图片。"""
        # 1. 找「商品详情」文字的可点击父级元素并点击
        try:
            tab = self.browserWin.execute_script("""
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
                self.browserWin.execute_script(
                    "arguments[0].scrollIntoView(true); arguments[0].click();", tab)
                time.sleep(6)
                for pos in range(0, 20000, 400):
                    self.browserWin.execute_script(f'window.scrollTo(0, {pos})')
                    time.sleep(0.15)
                time.sleep(3)
                self.browserWin.execute_script(
                    "document.querySelectorAll('img[data-src]').forEach(function(i){"
                    "  i.src=i.getAttribute('data-src')||i.src;});")
                time.sleep(2)
        except Exception:
            pass

        # 2. Shadow DOM 递归搜索 #offer-template-0 / #detail 下的 img
        urls = self.browserWin.execute_script("""
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

    def _get_specs(self):
        """提取规格：用 JS 从每个 .expand-view-item 同时取名称和图片，
        价格来自 .price-info。"""
        import re
        specs = []

        # 价格
        price = ''
        try:
            raw = self.browserWin.find_element(
                By.CSS_SELECTOR, '.price-info').text.replace('\n', '')
            m = re.search(r'\d+\.\d+', re.sub(r'[^\d.]', '', raw))
            if m:
                price = m.group()
        except Exception:
            pass

        # 用 JS 从每个 .expand-view-item 取名称 + 图片（兼容 img 和 background-image）
        spec_data = self.browserWin.execute_script("""
            var items = document.querySelectorAll('.expand-view-item');
            var results = [];
            for (var i = 0; i < items.length; i++) {
                var item = items[i];
                var label = item.querySelector('.item-label');
                if (!label || !label.textContent.trim()) continue;
                var name = label.textContent.trim();
                var imgSrc = '';
                // 先找 img 标签
                var imgEl = item.querySelector('img');
                if (imgEl) {
                    imgSrc = imgEl.getAttribute('data-src') ||
                             imgEl.getAttribute('src') || '';
                }
                // 再找 background-image CSS
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

        # 主页面全尺寸规格图（过滤缩略图 _sum，按索引对应规格名）
        full_imgs = []
        try:
            for img in self.browserWin.find_elements(
                    By.CSS_SELECTOR, 'img[src*="cbu01.alicdn.com"]'):
                src = img.get_attribute('src') or ''
                if 'ibank' in src and '_sum' not in src and src not in full_imgs:
                    full_imgs.append(src)
        except Exception:
            pass

        if spec_data:
            for i, item in enumerate(spec_data):
                img_url = item.get('img', '')
                # JS 没拿到图时用索引匹配主页面全尺寸图
                if not img_url or not img_url.startswith('http'):
                    img_url = full_imgs[i] if i < len(full_imgs) else ''
                specs.append({
                    'name': item.get('name', ''),
                    'price': price,
                    'images': [img_url] if img_url and img_url.startswith('http') else [],
                })
            return specs

        # 回退：td.field-value 表格 + 全尺寸图按索引
        try:
            cells = self.browserWin.find_elements(By.CSS_SELECTOR, 'td.field-value')
            for i, cell in enumerate(cells):
                name = cell.text.strip()
                if name:
                    img_url = full_imgs[i] if i < len(full_imgs) else ''
                    specs.append({'name': name, 'price': price,
                                  'images': [img_url] if img_url else []})
        except Exception:
            pass
        return specs

    def close_exit(self):
        self.browserWin.close()
