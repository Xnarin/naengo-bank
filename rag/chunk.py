"""data/rag 원천 데이터 → 청크 JSONL (data/rag/chunks.jsonl)

원천이 이미 텍스트(Markdown·CSV·JSON)라 PDF 추출(OCR·표 인식)은 필요 없다. 문서 구조 단위로 자른다.
- 법령: `##### 제N조` 단위. 부칙은 뺀다 (경과규정이라 고객 질문과 무관).
- 약관: `제N조(` 단위. 맨 앞 전문(前文)도 한 청크.
- FAQ: 질문·답변 1쌍 = 1청크 / 용어집: 용어 1개 = 1청크
- 내금고 상품(src/data/mock.ts → bank/내금고상품.json): 상품 1개 = 1청크
- 상품(finlife): 상품 1개 = 1청크 (가입조건·우대조건·기간별 금리)

조항이 MAX_CHARS를 넘으면 항(①②…)·호 단위 문단을 묶어서 나누고, 조각마다 "[문서] 제N조(제목)" 머리말을 반복한다.
겹침 없이 머리말을 반복하는 이유: 조항 경계가 이미 의미 경계라 글자 수 겹침보다 출처 표시가 정확하다.

실행 (bank_clone 폴더에서): python rag/chunk.py
"""

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data" / "rag"
OUT = ROOT / "chunks.jsonl"
MAX_CHARS = 800  # 이전 실습에서 500~1000 구간이 Hit@5 차이가 작았다. 조항 하나가 대부분 이 안에 들어간다

# 법률의 기관 운영 장(章)은 뺀다: 예금보험공사 조직·회계, 부실금융회사 정리, 업자 등록·허가·감독, 보칙.
# 고객 질문에 답이 될 일이 없고 "예금", "보험금" 같은 단어가 많아 검색 상위를 차지한다. 장이 없는 시행령은 그대로 둔다.
# 벌칙 장은 넣는다: "통장 빌려주면 처벌받나요?" 같은 실제 질문이 많다 (전자금융거래법 제49조).
EXCLUDE_CHAPTER_WORDS = ("예금보험공사", "부실금융회사", "등록", "허가", "감독", "보칙")

# 기업은행 용어집(퇴직연금 계리 용어 위주)에서 고객이 물어볼 만한 용어만 남긴다
GLOSSARY_KEEP = {
    "개인퇴직계좌 (IRP)", "확정급여형(DB)", "확정기여형(DC)", "퇴직연금제도", "퇴직금제도", "퇴직금중간정산제도", "중도인출",
    "세제혜택", "퇴직급여", "평균임금", "연금", "원리금", "원리금보장", "복리(Compound interest)", "예금", "예금자보호제도",
    "외화예금", "실적배당형 상품", "펀드(fund)", "주식형펀드", "채권형펀드", "혼합형펀드(balanced fund)", "인덱스펀드(index fund)",
    "분산투자", "수익률", "환매", "환매수수료", "환매조건부채권", "CD", "CMA", "MMF(Money Market Fund)", "질권", "저당권",
    "신탁(trust)", "특정금전신탁", "신용평가기관",
}

JOIN_DENY ={"1": "제한없음", "2": "서민전용", "3": "일부제한"}
PRODUCT_KIND = {
    "depositProductsSearch": "정기예금",
    "savingProductsSearch": "적금",
    "creditLoanProductsSearch": "신용대출",
    "rentHouseLoanProductsSearch": "전세자금대출",
    "mortgageLoanProductsSearch": "주택담보대출",
}
CREDIT_BANDS = {
    "crdt_grad_1": "900점 초과", "crdt_grad_4": "801~900점", "crdt_grad_5": "701~800점", "crdt_grad_6": "601~700점",
    "crdt_grad_10": "501~600점", "crdt_grad_11": "401~500점", "crdt_grad_12": "301~400점", "crdt_grad_13": "300점 이하",
}
PRODUCT_FIELDS = {  # finlife 필드 → 사람이 읽는 이름 (빈 값은 생략)
    "join_way": "가입방법", "join_member": "가입대상", "max_limit": "최고한도", "mtrt_int": "만기 후 이자율",
    "spcl_cnd": "우대조건", "etc_note": "유의사항", "cb_name": "신용평가사", "loan_lmt": "대출한도",
    "loan_inci_expn": "부대비용", "erly_rpay_fee": "중도상환수수료", "dly_rate": "연체이자율",
}


def strip_history(text):
    """개정 이력 태그 <개정 2016.5.29> [본조신설 2021.1.5] 제거. 시행일은 metadata에 있고, 검색엔 날짜 숫자만 잡음이 된다."""
    text = re.sub(r"[ \t]*<(?:개정|신설|전문개정|본조신설|제목개정)[^>]*>", "", text)
    return re.sub(r"[ \t]*\[(?:본조신설|전문개정|제목개정|본조제목개정)[^\]]*\]", "", text)


