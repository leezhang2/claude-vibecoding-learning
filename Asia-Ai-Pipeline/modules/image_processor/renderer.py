"""
Step 4: 渲染本地化文字
通过 multiprocessing.spawn 子进程调用 Pillow/FreeType，避免主进程中
iopaint/OpenCV FreeType DLL 污染导致的 0xC0000005 崩溃。
文字颜色从原图检测（annotate_regions_with_style），字号与原文保持一致。
"""
import io
import logging
import multiprocessing
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_FONTS_DIR = Path(__file__).parent / "fonts"
_FONT_FILES = {
    "SG": "NotoSans-Regular.ttf",
    "TH": "NotoSans-Regular.ttf",   # 泰文字符已被过滤；Latin 用 NotoSans
    "MY": "NotoSans-Regular.ttf",
    "ID": "NotoSans-Regular.ttf",
    "PH": "NotoSans-Regular.ttf",
}

# ── 字符过滤 ───────────────────────────────────────────────────────────────────
_NON_LATIN_RANGES = [
    (0x4E00, 0x9FFF), (0x3000, 0x303F), (0x3400, 0x4DBF),
    (0x0E00, 0x0E7F), (0xAC00, 0xD7AF),
    (0x0400, 0x04FF), (0x0600, 0x06FF), (0x0900, 0x097F),
]

_PUNCT_MAP: dict[str, str] = {
    '·': '-',  ''': "'",  ''': "'",  '"': '"',  '"': '"',
    '–': '-',  '—': '--', '…': '...','é': 'e',  'è': 'e',
    'ê': 'e',  'à': 'a',  'â': 'a',  'ä': 'a',  'ñ': 'n',
    'ü': 'u',  'ö': 'o',  'ó': 'o',  'ú': 'u',  'í': 'i',
    'á': 'a',  'ã': 'a',  'õ': 'o',
}


def _has_non_latin(text: str) -> bool:
    for c in text:
        cp = ord(c)
        if any(lo <= cp <= hi for lo, hi in _NON_LATIN_RANGES):
            return True
    return False


def _to_ascii(text: str) -> str:
    return ''.join(
        _PUNCT_MAP.get(c, c) if ord(c) >= 128 else c
        for c in text if ord(c) < 128 or c in _PUNCT_MAP
    ).strip()


# ── 原图文字颜色检测（在消除前调用） ────────────────────────────────────────────

def _detect_text_color(image: Image.Image, box: list) -> tuple[int, int, int]:
    """
    从原图 bounding box 检测文字颜色。
    策略：用背景亮度决定从"最暗"还是"最亮"像素簇中取文字色，
    避免依赖距离阈值（JPEG 压缩噪点会使阈值方案失准）。
    """
    arr = np.array(image.convert("RGB"))
    h, w = arr.shape[:2]
    xs = [p[0] for p in box]; ys = [p[1] for p in box]
    x0, y0 = max(0, int(min(xs))), max(0, int(min(ys)))
    x1 = min(w, int(max(xs))); y1 = min(h, int(max(ys)))

    if x1 <= x0 or y1 <= y0:
        return (20, 20, 20)

    # 背景色：bbox 外侧 5px 边框的中位色
    pad = 5
    strips = []
    if y0 > 0:   strips.append(arr[max(0,y0-pad):y0,  x0:x1])
    if y1 < h:   strips.append(arr[y1:min(h,y1+pad),  x0:x1])
    if x0 > 0:   strips.append(arr[y0:y1, max(0,x0-pad):x0])
    if x1 < w:   strips.append(arr[y0:y1, x1:min(w,x1+pad)])
    bg = (np.median(np.concatenate([s.reshape(-1,3) for s in strips], axis=0), axis=0)
          if strips else np.array([255., 255., 255.]))
    bg_lum = 0.299*bg[0] + 0.587*bg[1] + 0.114*bg[2]

    box_px  = arr[y0:y1, x0:x1].reshape(-1, 3).astype(float)
    px_lum  = 0.299*box_px[:,0] + 0.587*box_px[:,1] + 0.114*box_px[:,2]

    if bg_lum > 128:
        # 亮背景（白/浅色）→ 取亮度最低的 15% 像素 = 深色文字
        thresh  = np.percentile(px_lum, 15)
        text_px = box_px[px_lum <= thresh]
    else:
        # 暗背景（黑/深色）→ 取亮度最高的 15% 像素 = 浅色/彩色文字
        thresh  = np.percentile(px_lum, 85)
        text_px = box_px[px_lum >= thresh]

    if len(text_px) < 3:
        return (20, 20, 20) if bg_lum > 128 else (240, 240, 240)

    color = np.median(text_px, axis=0).astype(int)
    return (int(color[0]), int(color[1]), int(color[2]))


