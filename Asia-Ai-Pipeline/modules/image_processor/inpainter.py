"""
Step 3: LaMa Inpainting — 消除中文文字区域，背景自然修复
Fallback：IOPaint 不可用时，使用 Pillow 背景色填充
"""
import logging

import numpy as np
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    global _model
    if _model is None:
        try:
            from iopaint.model_manager import ModelManager
            _model = ModelManager(name="cv2", device="cpu")
            logger.info("IOPaint cv2 模型加载完成")
        except Exception as exc:
            logger.warning("IOPaint 加载失败，使用 Pillow fallback: %s", exc)
            _model = "pillow_fallback"
    return _model


def _expand_polygon(pts: list[tuple], padding: int) -> list[tuple]:
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    result = []
    for x, y in pts:
        dx, dy = x - cx, y - cy
        length = (dx**2 + dy**2) ** 0.5 or 1
        result.append((int(x + dx / length * padding), int(y + dy / length * padding)))
    return result


def _build_mask(size: tuple, regions: list[dict], padding: int = 3) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for region in regions:
        pts = [(int(x), int(y)) for x, y in region["box"]]
        draw.polygon(_expand_polygon(pts, padding), fill=255)
    return mask


def _pillow_fallback(image: Image.Image, mask: Image.Image) -> Image.Image:
    """
    用文字 bbox 外侧边缘像素的中位色填充 mask 区域。
    只采样 bbox 外侧 5px，避免将文字像素纳入背景色计算（A2 修复）。
    用 image.paste 替代 draw.bitmap，正确处理 L 模式 mask（A6 修复）。
    """
    mask_arr = np.array(mask)
    img_arr  = np.array(image)
    ys, xs   = np.where(mask_arr > 128)

    if len(xs) == 0:
        return image.copy()

    h, w = image.height, image.width
    my0, my1 = int(ys.min()), int(ys.max()) + 1
    mx0, mx1 = int(xs.min()), int(xs.max()) + 1
    pad = 5

    strips = []
    if my0 > 0:
        strips.append(img_arr[max(0, my0 - pad):my0,  mx0:mx1])
    if my1 < h:
        strips.append(img_arr[my1:min(h, my1 + pad),  mx0:mx1])
    if mx0 > 0:
        strips.append(img_arr[my0:my1, max(0, mx0 - pad):mx0])
    if mx1 < w:
        strips.append(img_arr[my0:my1, mx1:min(w, mx1 + pad)])

    if strips:
        border    = np.concatenate([s.reshape(-1, 3) for s in strips], axis=0)
        bg_color  = tuple(np.median(border, axis=0).astype(int).tolist())
    else:
        bg_color = (255, 255, 255)

    result = image.copy()
    result.paste(bg_color, mask=mask)
    return result


def erase_regions(image: Image.Image, regions: list[dict]) -> Image.Image:
    """
    消除 regions 中的文字区域，返回背景修复后的图片。
    优先使用 LaMa；不可用时 fallback 到 Pillow 背景色填充。
    """
    if not regions:
        return image

    image = image.convert("RGB")
    mask  = _build_mask(image.size, regions)
    model = _get_model()

    if model == "pillow_fallback":
        return _pillow_fallback(image, mask)

    try:
        from iopaint.schema import InpaintRequest
        img_arr = np.array(image)
        mask_arr = np.array(mask)
        result = model(
            image=img_arr,
            mask=mask_arr,
            config=InpaintRequest(),
        )
        # iopaint __call__ always returns BGR (see iopaint/model/base.py and opencv2.py)
        return Image.fromarray(result[:, :, ::-1].copy())
    except Exception as exc:
        logger.warning("LaMa 推理失败，使用 Pillow fallback: %s", exc)
        return _pillow_fallback(image, mask)