def clean_md(text):
    text = re.sub(r"\*\*([①-⑳])\*\*", r"\1", text)  # **①** → ①
    text = text.replace("\\.", ".")  # 1\. → 1.
    text = re.sub(r"^[ \t]*\S{1,3}\.\s*삭제\s*<[^>]*>[ \t]*\n?", "", strip_history(text), flags=re.M)  # "4. 삭제 <2020.12.29>"
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def pack(header, body):
    """본문을 항(①②…) 단위로 MAX_CHARS 이하로 묶는다.
    항 하나가 넘치면(정의 조항 등) 호(1. 2. …) 단위로 다시 묶고, 조각마다 항 첫 문장을 붙인다
    ("보험금 지급한도는 1억원으로 한다" 같은 항 본문이 뒤쪽 호 조각에서도 보이도록)."""
    def greedy(segs, prefix=""):
        out, cur = [], ""
        for s in segs:
            if cur and len(header) + len(prefix) + len(cur) + len(s) > MAX_CHARS:
                out.append(cur)
                cur = ""
            cur = f"{cur}\n{s}" if cur else s
        return out + [cur]

    if len(header) + len(body) <= MAX_CHARS:
        return [f"{header}\n{body}"]
    parts = []
    for para in greedy(re.split(r"\n(?=[①-⑳])", body)):
        if len(header) + len(para) <= MAX_CHARS:
            parts.append(para)
            continue
        lead, *items = re.split(r"\n(?=\s*\d+\.\s)", para)
        groups = greedy(items, lead)
        parts += [f"{lead}\n{g}" for g in groups] if items else [para]
    return [f"{header}\n{p.strip()}" for p in parts]


def frontmatter(md):
    m = re.match(r"---\n(.*?)\n---\n", md, re.S)
    meta = dict(re.findall(r"^(\S+): '?([^'\n]*)'?$", m.group(1), re.M)) if m else {}
    return meta, md[m.end():] if m else md


def law_chunks(path):
    meta, body = frontmatter(path.read_text(encoding="utf-8"))
    body = body.split("\n## 부칙")[0]
    name = meta.get("제목", path.stem)
    base = {"source_type": "law", "doc": name, "effective_date": meta.get("시행일자"), "url": meta.get("출처")}
    chapter = section = None
    for block in re.split(r"\n(?=#{2,5} )", body):
        head, _, text = block.partition("\n")
        if head.startswith(("## ", "### ")):
            title = strip_history(head.lstrip("# ")).strip()
            if re.match(r"제\d+장", title):
                chapter, section = title, None
            else:
                section = title  # 절은 장 아래에 붙인다
            continue
        m = re.match(r"##### (제\d+조(?:의\d+)?) \((.*?)\)", head)
        text = re.sub(r"\*\*[①-⑳]\*\* 삭제 <[^>]*>\n*", "", text)  # 삭제된 항만 지운다
        if not m or not text.strip() or text.strip().startswith("삭제"):
            continue
        if chapter and any(w in chapter for w in EXCLUDE_CHAPTER_WORDS):
            continue
        header = f"[{name}] {m.group(1)}({m.group(2)})"
        for t in pack(header, clean_md(text)):
            yield t, {**base, "article": m.group(1), "title": m.group(2), "chapter": " > ".join(x for x in (chapter, section) if x) or None}


def terms_chunks(path):
    lines = path.read_text(encoding="utf-8").split("\n\n")
    name = lines[0].strip()
    base = {"source_type": "terms", "doc": name, "effective_date": "2024-09-27", "url": "https://www.ftc.go.kr/www/selectBbsNttList.do?bordCd=201&key=202"}
    body = "\n".join(lines[1:])
    pieces = re.split(r"\n(?=제\d+조(?:의\d+)?\s*\()", body)  # 제9조의2(휴면예금) 같은 가지 조문도 나눈다
    yield f"[{name}] 전문\n{pieces[0].strip()}", {**base, "article": "전문", "title": "전문"}
    for p in pieces[1:]:
        m = re.match(r"(제\d+조(?:의\d+)?)\s*\(([^)]*)\)\s*", p)
        title = m.group(2).strip()
        if all(len(w) == 1 for w in title.split()):
            title = title.replace(" ", "")  # 글자 사이 띄운 제목 "입 금" → "입금"
        for t in pack(f"[{name}] {m.group(1)}({title})", p[m.end():].strip()):
            yield t, {**base, "article": m.group(1), "title": title}


