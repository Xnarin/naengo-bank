"""PDF 추출 (텍스트 / 표 / 이미지 후보) -> 페이지별 JSONL + 미리보기 마크다운

규칙
- 여백 제거: 페이지 가장자리(MARGIN 비율)를 잘라내고 안쪽만 읽는다 (머리말·꼬리말·쪽번호 제거)
- 표: find_tables() -> 마크다운 표 + 바로 아래 각주
- 가짜 표: 1행 또는 1열(1행 1열 포함)은 표로 취급하지 않고 일반 텍스트로 읽는다
- 이미지: 페이지 면적 10% 초과만 후보로 기록 (Gemini/OCR 변환은 다음 단계)
- 페이지 유형: text(텍스트형) / mixed(혼합형) / scan(이미지형, 글자 없음) / empty(글자·이미지 없음)

실행
    python extract.py                 # data/ 아래 모든 PDF 추출 (이어서 실행 가능)
    python extract.py --only 앙골라    # 파일명에 포함된 것만
    python extract.py --preview-only  # JSONL로 미리보기만 다시 생성
"""

import argparse
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pdfplumber

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUT_DIR = BASE_DIR / "output" / "extracted"
JSONL_DIR = OUT_DIR / "jsonl"
PREVIEW_DIR = OUT_DIR / "preview"

# 가장자리 여백 비율 (위, 아래, 왼쪽, 오른쪽) - 쪽번호가 대부분 93.8~96.6% 높이에 있어 아래는 7%
# 여백 경계에 걸친 글자도 버리도록 crop 대신 within_bbox(완전히 안에 있는 것만) 사용
MARGIN = {"top": 0.06, "bottom": 0.07, "left": 0.03, "right": 0.03}
MIN_IMAGE_AREA_RATIO = 0.10
FOOTNOTE_PREFIXES = ("*", "※", "주:", "주)", "자료:", "출처:", "(주)", "* ")
FOOTNOTE_GAP = 25  # 표 하단에서 이 거리(pt) 안에서 시작하는 각주만 표에 붙인다

# pdfminer의 폰트 경고(Cannot set gray ...)가 너무 많아서 끈다
logging.getLogger("pdfminer").setLevel(logging.ERROR)


def normalize_cell(value):
    return " ".join((value or "").split())


def markdown_row(values):
    return "| " + " | ".join(v.replace("|", r"\|") for v in values) + " |"


def clean_rows(raw_rows):
    """빈 행·빈 열을 제거한 셀 2차원 리스트를 반환한다."""
    rows = [[normalize_cell(c) for c in row] for row in raw_rows]
    rows = [row for row in rows if any(row)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep_cols = [i for i in range(width) if any(r[i] for r in rows)]
    return [[r[i] for i in keep_cols] for r in rows]


def is_real_table(rows):
    """1행 또는 1열(1행 1열 포함)은 표가 아니라 안내 박스 등 일반 텍스트로 본다."""
    return len(rows) >= 2 and len(rows[0]) >= 2


def table_to_markdown(rows):
    headers = rows[0]
    body = []
    current_first = ""
    for row in rows[1:]:
        row = list(row)
        # 병합된 첫 열(구분) 빈칸은 직전 값으로 채운다
        if row[0]:
            current_first = row[0]
        elif any(row[1:]):
            row[0] = current_first
        body.append(row)
    lines = [markdown_row(headers), markdown_row(["---"] * len(headers))]
    lines += [markdown_row(r) for r in body]
    return headers, body, "\n".join(lines)


def find_footnotes(lines, table_bbox):
    """표 바로 아래에 이어지는 각주 줄을 찾는다."""
    footnotes = []
    last_bottom = table_bbox[3]
    for line in sorted(lines, key=lambda l: l["top"]):
        if line["top"] < table_bbox[3] - 1:
            continue
        if line["top"] - last_bottom > FOOTNOTE_GAP:
            break
        if not line["text"].strip().startswith(FOOTNOTE_PREFIXES):
            break
        footnotes.append(line)
        last_bottom = line["bottom"]
    return footnotes


def inside(obj, bbox):
    cx = (obj["x0"] + obj["x1"]) / 2
    cy = (obj["top"] + obj["bottom"]) / 2
    return bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]


def detect_columns(page):
    return layout_from_words(page.extract_words(), page.bbox)


