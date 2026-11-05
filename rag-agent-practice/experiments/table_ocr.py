"""[실험] 이미지 속 표를 표 구조 그대로 뽑기 - 레이아웃 감지 + 표 구조 인식

기존 추출 결과(output/extracted)는 읽기만 하고 수정하지 않는다.
결과: output/experiments/table_ocr/<파일명>.md

흐름 (이미지 영역마다)
  1. 레이아웃 모델(PP-DocLayoutV3)로 표 영역 찾기
  2. 표 영역만 잘라서 OCR (기존과 같은 PP-OCRv5 한국어)
  3. 표 구조 모델(SLANet+)로 행·열·병합 셀 인식 -> OCR 글자를 셀에 배치 -> HTML
  4. HTML -> 마크다운 표 (병합 셀은 값을 반복해서 채움)

실행
    python experiments/table_ocr.py 한-호주
"""

import logging
import sys
import time
from pathlib import Path

import numpy as np
from bs4 import BeautifulSoup
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
from extract import JSONL_DIR, OUT_DIR, load_records, markdown_row  # noqa: E402
from ocr_images import get_engine  # noqa: E402

EXP_DIR = BASE_DIR / "output" / "experiments" / "table_ocr"
MIN_TABLE_SCORE = 0.5

logging.getLogger("RapidOCR").setLevel(logging.WARNING)


def load_models():
    from rapid_layout import RapidLayout
    from rapid_layout.utils.typings import ModelType as LayoutModel, RapidLayoutInput
    from rapid_table import RapidTable
    from rapid_table.utils.typings import ModelType as TableModel, RapidTableInput

    layout = RapidLayout(cfg=RapidLayoutInput(model_type=LayoutModel.PP_DOC_LAYOUTV3))
    table = RapidTable(RapidTableInput(model_type=TableModel.SLANETPLUS, use_ocr=True))
    return layout, table


def html_to_rows(html):
    """HTML 표 -> 2차원 리스트. rowspan/colspan으로 병합된 칸은 같은 값으로 채운다."""
    soup = BeautifulSoup(html, "html.parser")
    grid = {}
    for r_idx, tr in enumerate(soup.find_all("tr")):
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


def rows_to_markdown(rows):
    lines = [markdown_row(rows[0]), markdown_row(["---"] * len(rows[0]))]
    lines += [markdown_row(r) for r in rows[1:]]
    return "\n".join(lines)


def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else "한-호주"
    jsonl_file = next(f for f in JSONL_DIR.rglob("*.jsonl") if keyword in f.name)
    records = load_records(jsonl_file)
    out_dir = EXP_DIR / jsonl_file.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    layout, table = load_models()
    ocr = get_engine()

    lines = [f"# [실험] 표 구조 인식 - {records[0]['file_name']}", ""]
    n_images = n_tables = 0
    t0 = time.time()
    for r in records:
        for b in r["blocks"]:
            if b["content_type"] != "image" or not b.get("image_path"):
                continue
            n_images += 1
            img = np.array(Image.open(OUT_DIR / b["image_path"]).convert("RGB"))
            lay = layout(img)
            boxes = [
                (box, score) for box, name, score in zip(lay.boxes or [], lay.class_names or [], lay.scores or [])
                if name == "table" and score >= MIN_TABLE_SCORE
            ]
            for t_idx, (box, score) in enumerate(boxes, start=1):
                x0, y0, x1, y1 = [int(v) for v in box]
                crop = img[max(0, y0):y1, max(0, x0):x1]
                res = ocr(crop)
                if res.boxes is None:
                    continue
                out = table(crop, ocr_results=[(res.boxes, res.txts, res.scores)])
                rows = html_to_rows(out.pred_htmls[0]) if out.pred_htmls else []
                if not rows:
                    continue
                n_tables += 1
                crop_name = f"p{r['page_no']}-{b['image_id']}-table{t_idx}.png"
                Image.fromarray(crop).save(out_dir / crop_name)
                lines += [
                    "---", "",
                    f"## p.{r['page_no']} {b['image_id']} 표 {t_idx}  (레이아웃 신뢰도 {score:.2f}, "
                    f"{len(rows)}행 x {len(rows[0])}열)", "",
                    f"![원본](<{out_dir.name}/{crop_name}>)", "",
                    "**[표 구조 인식 결과]**", "",
                    rows_to_markdown(rows), "",
                    "<details><summary>기존 OCR 결과(줄 단위)</summary>", "",
                    "\n".join(res.txts), "", "</details>", "",
                ]
            print(f"p.{r['page_no']} {b['image_id']}: 표 {len(boxes)}개", flush=True)

    lines[1:1] = ["", f"- 이미지 {n_images}곳 중 표 {n_tables}개 인식 / 소요 {time.time() - t0:.0f}초", ""]
    out_md = EXP_DIR / f"{jsonl_file.stem}.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"결과: {out_md}")


if __name__ == "__main__":
    main()
