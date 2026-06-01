import os
import os.path
import re
import sys
import time
import random
import logging
import requests
from urllib.parse import quote

from marketSpider import *


def mknewdir(dirname):
    if not os.path.exists(dirname):
        os.mkdir(os.path.join(os.getcwd(), dirname))


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
mknewdir('logs')
file_handler = logging.FileHandler(os.path.join('logs', '1688.log'), mode='a+', encoding='utf-8')
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - Line:%(lineno)d - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.info('start')


def log_status(msg):
    print(f'[状态] {msg}')
    logger.info(msg)


def clean_filename(s):
    """Windows 文件名：* 替换为 -，其余非法字符直接删除。"""
    s = str(s).replace('*', '-')
    return re.sub(r'[\\/:?"<>|\r\n]', '', s).strip()


def _get_ext(url):
    try:
        path = url.split('?')[0].rsplit('.', 1)[-1].lower()
        if path in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
            return path
    except Exception:
        pass
    return 'jpg'


_dl_session = requests.Session()
_dl_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
    'Referer': 'https://www.1688.com',
})


def download_img(url, save_path):
    if not url or not url.startswith('http'):
        return False
    try:
        resp = _dl_session.get(url, timeout=20)
        if resp.status_code == 200 and resp.content:
            with open(save_path, 'wb') as f:
                f.write(resp.content)
            return True
    except Exception as e:
        logger.warning(f'图片下载失败 {url[:60]}: {e}')
    return False


# ── 初始化 ──
keywords = input('输入搜索关键词: ')
logger.info(f'get keyword={keywords}')

browser = browserObj()
spider = Spider(keywords)

output_base = os.path.join(os.getcwd(), f'{clean_filename(keywords)}-1688-{spider.runtime}')
os.makedirs(output_base, exist_ok=True)
log_status(f'输出目录: {output_base}')

spider.init_csv_file('1688',
                     ['item_no', 'item_name', 'item_price', 'item_shop', 'shop_link', 'item_link'],
                     {'item_no': '序号', 'item_name': '商品名', 'item_price': '商品价格',
                      'item_shop': '店铺名称', 'shop_link': '店铺链接', 'item_link': '商品链接'})

log_status('启动浏览器，加载 Cookie')
browser.navi_to('https://www.1688.com')
browser.add_cookie()

log_status(f'搜索关键词: {keywords}')
search_base_url = f'https://s.1688.com/selloffer/offer_search.htm?keywords={quote(keywords, encoding="gbk")}'
browser.navi_to(search_base_url)
time.sleep(10)

browser.scroll_page()
time.sleep(3)

getPage = '?'
try:
    getPage = browser.find_css('.pagination-container .fui-paging-num').text
    logger.info(f'get 1688 have pages {getPage}')
except Exception:
    logger.warning('无法自动获取页数')

print(f'已找到 {getPage} 页，请输入爬取范围')
StartPage = int(input('起始页数: '))
EndPage = int(input('截止页数: ')) + 1
logger.info(f'get startPage{StartPage};get EndPage{EndPage - 1}')

exitSignal = False
item_no = 0  # 全局商品序号

