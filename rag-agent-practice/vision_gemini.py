"""find_figures.py가 찾은 그림 대상을 Gemini로 마크다운 변환해 JSONL에 반영한다.

- chart    -> 값은 마크다운 표 + 요약
- diagram  -> 박스 글자는 그대로, 흐름은 →, 계층은 들여쓰기 목록 + 요약
- table    -> 마크다운 표 (병합 셀 값 반복)
- ocr_failed -> 종류를 먼저 판단해 위 규칙대로 / 사진·로고는 한 줄 설명
- 결과는 output/extracted/figures/results.jsonl에 하나씩 저장 (중간에 끊겨도 이어서 실행)
- 반영: ocr_failed는 기존 이미지 블록의 text를 교체, 나머지는 페이지에 figure 블록으로 추가

실행
    python vision_gemini.py                 # 전체
    python vision_gemini.py --limit 5       # 앞에서 5개만 (품질 확인용)
    python vision_gemini.py --merge-only    # 저장된 결과로 JSONL·미리보기만 다시 반영
"""

import argparse
import base64
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

from extract import BASE_DIR, JSONL_DIR, OUT_DIR, load_records, write_index, write_preview
from find_figures import FIG_DIR

TARGETS = FIG_DIR / "targets.jsonl"
RESULTS = FIG_DIR / "results.jsonl"
DEFAULT_MODEL = "gemini-3.6-flash"

COMMON = """첨부한 이미지는 한국어 문서(PDF)의 한 영역입니다. RAG 검색용 마크다운으로 변환하세요.
- 이미지에 적힌 글자는 그대로 옮기고, 요약하거나 생략하지 마세요.
- 이미지에 없는 내용을 추측해서 덧붙이지 마세요. 읽을 수 없는 부분은 [확인 불가]로 표시하세요.
- 결과 전체를 코드 블록으로 감싸지 마세요.
"""

PROMPTS = {
    "chart": COMMON + """- 이 이미지는 차트(그래프)입니다.
- 첫 줄: `### [차트] 차트 제목` (제목이 없으면 내용을 보고 짧게 붙이고 끝에 (제목 없음) 표시)
- 단위, 축 이름, 범례를 적으세요.
- 값은 마크다운 표로 작성하세요. 가로축 항목을 행, 계열(범례)을 열로 둡니다.
- 데이터 라벨로 적힌 값은 그대로 쓰고, 눈금으로 어림한 값은 뒤에 (추정)을 붙이세요.
- 마지막 줄: `요약:` 뒤에 추세나 핵심 비교를 1~2문장으로.
""",
    "diagram": COMMON + """- 이 이미지는 다이어그램(도형·흐름도·구조도)입니다.
- 첫 줄: `### [다이어그램] 제목` (제목이 없으면 내용을 보고 짧게 붙이고 끝에 (제목 없음) 표시)
- 박스·도형 안의 글자를 빠짐없이 옮기세요.
- 화살표로 이어진 관계는 `A → B`, 포함·계층 관계는 들여쓰기 목록으로 쓰세요.
- 단계나 순서가 있으면 그 순서대로 쓰세요.
- 마지막 줄: `요약:` 뒤에 구조를 한 문장으로.
""",
    "table": COMMON + """- 이 이미지는 표입니다.
- 첫 줄: `### [표] 표 제목` (제목이 없으면 (제목 없음))
- 열 이름과 값의 관계가 드러나는 마크다운 표로 작성하세요.
- 병합된 셀은 해당되는 모든 칸에 같은 값을 반복해 넣으세요.
- 수치, 단위, 각주(*, ※, 주:, 자료:)를 보존하세요.
""",
    "ocr_failed": COMMON + """- 먼저 이미지 종류를 판단하세요.
- 사진·로고·장식·일러스트처럼 정보가 없는 이미지면 `[이미지] 한 줄 설명`만 쓰세요.
- 차트면 `### [차트] 제목` + 값을 마크다운 표(어림한 값은 (추정)) + `요약:` 한 줄.
- 다이어그램이면 `### [다이어그램] 제목` + 박스 글자를 빠짐없이, 관계는 →, 계층은 들여쓰기 목록 + `요약:` 한 줄.
- 표면 마크다운 표로, 병합 셀은 값을 반복.
- 글(문단)이면 제목과 본문을 읽기 순서대로 그대로 옮기세요.
- 한 이미지에 여러 종류가 섞여 있으면 위에서 아래 순서로 각각 위 규칙대로 쓰세요.
""",
}

_lock = threading.Lock()


def target_key(t):
    return f"{t['jsonl']}#{t['figure_id']}"