def layout_from_words(words, bbox, min_words=40):
    """2단 편집이면 단 사이 경계 x좌표와 전체 폭 구간(제목 등)을 반환, 1단이면 None.

    가운데 30~70% 구간에서 단어가 가장 적게 걸치는 세로선을 찾고,
    걸치는 단어가 거의 없으면서 양쪽에 글이 충분하면 2단으로 본다.
    words: x0, x1, top, bottom 키를 가진 dict 목록 (OCR 글상자에도 그대로 쓴다)
    """
    if len(words) < min_words:
        return None
    x_min, x_max = bbox[0], bbox[2]
    width = x_max - x_min
    best_x, best_cross = None, None
    x = x_min + width * 0.30
    while x <= x_min + width * 0.70:
        cross = sum(1 for wd in words if wd["x0"] < x < wd["x1"])
        if best_cross is None or cross < best_cross:
            best_x, best_cross = x, cross
        x += 2
    left = sum(1 for wd in words if wd["x1"] <= best_x)
    right = sum(1 for wd in words if wd["x0"] >= best_x)
    if best_cross > len(words) * 0.03 or min(left, right) < len(words) * 0.2:
        return None

    # 경계를 가로지르는 줄(제목·초록 등)은 전체 폭 구간으로 따로 읽는다
    bands = []
    for wd in sorted((wd for wd in words if wd["x0"] < best_x < wd["x1"]), key=lambda w: w["top"]):
        if bands and wd["top"] <= bands[-1][1] + 2:
            bands[-1][1] = max(bands[-1][1], wd["bottom"])
        else:
            bands.append([wd["top"], wd["bottom"]])

    # 페이지를 위에서부터 [2단 구간, 전체 폭 구간, 2단 구간 ...]으로 나눈다
    segments, cursor = [], bbox[1]
    for top, bottom in bands:
        if top > cursor:
            segments.append((cursor, top, "cols"))
        segments.append((top, bottom, "full"))
        cursor = bottom
    segments.append((cursor, bbox[3], "cols"))
    return {"gutter": best_x, "segments": segments}


def reading_key(bbox, layout):
    x0, top, x1, bottom = bbox
    if not layout:
        return (0, 0, round(top), x0)
    cy = (top + bottom) / 2
    seg_idx = next(
        (i for i, (s0, s1, _) in enumerate(layout["segments"]) if s0 <= cy <= s1),
        len(layout["segments"]) - 1,
    )
    kind = layout["segments"][seg_idx][2]
    gutter = layout["gutter"]
    if kind == "full" or x0 < gutter < x1:
        col = 0  # 두 단에 걸친 표·이미지는 해당 구간 맨 앞에 둔다
    else:
        col = 0 if (x0 + x1) / 2 < gutter else 1
    return (seg_idx, col, round(top), x0)


def read_lines(page, layout):
    """1단은 그대로, 2단은 구간별로 왼쪽/오른쪽 단을 잘라서 줄 단위로 읽는다."""
    if not layout:
        parts = [page]
    else:
        x_min, x_max, g = page.bbox[0], page.bbox[2], layout["gutter"]
        boxes = []
        for s0, s1, kind in layout["segments"]:
            if kind == "full":
                boxes.append((x_min, s0, x_max, s1))
            else:
                boxes += [(x_min, s0, g, s1), (g, s0, x_max, s1)]
        # 글자 중심점 기준으로 나눠서 경계에 걸친 글자가 두 번 읽히지 않게 한다
        parts = [
            page.filter(lambda o, b=b: o.get("object_type") != "char" or inside(o, b))
            for b in boxes
        ]
    lines = []
    for part in parts:
        lines += [l for l in part.extract_text_lines(return_chars=False) if l["text"].strip()]
    return lines


