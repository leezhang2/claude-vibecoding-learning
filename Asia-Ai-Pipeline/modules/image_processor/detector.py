"""
Step 1: PaddleOCR 中文文字检测
返回图片中所有含中文的文字区域及其像素级四边形坐标
"""
import logging

logger = logging.getLogger(__name__)

_ocr = None


def _get_ocr():
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(use_angle_cls=True, lang="ch")
        logger.info("PaddleOCR 加载完成")
    return _ocr


def has_chinese(text: str) -> bool:
    return any('一' <= c <= '鿿' for c in text)


def detect_chinese_regions(image_path: str) -> list[dict]:
    """
    检测图片中所有含中文字符的文字区域。
    返回列表，每项：{"text": str, "box": [[x,y]×4 顺时针], "confidence": float}
    无中文或检测失败时返回空列表。
    """
    try:
        result = _get_ocr().ocr(image_path, cls=True)
    except Exception as exc:
        logger.error("OCR 失败 %s: %s", image_path, exc)
        return []

    if not result or not result[0]:
        return []

    regions = []
    for line in result[0]:
        box, (text, confidence) = line
        if confidence >= 0.7 and has_chinese(text):
            regions.append({"text": text, "box": box, "confidence": confidence})
    return regions