def faq_chunks(path):
    for r in csv.DictReader(path.open(encoding="utf-8")):
        q, a = r["질문 내용"].strip(), r["답변 내용"].strip()
        if "대상 금액" in q:  # 2024-07 자료라 상한이 5천만원으로 낡음 (현재 1억원, 생활법령정보). 내금고 FAQ가 대신 답한다
            continue
        yield f"[착오송금 반환지원 FAQ] ({r['질문 구분']})\nQ. {q}\nA. {a}", {
            "source_type": "faq", "doc": "예금보험공사 착오송금 반환지원제도 FAQ", "title": q, "url": "https://www.data.go.kr/data/15130623/fileData.do"}


def bank_faq_chunks(path):
    """내금고 자체 FAQ (md): ## 카테고리 / ### 질문 / 답변. [정책 미정] 표시는 검토용이라 청크에서 뺀다."""
    md = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)
    category = None
    for block in re.split(r"\n(?=##+ )", md):
        head, _, body = block.partition("\n")
        if head.startswith("## "):
            category = head[3:].strip()
        elif head.startswith("### "):
            q, a = head[4:].strip(), re.sub(r"\s*\[정책 미정[^\]]*\]", "", body).strip()
            yield f"[내금고 FAQ] ({category})\nQ. {q}\nA. {a}", {"source_type": "faq", "doc": "내금고 자주 묻는 질문", "title": q, "category": category}


def glossary_chunks(path):
    seen = set()
    for r in csv.DictReader(path.open(encoding="utf-8")):
        term, desc = r["용 어"].strip(), r["설 명"].strip()
        if term not in GLOSSARY_KEEP or (term, desc) in seen:  # 원본에 같은 용어가 두 번 있는 경우도 거른다
            continue
        seen.add((term, desc))
        yield f"[금융용어] {term}\n{desc}", {"source_type": "glossary", "doc": "중소기업은행 금융용어해설", "title": term, "url": "https://www.data.go.kr/data/15045457/fileData.do"}


def rate_line(o):
    if "save_trm" in o:  # 예금·적금
        kind = f"{o.get('rsrv_type_nm')} " if o.get("rsrv_type_nm") else ""
        return f"- {o['save_trm']}개월 {kind}{o['intr_rate_type_nm']}: 기본 {o['intr_rate']}% / 최고 {o['intr_rate2']}%"
    if "crdt_grad_avg" in o:  # 신용대출: 신용점수 구간별 금리 (finlife 필드 정의)
        bands = [(CREDIT_BANDS[k], o[k]) for k in CREDIT_BANDS if o.get(k) is not None]
        return f"- {o['crdt_lend_rate_type_nm']}: 평균 {o['crdt_grad_avg']}% (" + ", ".join(f"{b} {v}%" for b, v in bands) + ")"
    kind = " ".join(x for x in (o.get("mrtg_type_nm"), o.get("rpay_type_nm"), o.get("lend_rate_type_nm")) if x)
    return f"- {kind}: {o['lend_rate_min']}~{o['lend_rate_max']}%"