def extract_page(page, page_no):
    w, h = page.width, page.height
    crop_box = (
        page.bbox[0] + w * MARGIN["left"],
        page.bbox[1] + h * MARGIN["top"],
        page.bbox[2] - w * MARGIN["right"],
        page.bbox[3] - h * MARGIN["bottom"],
    )
    # 여백 제거 + 굵은 글씨용 중복 글자 제거
    body = page.within_bbox(crop_box).dedupe_chars()
    # 폰트에 글자 매핑이 없으면 "(cid:123)"으로 나온다 -> 텍스트에서는 빼고, 비율이 높으면 페이지를 이미지 처리 대상으로
    n_chars = len(body.chars)
    n_cid = sum(1 for c in body.chars if c["text"].startswith("(cid:"))
    body = body.filter(lambda o: o.get("object_type") != "char" or not o["text"].startswith("(cid:"))
    broken_font = n_chars > 0 and n_cid / n_chars > 0.3
    all_lines = body.extract_text_lines(return_chars=False)

    # ---- 표 ----
    regions = []
    fake_tables = 0
    for t_idx, table in enumerate(body.find_tables(), start=1):
        rows = clean_rows(table.extract())
        if not rows:
            continue
        if not is_real_table(rows):
            # 1행/1열 -> 표 영역으로 잡지 않으므로 글자가 본문 텍스트로 그대로 읽힌다
            fake_tables += 1
            continue
        headers, body_rows, table_md = table_to_markdown(rows)
        footnote_lines = find_footnotes(all_lines, table.bbox)
        footnotes = "\n".join(l["text"] for l in footnote_lines)
        bbox = (
            table.bbox[0], table.bbox[1], table.bbox[2],
            max([table.bbox[3]] + [l["bottom"] for l in footnote_lines]),
        )
        text = table_md + (f"\n\n{footnotes}" if footnotes else "")
        regions.append({
            "content_type": "table",
            "table_id": f"page-{page_no}-table-{t_idx}",
            "bbox": bbox,
            "text": text,
            "headers": headers,
            "rows": body_rows,
            "footnotes": footnotes,
        })

    # ---- 본문 텍스트 (표 영역 밖의 글자만) ----
    table_boxes = [r["bbox"] for r in regions]
    text_page = body.filter(
        lambda o: o.get("object_type") != "char" or not any(inside(o, b) for b in table_boxes)
    )
    layout = detect_columns(text_page)
    positioned = [
        {"content_type": "text", "text": l["text"], "bbox": (l["x0"], l["top"], l["x1"], l["bottom"])}
        for l in read_lines(text_page, layout)
    ]

    # ---- 이미지 후보 (면적 10% 초과) ----
    page_area = w * h
    images = []
    # 페이지 전체를 덮는 스캔 이미지는 여백까지 걸쳐 있어 body에서 빠지므로 원본 페이지에서 찾고 여백 안쪽으로 자른다
    for i_idx, img in enumerate(page.images, start=1):
        x0, top = max(img["x0"], crop_box[0]), max(img["top"], crop_box[1])
        x1, bottom = min(img["x1"], crop_box[2]), min(img["bottom"], crop_box[3])
        if x1 <= x0 or bottom <= top:
            continue
        ratio = (x1 - x0) * (bottom - top) / page_area
        if ratio > MIN_IMAGE_AREA_RATIO:
            images.append({
                "content_type": "image",
                "image_id": f"page-{page_no}-image-{i_idx}",
                "bbox": (x0, top, x1, bottom),
                "area_ratio": round(ratio, 3),
                "text": "",  # 다음 단계(OCR/Gemini)에서 채운다
                "needs_vision": True,
            })

    # ---- 읽기 순서로 정렬하고 연속된 텍스트 줄은 합친다 ----
    # 1단: 위->아래, 왼->오 / 2단: 구간마다 왼쪽 단을 다 읽고 오른쪽 단
    positioned += [dict(r) for r in regions] + images
    positioned.sort(key=lambda b: reading_key(b["bbox"], layout))
    blocks = []
    for b in positioned:
        if blocks and b["content_type"] == "text" and blocks[-1]["content_type"] == "text":
            prev = blocks[-1]
            prev["text"] += "\n" + b["text"]
            prev["bbox"] = (
                min(prev["bbox"][0], b["bbox"][0]), min(prev["bbox"][1], b["bbox"][1]),
                max(prev["bbox"][2], b["bbox"][2]), max(prev["bbox"][3], b["bbox"][3]),
            )
        else:
            blocks.append(b)
    for idx, b in enumerate(blocks):
        b["block_id"] = f"page-{page_no}-block-{idx}"
        b["bbox"] = [round(v, 1) for v in b["bbox"]]

    char_count = len(text_page.chars) + sum(len(r["text"]) for r in regions)
    # 글자가 없는데 큰 이미지도 없는 페이지 -> 페이지 전체를 이미지 처리 대상으로 표시
    # - 글자를 벡터 곡선으로 그린 경우(아웃라인 폰트)
    # - 슬라이드가 작은 이미지 여러 조각으로 쪼개져 들어간 경우(조각마다 10% 미만)
    vector_count = len(body.curves) + len(body.rects)
    tiles_ratio = sum(
        max(0, min(im["x1"], crop_box[2]) - max(im["x0"], crop_box[0]))
        * max(0, min(im["bottom"], crop_box[3]) - max(im["top"], crop_box[1]))
        for im in page.images
    ) / page_area
    # - 폰트 매핑이 없어 글자가 (cid:N)으로 깨진 경우
    if broken_font or (char_count < 20 and not images and (vector_count > 100 or tiles_ratio > 0.3)):
        reason = "broken_font" if broken_font else ("vector_text" if vector_count > 100 else "image_tiles")
        blocks.append({
            "content_type": "image",
            "image_id": f"page-{page_no}-image-full",
            "bbox": [round(v, 1) for v in crop_box],
            "area_ratio": 1.0,
            "text": "",
            "needs_vision": True,
            "full_page_reason": reason,
            "block_id": f"page-{page_no}-block-{len(blocks)}",
        })
        images.append(blocks[-1])
    if char_count < 20:
        page_type = "scan" if images else "empty"
    elif images:
        page_type = "mixed"
    else:
        page_type = "text"

    return {
        "page_no": page_no,
        "page_type": page_type,
        "columns": 2 if layout else 1,
        "char_count": char_count,
        "n_tables": len(regions),
        "n_fake_tables": fake_tables,
        "n_images": len(images),
        "n_cid_removed": n_cid,
        "blocks": blocks,
    }


