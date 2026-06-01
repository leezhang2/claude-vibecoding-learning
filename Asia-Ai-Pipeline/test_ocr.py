"""
OCR 检测结果可视化工具
复用 detector._get_ocr() 单例（与主流程参数完全一致）。
对指定商品的所有图片标注 OCR 结果，保存到 ocr/ 子目录。

图片标注（cv2 绘制，无 FreeType 依赖）：
  绿框 + 序号 ─ 将被处理（中文，置信度 ≥ 0.7）
  橙框 + 序号 ─ 被过滤（中文，置信度 < 0.7）
  灰框 + 序号 ─ 忽略（非中文）
  序号下方显示置信度

文字内容见终端输出（Hershey 字体不支持中文，不写入图片）。

用法：
  uv run .venv/Scripts/python.exe test_ocr.py            # 第一个商品
  uv run .venv/Scripts/python.exe test_ocr.py 3          # item_no=3
  uv run .venv/Scripts/python.exe test_ocr.py 1 2 3      # 多个商品
"""
import os
import sys
import json
from pathlib import Path

import torch  # noqa: F401 — must be first: CUDA must be claimed before paddle

SESSION_DIR = r"D:\demo\llm-learning\claude-vibecoding-learning\Asia-Ai-Pipeline\output\包包-1688-2026-05-29_17-02"


# ── 工具函数 ───────────────────────────────────────────────────────────────────

def has_chinese(text: str) -> bool:
    return any('一' <= c <= '鿿' for c in text)


def load_products(session_dir: str) -> list[dict]:
    products = []
    for item_no in sorted(os.listdir(session_dir)):
        folder = os.path.join(session_dir, item_no)
        meta = os.path.join(folder, "metadata.json")
        if os.path.exists(meta):
            with open(meta, encoding="utf-8") as f:
                p = json.load(f)
            # 始终用磁盘实际路径覆盖，避免 metadata 里存的路径因编码/迁移失效
            p["folder_path"] = folder
            products.append(p)
    return products


def collect_images(product: dict) -> list[tuple[str, str]]:
    """直接扫描商品目录，不依赖 metadata 路径字段，避免编码问题。"""
    folder = product.get("folder_path", "")
    if not os.path.isdir(folder):
        return []
    _SKIP = {"localized", "ocr"}
    images = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP)
        for fname in sorted(filenames):
            if fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                abs_path = os.path.join(dirpath, fname)
                rel = os.path.relpath(abs_path, folder)
                images.append((abs_path, rel))
    return images


# ── cv2 标注（无 FreeType，避免 Paddle/OpenCV 与 Pillow 的 DLL 冲突） ──────────

def annotate_image(image_path: str, detections: list[dict]):
    import cv2
    import numpy as np

    # imdecode 支持 Unicode 路径（cv2.imread 在 Windows 上不支持中文路径）
    img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"无法读取图片: {image_path}")

    overlay = img.copy()
    font    = cv2.FONT_HERSHEY_SIMPLEX

    for d in detections:
        pts  = [(int(x), int(y)) for x, y in d["box"]]
        npts = np.array(pts, dtype=np.int32)
        conf = d["confidence"]
        seq  = d["seq"]
        is_cn   = has_chinese(d["text"])
        will_do = is_cn and conf >= 0.7

        # BGR 颜色
        if will_do:
            color = (30,  210,  30)    # 绿
        elif is_cn:
            color = (0,   140, 255)    # 橙
        else:
            color = (160, 160, 160)    # 灰

        # 半透明填充
        cv2.fillPoly(overlay, [npts], color)

        # 描边（双层加粗）
        cv2.polylines(img, [npts], True, color, 2)
        cv2.polylines(img, [npts], True, color, 1)

        x_min = min(p[0] for p in pts)
        y_min = min(p[1] for p in pts)
        y_max = max(p[1] for p in pts)

        # 序号角标（框左上角）
        num_str = str(seq)
        (tw, th), bl = cv2.getTextSize(num_str, font, 0.45, 1)
        nx = max(0, x_min)
        ny = max(th + 6, y_min)
        cv2.rectangle(img, (nx, ny - th - 4), (nx + tw + 6, ny + bl), color, -1)
        cv2.putText(img, num_str, (nx + 3, ny - 1), font,
                    0.45, (255, 255, 255), 1, cv2.LINE_AA)

        # 置信度（框正下方）
        conf_str = f"{conf:.2f}"
        y_conf = min(img.shape[0] - 6, y_max + 16)
        cv2.putText(img, conf_str, (x_min, y_conf), font,
                    0.4, color, 1, cv2.LINE_AA)

    # 叠加半透明填充
    cv2.addWeighted(overlay, 0.15, img, 0.85, 0, img)
    return img