def annotate_regions_with_style(image: Image.Image, regions: list[dict]) -> None:
    """
    从原图（消除前）为每个 region 检测文字颜色，写入 region["detected_color"]。
    必须在 erase_regions 之前调用。
    """
    for region in regions:
        region["detected_color"] = _detect_text_color(image, region["box"])


# ── Worker 进程主函数 ──────────────────────────────────────────────────────────
# 定义在模块顶层以支持 spawn 序列化。
# renderer.py 不在顶层 import cv2/iopaint，子进程导入本模块时不会加载
# OpenCV 的 FreeType DLL，避免与 Pillow FreeType 冲突。

def _worker_main(
    in_q: "multiprocessing.Queue",
    out_q: "multiprocessing.Queue",
    fonts_dir: str,
    font_files: dict,
) -> None:
    """子进程主循环：Pillow/FreeType 渲染，无 iopaint 依赖。"""
    from PIL import Image, ImageDraw, ImageFont  # noqa

    font_cache: dict = {}

    def load_font(country: str, size: int):
        key = (country, size)
        if key not in font_cache:
            fp = Path(fonts_dir) / font_files.get(country, "NotoSans-Regular.ttf")
            try:
                font_cache[key] = ImageFont.truetype(str(fp), size) if fp.exists() else ImageFont.load_default()
            except Exception:
                # 字体文件损坏时降级
                noto = Path(fonts_dir) / "NotoSans-Regular.ttf"
                font_cache[key] = (ImageFont.truetype(str(noto), size)
                                   if noto.exists() else ImageFont.load_default())
        return font_cache[key]

    while True:
        task = in_q.get()
        if task is None:
            break
        try:
            img_bytes, regions, translations, country = task
            image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            draw  = ImageDraw.Draw(image)

            for region in regions:
                local_text = translations.get(region["text"], "")
                if not local_text or _has_non_latin(local_text):
                    continue
                safe = _to_ascii(local_text)
                if not safe:
                    continue

                xs, ys = [p[0] for p in region["box"]], [p[1] for p in region["box"]]
                x, y   = int(min(xs)), int(min(ys))
                box_w  = int(max(xs) - min(xs))
                box_h  = int(max(ys) - min(ys))

                # 原图检测到的文字颜色（每个区域独立）
                fg = region.get("detected_color") or (20, 20, 20)

                # 字号：以 box_h 为起点，再按 box_w 缩放使文字填满原始宽度
                font_size = max(box_h - 2, 8)
                font = load_font(country, font_size)
                text_w = draw.textlength(safe, font=font)
                if text_w > 0 and box_w > 0:
                    # 允许放大至 2× 填满较短译文，或缩小以适配较长译文
                    scaled = int(font_size * (box_w / text_w))
                    font_size = max(6, min(scaled, font_size * 2))
                    font = load_font(country, font_size)

                # anchor="lt"：左-上角对齐，坐标与 OCR bounding box 一致
                draw.text((x, y), safe, fill=fg, font=font, anchor="lt")

            buf = io.BytesIO()
            image.save(buf, format="PNG")
            out_q.put(("ok", buf.getvalue()))
        except Exception as exc:
            out_q.put(("err", str(exc)))


# ── Worker 生命周期 ────────────────────────────────────────────────────────────

_worker_proc: Optional["multiprocessing.Process"] = None
_in_queue:    Optional["multiprocessing.Queue"]   = None
_out_queue:   Optional["multiprocessing.Queue"]   = None