def jsonl_path_for(pdf_path):
    # 판례 파일명이 너무 길어 Windows 경로 제한(260자)에 걸리므로 80자로 자른다 (원래 이름은 file_name에 보관)
    rel = pdf_path.relative_to(DATA_DIR)
    return JSONL_DIR / rel.parent / f"{pdf_path.stem[:80]}.jsonl"


def extract_pdf(pdf_path):
    out_path = jsonl_path_for(pdf_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 이어서 실행: 이미 저장된 페이지는 건너뛴다
    done = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["page_no"])
                except (json.JSONDecodeError, KeyError):
                    pass

    domain = pdf_path.relative_to(DATA_DIR).parts[0]
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        if len(done) >= total:
            return total, 0
        with out_path.open("a", encoding="utf-8") as f:
            new = 0
            for page_no, page in enumerate(pdf.pages, start=1):
                if page_no in done:
                    continue
                try:
                    record = extract_page(page, page_no)
                except Exception as e:  # 한 페이지 실패로 전체가 멈추지 않게 기록만 남긴다
                    record = {"page_no": page_no, "page_type": "error", "error": repr(e),
                              "char_count": 0, "n_tables": 0, "n_fake_tables": 0,
                              "n_images": 0, "blocks": []}
                record = {"file_name": pdf_path.name, "domain": domain,
                          "total_pages": total, **record}
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                new += 1
            # 페이지가 많은 문서는 여기서 시간이 걸린다
    return total, new


