"""Gemini로 보낼 그림 대상을 찾는다 (차트·다이어그램·깨진 표·OCR 실패 영역).

- 모든 페이지(여백 제거한 본문)를 렌더링해 레이아웃 모델(PP-DocLayoutV3)을 돌린다
  -> PDF에 선·도형으로 그린 벡터 차트도 렌더링된 화면 기준이라 함께 잡힌다
- chart: 모두 대상 / image: 안에 글자 상자가 4개 이상이면 다이어그램으로 대상, 아니면 사진·로고로 제외
- table: 이미지 속 표인데 표 구조 인식이 실패했거나(채택 안 됨) 빈 열이 있는 표만 대상
  (PDF 글자로 이미 읽힌 표는 제외)
- OCR 실패 영역(needs_vision=True)은 블록 전체를 대상으로 하고, 그 안의 영역은 중복이라 뺀다
- 결과: output/extracted/figures/targets.jsonl + 영역별 PNG

실행
    python find_figures.py
"""

import argparse
import json
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pdfplumber

from extract import DATA_DIR, JSONL_DIR, MARGIN, OUT_DIR, inside, load_records

FIG_DIR = OUT_DIR / "figures"
LAYOUT_DPI = 150
CROP_DPI = 200
MIN_SCORE = 0.5
MIN_AREA = 0.02        # 페이지 면적의 2% 미만 영역(아이콘 등)은 제외
MIN_DIAGRAM_TEXT = 4   # image 영역 안 글자 상자가 이보다 적으면 사진·로고로 본다

logging.getLogger("pdfminer").setLevel(logging.ERROR)

_models = None


def get_models():
    global _models
    if _models is None:
        from rapid_layout import RapidLayout
        from rapid_layout.utils.typings import ModelType, RapidLayoutInput
        from rapidocr import RapidOCR
        layout = RapidLayout(cfg=RapidLayoutInput(model_type=ModelType.PP_DOC_LAYOUTV3))
        # 글자 상자 개수만 세면 되므로 검출만 한다
        det = RapidOCR(params={"Global.use_rec": False, "Global.use_cls": False,
                               "Global.log_level": "warning"})
        _models = (layout, det)
    return _models