def product_chunks(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    kind = PRODUCT_KIND[path.stem]
    for b in data["baseList"]:
        same = ("fin_co_no", "fin_prdt_cd", "crdt_prdt_type")  # 신용대출은 같은 코드에 일반/마이너스 유형이 갈린다
        opts = [o for o in data["optionList"] if all(o.get(k) == b.get(k) for k in same)]
        lines = [f"[{kind}] {b['kor_co_nm']} {b['fin_prdt_nm']}"]
        if b.get("crdt_prdt_type_nm"):
            lines.append(f"상품유형: {b['crdt_prdt_type_nm']}")
        if b.get("join_deny"):
            lines.append(f"가입제한: {JOIN_DENY.get(b['join_deny'], b['join_deny'])}")
        lines += [f"{label}: {str(b[k]).strip()}" for k, label in PRODUCT_FIELDS.items() if b.get(k) not in (None, "", "-")]
        if opts:
            lines += [f"금리 ({b['dcls_month'][:4]}년 {b['dcls_month'][4:]}월 공시)"] + [rate_line(o) for o in opts]
        yield "\n".join(lines), {
            "source_type": "product", "doc": f"{b['kor_co_nm']} {b['fin_prdt_nm']}", "title": kind, "bank": b["kor_co_nm"],
            "product_code": b["fin_prdt_cd"], "disclosure_month": b["dcls_month"], "url": "https://finlife.fss.or.kr"}


def bank_product_chunks(path):
    """내금고 상품 (bank/내금고상품.json = src/data/mock.ts 스냅샷): 상품 1개 = 1청크"""
    for p in json.loads(path.read_text(encoding="utf-8")):
        lines = [f"[내금고 상품] {p['name']} ({p['tag']}) - {p['tagline']}",
                 "금리: " + ", ".join(f"{r['label']} {r['rate']}" for r in p["rateTable"]),
                 "혜택: " + ", ".join(p["benefits"]), "가입 대상: " + ", ".join(p["target"]),
                 "가입 조건: " + ", ".join(p["conditions"]), "유의사항: " + " ".join(p["notices"])]
        lines += [f"{d['title']}: {d['body']}" for d in p["details"]]
        yield "\n".join(lines), {"source_type": "product", "doc": p["name"], "title": p["name"], "bank": "내금고", "product_code": p["id"]}


def snapshot_bank_products():
    # 앱 상품 정의(mock.ts)를 매번 새로 떠서 챗봇 답변과 앱 화면이 어긋나지 않게 한다. Node 23.6+는 .ts를 바로 import
    src = (ROOT.parents[1] / "src" / "data" / "mock.ts").as_uri()
    out = subprocess.run(["node", "--input-type=module", "-e", f"const m = await import('{src}'); console.log(JSON.stringify(m.products))"],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    (ROOT / "bank").mkdir(exist_ok=True)
    (ROOT / "bank" / "내금고상품.json").write_text(json.dumps(json.loads(out), ensure_ascii=False, indent=1), encoding="utf-8")


SOURCES = [
    ("laws/*.md", law_chunks),
    ("terms/*.md", terms_chunks),
    ("bank/내금고상품.json", bank_product_chunks),
    ("faq/내금고FAQ.md", bank_faq_chunks),
    ("faq/착오송금반환FAQ.csv", faq_chunks),
    ("faq/금융용어해설_기업은행.csv", glossary_chunks),
    # 타행 상품(finlife)은 뺀다: 내금고 챗봇은 다른 은행 상품을 추천하지 않고, 상품 청크가 약관 검색을 밀어냈다 (R38).
    # 다시 넣으려면 아래 줄 주석만 풀면 된다. 원본 JSON은 data/rag/products/에 그대로 둔다.
    # ("products/*.json", product_chunks),
]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    snapshot_bank_products()
    rows = []
    for pattern, fn in SOURCES:
        for path in sorted(ROOT.glob(pattern)):
            rel = path.relative_to(ROOT).as_posix()
            for i, (text, meta) in enumerate(fn(path)):
                rows.append({"chunk_id": f"{rel}#{i}", "text": text, "metadata": {"file_name": rel, **meta}})
            print(f"{rel}: {sum(r['metadata']['file_name'] == rel for r in rows)}")
    with OUT.open("w", encoding="utf-8") as f:
        # 가운뎃점 통일 (ㆍ ․ ·가 원천마다 달라 BM25 토큰이 갈린다). 본문·제목 모두 적용
        f.writelines(json.dumps(r, ensure_ascii=False).replace("ㆍ", "·").replace("․", "·") + "\n" for r in rows)
    # 자체 점검: 부칙 앞 조항이 빠짐없이 들어갔는지 (전부 삭제된 조항, 제외한 장만 예외)
    for path in ROOT.glob("laws/*.md"):
        body = path.read_text(encoding="utf-8").split("\n## 부칙")[0]
        got = {r["metadata"]["article"] for r in rows if r["metadata"]["file_name"] == f"laws/{path.name}"}
        live, excluded = set(), False
        for m in re.finditer(r"^## (제\d+장.*)$|^##### (제\d+조(?:의\d+)?) \(.*?\)\n+(?!\*\*①\*\* 삭제|삭제)", body, re.M):
            if m.group(1):
                excluded = any(w in m.group(1) for w in EXCLUDE_CHAPTER_WORDS)
            elif not excluded:
                live.add(m.group(2))
        assert live <= got, f"{path.name} 누락: {live - got}"
        assert len(got) >= len(live), path.name
    # 사람이 검토할 미리보기: 원천 종류별 md (data/rag/preview/)
    (ROOT / "preview").mkdir(exist_ok=True)
    for kind in sorted({r["metadata"]["source_type"] for r in rows}):
        part = [r for r in rows if r["metadata"]["source_type"] == kind]
        md = [f"# {kind} ({len(part)}청크)\n"] + [f"### `{r['chunk_id']}` · {len(r['text'])}자" + (f" · {r['metadata']['chapter']}" if r["metadata"].get("chapter") else "") + f"\n```\n{r['text']}\n```\n" for r in part]
        (ROOT / "preview" / f"{kind}.md").write_text("\n".join(md).replace("ㆍ", "·").replace("․", "·"), encoding="utf-8")
    lens = sorted(len(r["text"]) for r in rows)
    print(f"total {len(rows)} chunks → {OUT.relative_to(ROOT.parents[1])} | 길이 중앙값 {lens[len(lens) // 2]}, 최대 {lens[-1]}")


if __name__ == "__main__":
    main()