def save_annotated(img, out_path: Path) -> None:
    """imencode + Python file I/O，支持 Unicode 路径。"""
    import cv2
    ext = out_path.suffix.lower()
    encode_ext = ext if ext in (".jpg", ".jpeg", ".png") else ".jpg"
    params = [cv2.IMWRITE_JPEG_QUALITY, 92] if encode_ext in (".jpg", ".jpeg") else []
    ok, buf = cv2.imencode(encode_ext, img, params)
    if not ok:
        raise RuntimeError(f"imencode 失败: {out_path}")
    out_path.write_bytes(buf.tobytes())


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    # 复用 detector 模块的 OCR 单例（参数与主流程完全一致）
    from modules.image_processor.detector import _get_ocr

    all_products = load_products(SESSION_DIR)
    if not all_products:
        print("未找到商品"); return

    requested = sys.argv[1:]
    products = (
        [p for p in all_products if str(p.get("item_no")) in requested]
        if requested else all_products[:1]
    )
    if not products:
        print(f"item_no {requested} 不存在"); return

    ocr_engine = _get_ocr()

    for product in products:
        item_no = product.get("item_no")
        title   = product.get("title_cn", "")[:24]
        images  = collect_images(product)
        ocr_dir = Path(product["folder_path"]) / "ocr"
        ocr_dir.mkdir(exist_ok=True)

        print(f"\n{'─' * 62}")
        print(f"商品 {item_no}  《{title}》")
        print(f"图片数量：{len(images)}  输出：{ocr_dir}")
        print(f"{'─' * 62}")

        total_process = 0

        for img_idx, (abs_path, rel) in enumerate(images, 1):
            fname = os.path.basename(abs_path)
            rel_dir = os.path.dirname(rel)
            display = f"{rel_dir}/{fname}" if rel_dir else fname
            print(f"\n[{img_idx:02d}/{len(images)}]  {display}")

            try:
                raw = ocr_engine.ocr(abs_path, cls=True)
            except Exception as e:
                print(f"  OCR 失败: {e}")
                continue

            if not raw or not raw[0]:
                print("  (无文字)")
                continue

            detections = []
            for seq, line in enumerate(raw[0], 1):
                box, (text, conf) = line
                is_cn   = has_chinese(text)
                will_do = is_cn and conf >= 0.7
                tag     = "✓ 处理" if will_do else ("✗ 低置信" if is_cn else "─ 非中文")
                if will_do:
                    total_process += 1
                detections.append({"box": box, "text": text,
                                   "confidence": conf, "seq": seq})
                print(f"  [{seq:02d}] {tag}  {conf:.3f}  {text!r}")

            # 输出文件名保留相对路径结构（如 商品详情图片/001.jpg → 商品详情图片_001.jpg）
            safe_name = rel.replace(os.sep, "_").replace("/", "_")
            out_path  = ocr_dir / safe_name
            try:
                annotated = annotate_image(abs_path, detections)
                save_annotated(annotated, out_path)
                n_will = sum(1 for d in detections
                             if has_chinese(d["text"]) and d["confidence"] >= 0.7)
                print(f"  → {out_path.name}  "
                      f"({len(detections)} 处检测，{n_will} 处将处理)")
            except Exception as e:
                print(f"  标注失败: {e}")

        print(f"\n汇总：将替换 {total_process} 处中文区域")
        print(f"标注图片：{ocr_dir}")


if __name__ == "__main__":
    main()
    os._exit(0)