def load_done():
    done = {}
    if RESULTS.exists():
        for line in RESULTS.open(encoding="utf-8"):
            try:
                r = json.loads(line)
                done[r["key"]] = r
            except (json.JSONDecodeError, KeyError):
                pass
    return done


def make_llm(model):
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(model=model, timeout=120, max_retries=2, temperature=0)


def convert(llm, t):
    from langchain_core.messages import HumanMessage
    png = (OUT_DIR / t["image_path"]).read_bytes()
    message = HumanMessage(content=[
        {"type": "text", "text": PROMPTS[t["kind"]]},
        {"type": "image", "base64": base64.b64encode(png).decode("ascii"), "mime_type": "image/png"},
    ])
    for attempt in range(4):
        try:
            resp = llm.invoke([message])
            text = resp.text if isinstance(resp.text, str) else resp.text()
            usage = getattr(resp, "usage_metadata", None) or {}
            return text.strip(), {"input_tokens": usage.get("input_tokens"),
                                  "output_tokens": usage.get("output_tokens")}
        except Exception as e:  # 속도 제한 등 -> 잠깐 쉬고 재시도
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
            last = e
    raise last


def run(model, workers, limit):
    targets = [json.loads(l) for l in TARGETS.open(encoding="utf-8")]
    done = load_done()
    todo = [t for t in targets if target_key(t) not in done]
    if limit:
        todo = todo[:limit]
    print(f"대상 {len(targets)}개 / 완료 {len(done)}개 / 이번 실행 {len(todo)}개 (모델: {model})", flush=True)
    if not todo:
        return
    llm = make_llm(model)
    n_ok = n_err = 0
    with ThreadPoolExecutor(max_workers=workers) as pool, RESULTS.open("a", encoding="utf-8") as out:
        futures = {pool.submit(convert, llm, t): t for t in todo}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                text, usage = fut.result()
                rec = {"key": target_key(t), "text": text, "model": model, "usage": usage}
                with _lock:
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()
                n_ok += 1
            except Exception as e:
                n_err += 1
                print(f"  실패 {target_key(t)}: {repr(e)[:150]}", flush=True)
            if (n_ok + n_err) % 20 == 0:
                print(f"  진행 {n_ok + n_err}/{len(todo)} (실패 {n_err})", flush=True)
    print(f"완료 {n_ok}개 / 실패 {n_err}개", flush=True)


def merge():
    """결과를 페이지 JSONL에 반영한다. 여러 번 실행해도 같은 결과가 나오게 figure 블록은 지우고 다시 넣는다."""
    targets = [json.loads(l) for l in TARGETS.open(encoding="utf-8")]
    done = load_done()
    by_file = {}
    for t in targets:
        if target_key(t) in done:
            by_file.setdefault(t["jsonl"], []).append(t)

    for jsonl_rel, items in by_file.items():
        path = JSONL_DIR / jsonl_rel
        records = load_records(path)
        pages = {r["page_no"]: r for r in records}
        for r in records:
            r["blocks"] = [b for b in r["blocks"] if b["content_type"] != "figure"]
        for t in items:
            res = done[target_key(t)]
            r = pages[t["page_no"]]
            if t["kind"] == "ocr_failed":
                for b in r["blocks"]:
                    if b.get("block_id") == t["block_id"]:
                        b["text"] = res["text"]
                        b["needs_vision"] = False
                        b["vision_method"] = res["model"]
                continue
            block = {
                "content_type": "figure", "figure_kind": t["kind"], "figure_id": t["figure_id"],
                "bbox": t["bbox"], "image_path": t["image_path"], "text": res["text"],
                "vision_method": res["model"], "block_id": f"page-{t['page_no']}-{t['figure_id']}",
            }
            # 읽기 순서: 그림 위쪽 좌표보다 위에서 시작한 블록들 뒤에 넣는다
            pos = sum(1 for b in r["blocks"] if b["bbox"][1] <= t["bbox"][1])
            r["blocks"].insert(pos, block)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, path)

    summaries = [s for s in (write_preview(f) for f in sorted(JSONL_DIR.rglob("*.jsonl"))) if s]
    write_index(summaries)
    print(f"JSONL 반영: {len(by_file)}개 파일 / 미리보기 갱신 완료")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--merge-only", action="store_true")
    args = parser.parse_args()

    load_dotenv(BASE_DIR / ".env", override=True)
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    if not args.merge_only:
        if not os.getenv("GOOGLE_API_KEY"):
            raise SystemExit(".env에 GOOGLE_API_KEY가 없습니다.")
        run(model, args.workers, args.limit)
    merge()


if __name__ == "__main__":
    main()
