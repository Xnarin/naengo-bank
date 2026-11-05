"""extract.py가 표시해 둔 이미지 영역(needs_vision)을 OCR로 텍스트화한다.

- 엔진: RapidOCR + PP-OCRv5 한국어 모델 (CPU, onnxruntime)
- 이미지 영역을 PNG로 저장 (output/extracted/images/) -> 미리보기에서 원본과 대조 가능
- 이미 PDF 글자로 추출된 부분과 겹치는 OCR 글상자는 버린다 (배경 이미지 위 텍스트 중복 방지)
- 글자가 (cid)로 깨진 페이지는 기존 텍스트·표를 버리고 OCR 결과로 대체한다
- OCR로 글자를 못 찾았거나 신뢰도가 낮으면 needs_vision=True로 남긴다 -> 다음 단계 Gemini 대상
- 표: 레이아웃 모델(PP-DocLayoutV3)로 표 영역을 찾고 표 구조 모델(SLANet+)로 행·열을 복원해
  마크다운 표로 넣는다. 1행/1열이거나 데이터 칸이 절반 넘게 비면(구조 인식 실패) 일반 OCR 텍스트로 둔다

실행
    python ocr_images.py               # 전체 (이미 OCR한 블록은 표 감지만 추가로 한다)
    python ocr_images.py --only luxury # 파일명 일부로 골라서
"""

import argparse
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pdfplumber
from bs4 import BeautifulSoup
from PIL import Image

from extract import (DATA_DIR, JSONL_DIR, OUT_DIR, inside, is_real_table, layout_from_words,
                     load_records, markdown_row, reading_key, write_index, write_preview)

IMAGES_DIR = OUT_DIR / "images"
DPI = 200
MIN_BOX_SCORE = 0.5    # 이보다 낮은 글상자는 버린다
LOW_QUALITY = 0.8      # 평균 신뢰도가 이보다 낮으면 Gemini 대상으로 남긴다
OCR_METHOD = "rapidocr-ppocrv5-korean"
MIN_TABLE_SCORE = 0.5  # 레이아웃 모델의 표 신뢰도 하한
MIN_TABLE_FILL = 0.5   # 데이터 행의 채워진 칸 비율 하한 (이보다 낮으면 구조 인식 실패로 본다)

logging.getLogger("pdfminer").setLevel(logging.ERROR)

_engine = None
_layout = None
_table = None


def get_engine():
    # 프로세스마다 한 번만 모델을 올린다
    global _engine
    if _engine is None:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
        _engine = RapidOCR(params={
            "Rec.lang_type": LangRec.KOREAN,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
            # 방향 분류기가 문단 첫 줄을 180도로 잘못 뒤집어 글자가 깨진다 (문서는 모두 정방향)
            "Global.use_cls": False,
            "Global.log_level": "warning",
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
        })
    return _engine


def get_table_models():
    global _layout, _table
    if _layout is None:
        from rapid_layout import RapidLayout
        from rapid_layout.utils.typings import ModelType as LayoutModel, RapidLayoutInput
        from rapid_table import RapidTable
        from rapid_table.utils.typings import ModelType as TableModel, RapidTableInput
        _layout = RapidLayout(cfg=RapidLayoutInput(model_type=LayoutModel.PP_DOC_LAYOUTV3))
        _table = RapidTable(RapidTableInput(model_type=TableModel.SLANETPLUS, use_ocr=True))
    return _layout, _table


def html_to_rows(html):
    """HTML 표 -> 2차원 리스트. rowspan/colspan으로 병합된 칸은 같은 값으로 채운다."""
    grid = {}
    for r_idx, tr in enumerate(BeautifulSoup(html, "html.parser").find_all("tr")):
        c_idx = 0
        for cell in tr.find_all(["td", "th"]):
            while (r_idx, c_idx) in grid:
                c_idx += 1
            text = " ".join(cell.get_text(" ").split())
            rs, cs = int(cell.get("rowspan", 1)), int(cell.get("colspan", 1))
            for dr in range(rs):
                for dc in range(cs):
                    grid[(r_idx + dr, c_idx + dc)] = text
            c_idx += cs
    if not grid:
        return []
    n_rows = max(r for r, _ in grid) + 1
    n_cols = max(c for _, c in grid) + 1
    return [[grid.get((r, c), "") for c in range(n_cols)] for r in range(n_rows)]