def load_records(jsonl_file):
    with jsonl_file.open(encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    return sorted(records, key=lambda r: r["page_no"])


def write_preview(jsonl_file):
    records = load_records(jsonl_file)
    if not records:
        return None
    first = records[0]
    rel = jsonl_file.relative_to(JSONL_DIR)
    out = PREVIEW_DIR / rel.with_suffix(".md")
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# {first['file_name']}",
        "",
        f"- 분야: {first['domain']} / 페이지: {first['total_pages']}",
        f"- 표: {sum(r['n_tables'] for r in records)}개 "
        f"(1행·1열이라 텍스트로 처리: {sum(r['n_fake_tables'] for r in records)}개)",
        f"- 이미지 후보(10% 초과): {sum(r['n_images'] for r in records)}개 / "
        f"스캔 페이지: {sum(r['page_type'] == 'scan' for r in records)}개 / "
        f"OCR 완료: {sum(1 for r in records for b in r['blocks'] if 'ocr_method' in b and not b.get('needs_vision'))}개 / "
        f"Gemini 필요: {sum(1 for r in records for b in r['blocks'] if b.get('needs_vision'))}개",
        "",
    ]
    for r in records:
        lines += ["---", "", f"## p.{r['page_no']}  `{r['page_type']}`  ({r['char_count']}자)", ""]
        if r.get("error"):
            lines += [f"> ⚠ 추출 오류: {r['error']}", ""]
        for b in r["blocks"]:
            if b["content_type"] == "text":
                lines += [b["text"], ""]
            elif b["content_type"] == "table":
                lines += [f"**[표 {b['table_id']}]**", "", b["text"], ""]
            elif b["content_type"] == "figure":
                kind = {"chart": "차트", "diagram": "다이어그램", "table": "표(이미지)"}[b["figure_kind"]]
                lines += [
                    f"> 🧩 [{kind} {b['figure_id']}] — Gemini 변환 ({b['vision_method']})", "",
                    f"![{b['figure_id']}](<../../{b['image_path']}>)", "",
                    b["text"], "",
                ]
            else:
                kind = {
                    "vector_text": "글자가 벡터로 그려진 페이지 전체",
                    "image_tiles": "작은 이미지 조각으로 된 페이지 전체",
                    "broken_font": "글자가 (cid)로 깨진 페이지 전체",
                }.get(b.get("full_page_reason"), f"면적 {b['area_ratio']:.0%}")
                if "ocr_method" not in b:
                    lines += [f"> 🖼 [이미지 {b['image_id']}] {kind} — Gemini/OCR 변환 대기", ""]
                    continue
                st = b["ocr_stats"]
                status = ("Gemini 변환 완료" if b.get("vision_method")
                          else "Gemini 필요" if b.get("needs_vision") else "OCR 완료")
                lines += [
                    f"> 🖼 [이미지 {b['image_id']}] {kind} — {status} "
                    f"(표 {st.get('tables', 0)}개 / 글상자 {st['kept']}개 사용 / "
                    f"기존 텍스트와 중복 {st['dup']}개 / 평균 신뢰도 {st['score']})",
                    "",
                    f"![{b['image_id']}](<../../{b['image_path']}>)",
                    "",
                ]
                if b["text"]:
                    label = "[Gemini]" if b.get("vision_method") else "[OCR]"
                    lines += [f"**{label}**", "", b["text"], ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out, records


def write_index(summaries):
    lines = [
        "# PDF 추출 결과",
        "",
        "| 분야 | 파일 | 페이지 | 텍스트형 | 혼합형 | 스캔형 | 표 | 가짜 표→텍스트 | 이미지 후보 | 평균 글자/쪽 | 오류 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for preview, records in summaries:
        r0 = records[0]
        count = lambda t: sum(r["page_type"] == t for r in records)
        avg = sum(r["char_count"] for r in records) // max(len(records), 1)
        link = preview.relative_to(OUT_DIR).as_posix()
        lines.append(
            f"| {r0['domain']} | [{r0['file_name']}](<{link}>) | {len(records)} | "
            f"{count('text')} | {count('mixed')} | {count('scan')} | "
            f"{sum(r['n_tables'] for r in records)} | {sum(r['n_fake_tables'] for r in records)} | "
            f"{sum(r['n_images'] for r in records)} | {avg} | {count('error')} |"
        )
    (OUT_DIR / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="파일명에 이 문자열이 들어간 PDF만 처리")
    parser.add_argument("--preview-only", action="store_true")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args()

    # golden_set.csv 등은 제외하고 PDF만 읽는다
    pdfs = sorted(DATA_DIR.rglob("*.pdf"))
    if args.only:
        pdfs = [p for p in pdfs if args.only in p.name]

    if not args.preview_only:
        # 파일 단위로 병렬 처리 (파일마다 JSONL이 따로라 서로 겹치지 않는다)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(extract_pdf, p): p for p in pdfs}
            for i, fut in enumerate(as_completed(futures), start=1):
                pdf_path = futures[fut]
                total, new = fut.result()
                print(f"[{i}/{len(pdfs)}] {pdf_path.parent.name}/{pdf_path.name} - {total}쪽 (새로 추출 {new})", flush=True)

    summaries = [s for s in (write_preview(f) for f in sorted(JSONL_DIR.rglob("*.jsonl"))) if s]
    write_index(summaries)
    print(f"미리보기: {PREVIEW_DIR}  /  목록: {OUT_DIR / 'INDEX.md'}")


if __name__ == "__main__":
    main()