def _ensure_worker() -> None:
    global _worker_proc, _in_queue, _out_queue
    if _worker_proc is not None and _worker_proc.is_alive():
        return
    ctx        = multiprocessing.get_context("spawn")
    _in_queue  = ctx.Queue()
    _out_queue = ctx.Queue()
    _worker_proc = ctx.Process(
        target=_worker_main,
        args=(_in_queue, _out_queue, str(_FONTS_DIR), dict(_FONT_FILES)),
        daemon=True,
        name="renderer-worker",
    )
    _worker_proc.start()
    logger.info("Renderer worker 启动 (pid=%s)", _worker_proc.pid)


def shutdown_worker() -> None:
    global _worker_proc, _in_queue, _out_queue
    if _in_queue is not None:
        try: _in_queue.put(None)
        except Exception: pass
    if _worker_proc is not None:
        _worker_proc.join(timeout=5)
        if _worker_proc.is_alive():
            _worker_proc.terminate()
    _worker_proc = _in_queue = _out_queue = None


# ── cv2 fallback（主进程，worker 不可用时） ────────────────────────────────────

def _render_cv2_fallback(
    image: Image.Image,
    regions: list[dict],
    translations: dict[str, str],
) -> Image.Image:
    import cv2
    img_arr   = cv2.cvtColor(np.array(image, copy=True), cv2.COLOR_RGB2BGR)
    h_img, w_img = img_arr.shape[:2]

    for region in regions:
        local_text = translations.get(region["text"], "")
        if not local_text or _has_non_latin(local_text):
            continue
        safe = _to_ascii(local_text)
        if not safe:
            continue

        xs, ys  = [p[0] for p in region["box"]], [p[1] for p in region["box"]]
        x, y    = int(min(xs)), int(min(ys))
        box_w   = int(max(xs) - min(xs))
        box_h   = int(max(ys) - min(ys))

        # 原图检测到的颜色转为 BGR
        detected = region.get("detected_color")
        if detected:
            fg = (detected[2], detected[1], detected[0])   # RGB → BGR
        else:
            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(w_img, x+box_w), min(h_img, y+box_h)
            region_arr = img_arr[y0:y1, x0:x1].reshape(-1, 3).astype(float)
            lum = (0.299*region_arr[:,2] + 0.587*region_arr[:,1] + 0.114*region_arr[:,0]).mean()
            fg  = (20, 20, 20) if lum > 128 else (240, 240, 240)

        font_face  = cv2.FONT_HERSHEY_SIMPLEX
        thickness  = max(1, box_h // 25)
        # 以 box_h 为起点，按 box_w 缩放字号以填满原始宽度
        font_scale = max(0.3, box_h / 30.0)
        (tw, _), _ = cv2.getTextSize(safe, font_face, font_scale, thickness)
        if tw > 0 and box_w > 0:
            font_scale = max(0.3, font_scale * min(box_w / tw, 2.0))

        (_, th), _ = cv2.getTextSize(safe, font_face, font_scale, thickness)
        cv2.putText(img_arr, safe, (x, y + th), font_face,
                    font_scale, fg, thickness, cv2.LINE_AA)

    return Image.fromarray(cv2.cvtColor(img_arr, cv2.COLOR_BGR2RGB))


# ── 公开接口 ───────────────────────────────────────────────────────────────────

def render_text(
    image: Image.Image,
    regions: list[dict],
    translations: dict[str, str],
    country: str,
) -> Image.Image:
    """
    渲染本地化文字。文字颜色来自 region["detected_color"]（须在消除前由
    annotate_regions_with_style 写入）；字号与原文 bbox 高度一致。
    通过子进程避免 FreeType DLL 冲突；失败时降级为 cv2 fallback。
    """
    _ensure_worker()

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    _in_queue.put((buf.getvalue(), regions, translations, country))

    try:
        status, data = _out_queue.get(timeout=60)
    except Exception as exc:
        logger.warning("Worker 无响应，使用 cv2 fallback: %s", exc)
        return _render_cv2_fallback(image, regions, translations)

    if status == "err":
        logger.warning("Worker 渲染失败，使用 cv2 fallback: %s", data)
        return _render_cv2_fallback(image, regions, translations)

    return Image.open(io.BytesIO(data))