def iou(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    area = lambda r: max(0, r[2] - r[0]) * max(0, r[3] - r[1])
    return inter / (area(a) + area(b) - inter + 1e-9)


def contained(inner, outer, ratio=0.7):
    """inner 면적의 ratio 이상이 outer 안에 있으면 True"""
    x0, y0 = max(inner[0], outer[0]), max(inner[1], outer[1])
    x1, y1 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    return inter >= ratio * max(1e-9, (inner[2] - inner[0]) * (inner[3] - inner[1]))


def table_is_broken(t):
    """채택된 이미지 표 중 데이터 행에서 통째로 빈 열이 있으면 구조가 깨진 것으로 본다"""
    cols = len(t["headers"])
    return any(all(not row[c] for row in t["rows"]) for c in range(cols)) if t["rows"] else True


def body_box(page):
    w, h = page.width, page.height
    return (page.bbox[0] + w * MARGIN["left"], page.bbox[1] + h * MARGIN["top"],
            page.bbox[2] - w * MARGIN["right"], page.bbox[3] - h * MARGIN["bottom"])


def find_in_file(jsonl_file):
    records = load_records(jsonl_file)
    first = records[0]
    domain, stem = first["domain"], jsonl_file.stem
    pdf_path = DATA_DIR / domain / first["file_name"]
    out_dir = FIG_DIR / domain / stem
    layout, det = get_models()
    targets = []

    with pdfplumber.open(pdf_path) as pdf:
        for r in records:
            if r["page_type"] == "empty":
                continue
            page = pdf.pages[r["page_no"] - 1]
            page_area = page.width * page.height
            chars = [c for c in page.chars if not c["text"].startswith("(cid:")]
            image_blocks = [b for b in r["blocks"] if b["content_type"] == "image"]
            page_targets = []

            # OCR 실패 영역은 블록 전체를 그대로 대상으로 (PNG는 OCR 단계에서 이미 저장됨)
            for b in image_blocks:
                if b.get("needs_vision") and b.get("image_path"):
                    page_targets.append({"kind": "ocr_failed", "bbox": b["bbox"],
                                         "image_path": b["image_path"], "block_id": b["block_id"]})

            box = body_box(page)
            img = np.array(page.crop(box).to_image(resolution=LAYOUT_DPI).original.convert("RGB"))
            scale = 72 / LAYOUT_DPI
            lay = layout(img)
            for px, name, score in zip(lay.boxes or [], lay.class_names or [], lay.scores or []):
                if name not in ("chart", "image", "table") or score < MIN_SCORE:
                    continue
                pdf_box = [round(v, 1) for v in (box[0] + px[0] * scale, box[1] + px[1] * scale,
                                                 box[0] + px[2] * scale, box[1] + px[3] * scale)]
                area = (pdf_box[2] - pdf_box[0]) * (pdf_box[3] - pdf_box[1]) / page_area
                if area < MIN_AREA:
                    continue
                # OCR 실패 블록 안에 있으면 블록 전체로 이미 보내므로 제외
                if any(t["kind"] == "ocr_failed" and contained(pdf_box, t["bbox"]) for t in page_targets):
                    continue
                n_chars = sum(1 for c in chars if inside(c, pdf_box))
                if name == "table":
                    # PDF 글자로 읽힌 표는 pdfplumber가 처리 / 이미지 속 표는 구조 인식이 잘 된 것만 제외
                    if n_chars > 20:
                        continue
                    ocr_tables = [t for b in image_blocks for t in b.get("ocr_tables", [])]
                    match = [t for t in ocr_tables if iou(pdf_box, t["bbox"]) > 0.5]
                    if match and not any(table_is_broken(t) for t in match):
                        continue
                    kind = "table"
                elif name == "chart":
                    kind = "chart"
                else:
                    crop = img[int(px[1]):int(px[3]), int(px[0]):int(px[2])]
                    res = det(crop) if crop.size else None
                    n_text = len(res.boxes) if res is not None and res.boxes is not None else 0
                    if max(n_text, n_chars // 5) < MIN_DIAGRAM_TEXT:
                        continue  # 사진·로고·장식
                    kind = "diagram"
                if any(iou(pdf_box, t["bbox"]) > 0.5 for t in page_targets):
                    continue
                page_targets.append({"kind": kind, "bbox": pdf_box, "layout_score": round(float(score), 3)})

            for i, t in enumerate(page_targets, start=1):
                t["figure_id"] = f"page-{r['page_no']}-fig-{i}"
                if "image_path" not in t:
                    png = out_dir / f"{t['figure_id']}.png"
                    png.parent.mkdir(parents=True, exist_ok=True)
                    clip = (max(t["bbox"][0], page.bbox[0]), max(t["bbox"][1], page.bbox[1]),
                            min(t["bbox"][2], page.bbox[2]), min(t["bbox"][3], page.bbox[3]))
                    page.crop(clip).to_image(resolution=CROP_DPI).original.convert("RGB").save(png)
                    t["image_path"] = png.relative_to(OUT_DIR).as_posix()
                targets.append({"jsonl": jsonl_file.relative_to(JSONL_DIR).as_posix(),
                                "file_name": first["file_name"], "domain": domain,
                                "page_no": r["page_no"], **t})
    return first["file_name"], targets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    files = sorted(JSONL_DIR.rglob("*.jsonl"))
    if args.only:
        files = [f for f in files if args.only in f.name]

    all_targets = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(find_in_file, f) for f in files]
        for i, fut in enumerate(as_completed(futures), start=1):
            name, targets = fut.result()
            all_targets += targets
            kinds = {k: sum(t["kind"] == k for t in targets) for k in ("chart", "diagram", "table", "ocr_failed")}
            print(f"[{i}/{len(files)}] {name} - {kinds}", flush=True)

    all_targets.sort(key=lambda t: (t["jsonl"], t["page_no"], t["figure_id"]))
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    with (FIG_DIR / "targets.jsonl").open("w", encoding="utf-8") as f:
        for t in all_targets:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    total = {k: sum(t["kind"] == k for t in all_targets) for k in ("chart", "diagram", "table", "ocr_failed")}
    print(f"전체 {len(all_targets)}개: {total}")


if __name__ == "__main__":
    main()