def find_image_tables(img, bbox, page_chars):
    """이미지 속 표를 찾아 행·열 구조로 복원한다. 표로 쓸 수 있는 것만 반환."""
    layout, table_model = get_table_models()
    lay = layout(img)
    scale = 72 / DPI
    tables = []
    for box, name, score in zip(lay.boxes or [], lay.class_names or [], lay.scores or []):
        if name != "table" or score < MIN_TABLE_SCORE:
            continue
        x0, y0, x1, y1 = [int(v) for v in box]
        x0, y0 = max(0, x0), max(0, y0)
        pdf_box = (bbox[0] + x0 * scale, bbox[1] + y0 * scale, bbox[0] + x1 * scale, bbox[1] + y1 * scale)
        # 이미 PDF 글자로 읽힌 표면 건너뛴다 (extract.py에서 처리됨)
        if sum(1 for c in page_chars if inside(c, pdf_box)) > 20:
            continue
        crop = img[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        res = get_engine()(crop)
        if res.boxes is None or not res.txts:
            continue
        out = table_model(crop, ocr_results=[(res.boxes, res.txts, res.scores)])
        rows = html_to_rows(out.pred_htmls[0]) if out.pred_htmls else []
        # 1행/1열이면 표가 아니다 (extract.py와 같은 규칙)
        if not rows or not is_real_table(rows):
            continue
        cells = [c for row in rows[1:] for c in row]
        if sum(1 for c in cells if c) / len(cells) < MIN_TABLE_FILL:
            continue
        lines = [markdown_row(rows[0]), markdown_row(["---"] * len(rows[0]))]
        lines += [markdown_row(r) for r in rows[1:]]
        tables.append({
            "px_box": (x0, y0, x1, y1),
            "bbox": [round(v, 1) for v in pdf_box],
            "layout_score": round(float(score), 3),
            "headers": rows[0],
            "rows": rows[1:],
            "text": "\n".join(lines),
        })
    return tables


def ocr_region(page, bbox, png_path, page_chars, image=None):
    """bbox 영역을 렌더링·저장하고 OCR한다. 읽기 순서로 정렬한 텍스트(표는 마크다운)와 통계를 반환."""
    if image is None:
        image = page.crop(bbox).to_image(resolution=DPI).original.convert("RGB")
        png_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(png_path)
    img = np.array(image)

    tables = find_image_tables(img, bbox, page_chars)
    res = get_engine()(img)
    boxes = res.boxes if res.boxes is not None else []
    if not len(boxes) and not tables:
        return "", {"boxes": 0, "kept": 0, "dup": 0, "score": 0.0, "tables": 0}, []

    scale = 72 / DPI  # 픽셀 -> PDF 좌표
    words, dup = [], 0
    for box, txt, score in zip(boxes, res.txts or [], res.scores or []):
        if score < MIN_BOX_SCORE or not txt.strip():
            continue
        xs, ys = box[:, 0], box[:, 1]
        # 표 안의 글상자는 표 셀로 이미 들어갔으므로 뺀다
        cx, cy = xs.mean(), ys.mean()
        if any(t["px_box"][0] <= cx <= t["px_box"][2] and t["px_box"][1] <= cy <= t["px_box"][3]
               for t in tables):
            continue
        wb = (bbox[0] + xs.min() * scale, bbox[1] + ys.min() * scale,
              bbox[0] + xs.max() * scale, bbox[1] + ys.max() * scale)
        # 이미 PDF 글자로 읽힌 영역이면 중복이므로 버린다
        n_inside = sum(1 for c in page_chars if inside(c, wb))
        if n_inside >= max(2, 0.5 * len(txt.replace(" ", ""))):
            dup += 1
            continue
        words.append({"x0": wb[0], "top": wb[1], "x1": wb[2], "bottom": wb[3],
                      "text": txt.strip(), "score": float(score)})

    # 2단 감지 후 읽기 순서로 정렬하고, 같은 줄의 글상자는 공백으로 잇는다
    layout = layout_from_words(words, bbox, min_words=10)
    key = lambda w: reading_key((w["x0"], w["top"], w["x1"], w["bottom"]), layout)
    words.sort(key=key)
    lines = []
    for w in words:
        if lines:
            prev = lines[-1]
            overlap = min(prev["bottom"], w["bottom"]) - max(prev["top"], w["top"])
            height = min(prev["bottom"] - prev["top"], w["bottom"] - w["top"])
            if key(prev)[:2] == key(w)[:2] and height > 0 and overlap > 0.5 * height:
                prev["text"] += " " + w["text"]
                prev["x1"] = max(prev["x1"], w["x1"])
                continue
        lines.append(dict(w))

    # 표를 원래 위치(읽기 순서)에 끼워 넣는다
    for t in tables:
        x0, top, x1, bottom = t["bbox"]
        lines.append({"x0": x0, "top": top, "x1": x1, "bottom": bottom, "text": t["text"], "table": True})
    lines.sort(key=key)
    text = "\n".join(f"\n{l['text']}\n" if l.get("table") else l["text"] for l in lines).strip()

    kept = len(words)
    stats = {
        "boxes": len(boxes), "kept": kept, "dup": dup,
        "score": round(sum(w["score"] for w in words) / kept, 3) if kept else 0.0,
        "tables": len(tables),
    }
    for t in tables:
        del t["px_box"]
    return text, stats, tables


def process_file(jsonl_file):
    records = load_records(jsonl_file)
    first = records[0]
    pdf_path = DATA_DIR / first["domain"] / first["file_name"]
    img_dir = IMAGES_DIR / first["domain"] / jsonl_file.stem
    done = n_tables = 0

    with pdfplumber.open(pdf_path) as pdf:
        for r in records:
            # 새로 OCR할 블록 + 예전에 OCR만 하고 표 감지는 안 한 블록
            targets = [b for b in r["blocks"] if b["content_type"] == "image" and (
                (b.get("needs_vision") and "ocr_method" not in b)
                or ("ocr_method" in b and not b.get("table_checked")))]
            if not targets:
                continue
            page = pdf.pages[r["page_no"] - 1]
            page_chars = [c for c in page.chars if not c["text"].startswith("(cid:")]
            for b in targets:
                broken = b.get("full_page_reason") == "broken_font"
                chars = [] if broken else page_chars
                png_path = img_dir / f"{b['image_id']}.png"
                image = None
                if "ocr_method" in b:
                    # 이미 OCR한 블록: 표가 없으면 기존 결과를 그대로 두고, 있을 때만 다시 OCR
                    image = Image.open(png_path).convert("RGB")
                    if not find_image_tables(np.array(image), tuple(b["bbox"]), chars):
                        b["table_checked"] = True
                        b["ocr_stats"]["tables"] = 0
                        continue
                text, stats, tables = ocr_region(page, tuple(b["bbox"]), png_path, chars, image)
                b["text"] = text
                b["image_path"] = png_path.relative_to(OUT_DIR).as_posix()
                b["ocr_method"] = OCR_METHOD
                b["ocr_stats"] = stats
                b["ocr_tables"] = tables
                b["table_checked"] = True
                # 표가 있거나 글상자가 전부 기존 텍스트와 중복 -> 처리 완료
                # 글자가 없음 또는 신뢰도 낮음 -> Gemini 대상
                if tables or (stats["kept"] == 0 and stats["dup"] > 0):
                    b["needs_vision"] = False
                else:
                    b["needs_vision"] = stats["kept"] == 0 or stats["score"] < LOW_QUALITY
                if broken:
                    # 깨진 글자로 만든 텍스트·표는 버리고 OCR 결과만 남긴다
                    r["blocks"] = [x for x in r["blocks"] if x["content_type"] == "image"]
                done += 1
                n_tables += len(tables)

    tmp = jsonl_file.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, jsonl_file)
    return first["file_name"], done, n_tables


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    files = sorted(JSONL_DIR.rglob("*.jsonl"))
    if args.only:
        files = [f for f in files if args.only in f.name]

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(process_file, f) for f in files]
        for i, fut in enumerate(as_completed(futures), start=1):
            name, done, n_tables = fut.result()
            print(f"[{i}/{len(files)}] {name} - 다시 OCR {done}곳, 표 {n_tables}개", flush=True)

    summaries = [s for s in (write_preview(f) for f in sorted(JSONL_DIR.rglob("*.jsonl"))) if s]
    write_index(summaries)
    print("미리보기 갱신 완료")


if __name__ == "__main__":
    main()