for page in range(StartPage, EndPage):
    if page != 1:
        browser.navi_to(search_base_url + f'&beginPage={page}')

    log_status(f'正在获取第 {page} 页，共 {EndPage - StartPage} 页')

    for i in range(4):
        browser.scroll_page()
        time.sleep(3)

    try:
        goods_arr = browser.browserWin.find_elements(By.CSS_SELECTOR, '.major-offer')
        goods_length = len(goods_arr)
        if goods_length == 0:
            raise Exception('商品列表为空')
    except Exception as e:
        try:
            notifimsg = browser.browserWin.find_element(
                By.CSS_SELECTOR, '[class*="noresult"] h2').text
            if '没找到' in notifimsg:
                log_status(f'第 {page} 页无商品，退出')
                exitSignal = True
                break
        except Exception:
            pass
        log_status(f'第 {page} 页获取失败（{e}），暂停 30 秒，如有验证码请手动完成')
        logger.warning(f'page{page} error, maybe captcha')
        spider.catch_err()
        time.sleep(30)
        continue

    # ── 第一遍：在搜索结果页提取所有基本信息（跳转前必须全部提取完）──
    log_status(f'第 {page} 页找到 {goods_length} 个商品，提取基本信息')
    page_items = []
    for num, card in enumerate(goods_arr, start=1):
        try:
            item_link = card.get_attribute('href') or ''
            item_name = card.find_element(By.CSS_SELECTOR, '.offer-title-row .title-text').text
            item_price = browser.browserWin.execute_script(
                "var el = arguments[0].querySelector('.offer-price-row .col-desc');"
                "return el ? el.textContent.replace(/\\s+/g,'') : '';",
                card
            )
            item_shop = card.find_element(
                By.CSS_SELECTOR, '.offer-shop-row .col-left a .desc-text').text
            shop_link = card.find_element(
                By.CSS_SELECTOR, '.offer-shop-row .col-left a').get_attribute('href') or ''
            page_items.append({
                'item_name': item_name, 'item_price': item_price,
                'item_shop': item_shop, 'shop_link': shop_link, 'item_link': item_link,
            })
            print(f'  [{num}/{goods_length}] {item_name[:30]} | {item_price}')
        except Exception:
            logger.warning(f'item{num} page{page} 跳过')
            page_items.append(None)

    # ── 第二遍：逐个访问详情页，创建文件夹并下载图片 ──
    for item in page_items:
        if not item or not item.get('item_link'):
            continue

        item_no += 1
        spider.write_new_line({
            'item_no': item_no,
            'item_name': item['item_name'],
            'item_price': item['item_price'],
            'item_shop': item['item_shop'],
            'shop_link': item['shop_link'],
            'item_link': item['item_link'],
        })

        item_dir      = os.path.join(output_base, str(item_no))
        detail_img_dir = os.path.join(item_dir, '商品详情图片')
        spec_dir       = os.path.join(item_dir, '商品规格')
        os.makedirs(detail_img_dir, exist_ok=True)
        os.makedirs(spec_dir,       exist_ok=True)

        log_status(f'[{item_no}] 访问详情页: {item["item_name"][:25]}')
        try:
            browser.navi_to(item['item_link'])
            detail_imgs, specs = browser.scrape_detail()

            # 下载商品详情图片
            for idx, img_url in enumerate(detail_imgs, start=1):
                download_img(img_url, os.path.join(detail_img_dir, f'{idx:03d}.{_get_ext(img_url)}'))

            # 下载规格图片（规格——价格 命名文件夹）
            for spec in specs:
                folder = clean_filename(
                    f'{spec["name"]}——{spec["price"]}' if spec['price'] else spec['name']
                )
                if not folder:
                    continue
                spec_item_dir = os.path.join(spec_dir, folder)
                os.makedirs(spec_item_dir, exist_ok=True)
                for idx, img_url in enumerate(spec['images'], start=1):
                    download_img(img_url, os.path.join(spec_item_dir, f'{idx:03d}.{_get_ext(img_url)}'))

            log_status(f'[{item_no}] 完成: 详情图 {len(detail_imgs)} 张，规格 {len(specs)} 个')
        except Exception as e:
            logger.warning(f'item{item_no} detail error: {e}')

        time.sleep(random.randint(3, 8))

    if exitSignal:
        break

    if page < EndPage - 1:
        delay_time = random.randint(10, 30)
        log_status(f'随机延时 {delay_time} 秒后翻页')
        time.sleep(delay_time)

log_status('爬取完成，正在关闭')
browser.close_exit()
spider.close_exit()
print('程序结束，数据已保存')
sys.exit(0)