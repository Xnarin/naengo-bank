"""data/ 아래 PDF를 페이지별로 읽고 → 청킹 → 임베딩 → Chroma에 저장한다.

실행: python ingest.py [--chunk-size 500] [--chunk-overlap 50]
청킹 설정마다 컬렉션 이름이 달라서, 설정을 바꿔도 이전 DB가 남아 비교 실험에 쓸 수 있다.
임베딩은 emb_cache/에 PDF별로 캐시되어, 중간에 끊겨도 다시 실행하면 이어서 진행된다.
"""

import argparse
import base64
import json
import os
import pickle
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

import pdfplumber
import pypdfium2

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DATA_DIR = Path(__file__).parent / "data"
CHROMA_DIR = Path(__file__).parent / "chroma_db"
OCR_CACHE_DIR = Path(__file__).parent / "ocr_cache"
IMAGE_CACHE_DIR = Path(__file__).parent / "image_cache"
EMB_CACHE_DIR = Path(__file__).parent / "emb_cache"
EMBEDDING_MODEL_NAME = "gemini-embedding-2"
OCR_MODEL_NAME = "gemini-3.6-flash"
OCR_PROMPT = "이 문서 페이지의 글자를 읽는 순서대로 그대로 옮겨 적어라. 표는 Markdown 표로, 그림은 무시하고, 설명이나 요약은 덧붙이지 마라."
IMAGE_PROMPT = "이 이미지는 PDF 문서 한 페이지의 일부다. 표·차트·그래프·도식·인포그래픽이면 읽을 수 있는 모든 글자와 수치를 옮겨라. 표는 Markdown 표로, 차트와 그래프는 제목·축·범례·항목별 수치를 목록으로 쓰고, 해석이나 요약은 덧붙이지 마라. 사진·로고·장식처럼 읽을 정보가 없으면 NONE 한 단어만 출력하라."
MIN_IMAGE = (120, 80, 0.04)  # 너비·높이(pt)와 페이지 대비 면적 비율의 최소값. 아이콘·장식을 거른다
BATCH_SIZE = 100  # 임베딩 API 배치 한도


def index_name(chunk_size, chunk_overlap, tables=False):
    """tables: False(텍스트만) / True(+pdfplumber 표 청크) / "image"(+이미지 표·차트를 비전으로 읽은 청크)"""
    return f"pdf_c{chunk_size}_o{chunk_overlap}" + ("_tblimg" if tables == "image" else "_tbl" if tables else "")


def get_vectorstore(chunk_size, chunk_overlap, tables=False):
    return Chroma(
        collection_name=index_name(chunk_size, chunk_overlap, tables),
        embedding_function=GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME),
        persist_directory=os.path.relpath(CHROMA_DIR),  # 한글 포함 절대경로를 주면 Windows에서 HNSW 파일이 안 써진다
        collection_configuration={"hnsw": {"space": "cosine"}},
    )


def ocr_pages(path, page_idxs):
    """텍스트 레이어가 없는 스캔 페이지를 Gemini 비전으로 읽는다. 결과는 파일별 JSON에 캐시."""
    OCR_CACHE_DIR.mkdir(exist_ok=True)
    cache_path = OCR_CACHE_DIR / f"{path.stem}.json"
    cache = json.loads(cache_path.read_text(encoding="utf8")) if cache_path.exists() else {}
    llm = ChatGoogleGenerativeAI(model=OCR_MODEL_NAME, timeout=90, max_retries=2)
    pdf = pypdfium2.PdfDocument(str(path))
    for i in page_idxs:
        if str(i) in cache:
            continue
        buf = BytesIO()
        pdf[i].render(scale=2).to_pil().save(buf, format="PNG")
        message = HumanMessage(content=[
            {"type": "text", "text": OCR_PROMPT},
            {"type": "image", "base64": base64.b64encode(buf.getvalue()).decode("ascii"), "mime_type": "image/png"},
        ])
        cache[str(i)] = llm.invoke([message]).text.strip()
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf8")  # 페이지마다 저장 → 중단돼도 이어서
        print(f"  ocr {path.name} p{i + 1}")
    return cache


def load_pdf(path):
    """페이지별 Document. page_no는 1부터 (골든셋 페이지 표기와 맞춤)."""
    docs = PyPDFLoader(str(path)).load()
    empty = [i for i, d in enumerate(docs) if not d.page_content.strip()]
    if empty:  # 스캔 페이지는 OCR로 채운다 (페이지 수를 줄이는 PDF는 없다고 가정)
        ocr = ocr_pages(path, empty)
        for i in empty:
            docs[i] = Document(page_content=ocr[str(i)], metadata={"page": i})
    for doc in docs:
        doc.metadata = {
            "domain": path.parent.name,
            "file_name": path.name,
            "page_no": doc.metadata["page"] + 1,
        }
    # OCR 후에도 빈 페이지(백지 등)는 임베딩 대상에서 뺀다.
    return [d for d in docs if d.page_content.strip()]


def table_to_chunks(rows, size):
    """표를 Markdown으로 바꾸고, 크면 헤더를 매 조각에 반복하면서 행 단위로 자른다. 비었거나 너무 작은 표는 버린다."""
    rows = [[" ".join((c or "").split()).replace("|", "/") for c in row] for row in rows]
    rows = [r for r in rows if any(r)]
    if len(rows) < 2 or sum(len(c) for r in rows for c in r) < 20:
        return []
    header = "| " + " | ".join(rows[0]) + " |" + chr(10) + "| " + " | ".join("---" for _ in rows[0]) + " |"
    chunks, current = [], []
    for row in rows[1:]:
        line = "| " + " | ".join(row) + " |"
        if current and len(header) + sum(len(x) + 1 for x in current) + len(line) > size:
            chunks.append(header + chr(10) + chr(10).join(current))
            current = []
        current.append(line)
    return chunks + [header + chr(10) + chr(10).join(current)]


def read_images(path, pdf, docs):
    """표·차트가 이미지로 들어 있는 영역을 Gemini 비전으로 읽어 Document로 돌려준다. 결과는 파일별 JSON에 캐시."""
    IMAGE_CACHE_DIR.mkdir(exist_ok=True)
    cache_path = IMAGE_CACHE_DIR / f"{path.stem}.json"
    cache = json.loads(cache_path.read_text(encoding="utf8")) if cache_path.exists() else {}
    jobs = {}
    for doc in docs:
        page = pdf.pages[doc.metadata["page_no"] - 1]
        if not page.chars:
            continue  # 글자 없는 페이지는 전체 OCR로 이미 읽었다
        for i, im in enumerate(page.images):
            w, h = im["x1"] - im["x0"], im["bottom"] - im["top"]
            if w >= MIN_IMAGE[0] and h >= MIN_IMAGE[1] and w * h / (page.width * page.height) >= MIN_IMAGE[2]:
                jobs[f"{doc.metadata['page_no']}-{i}"] = (doc, page, im)
    pngs = {}
    for key, (doc, page, im) in jobs.items():
        if key in cache:
            continue
        bbox = (max(im["x0"], 0), max(im["top"], 0), min(im["x1"], page.width), min(im["bottom"], page.height))
        buf = BytesIO()
        page.crop(bbox).to_image(resolution=150).original.save(buf, format="PNG")  # pdfplumber는 스레드 안전하지 않아 렌더링은 여기서
        pngs[key] = buf.getvalue()
    llm = ChatGoogleGenerativeAI(model=OCR_MODEL_NAME, timeout=90, max_retries=3)

    def ask(key):
        message = HumanMessage(content=[
            {"type": "text", "text": IMAGE_PROMPT},
            {"type": "image", "base64": base64.b64encode(pngs[key]).decode("ascii"), "mime_type": "image/png"},
        ])
        return key, llm.invoke([message]).text.strip()

    with ThreadPoolExecutor(4) as pool:
        for future in as_completed([pool.submit(ask, k) for k in pngs]):
            try:
                key, text = future.result()
            except Exception as e:  # 실패한 이미지는 캐시하지 않아 다음 실행에서 다시 시도한다
                print(f"  image failed: {str(e)[:80]}")
                continue
            cache[key] = "" if text.upper().startswith("NONE") else text
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf8")
    return [Document(page_content=cache[k], metadata={**jobs[k][0].metadata, "content_type": "image"}) for k in jobs if cache.get(k)]


def load_pdf_with_tables(path, chunk_size, images=False):
    """load_pdf의 페이지 텍스트는 그대로 두고, pdfplumber가 찾은 표를 Markdown 청크로 덧붙인다.
    표 영역의 글자를 본문에서 빼지 않는다: pdfplumber는 병합·세로 글자 칸을 빈칸으로 뽑아서, 빼면 그 글자가 사라진다.
    표 청크는 content_type=table이라 이후 글자 수로 다시 자르지 않는다. 글자 없는 이미지 표는 못 읽는다."""
    docs = load_pdf(path)
    for doc in docs:
        doc.metadata["content_type"] = "text"
    tables = []
    with pdfplumber.open(path) as pdf:
        for doc in docs:
            for t in pdf.pages[doc.metadata["page_no"] - 1].find_tables():
                tables += [Document(page_content=c, metadata={**doc.metadata, "content_type": "table"}) for c in table_to_chunks(t.extract(), chunk_size)]
        image_docs = read_images(path, pdf, docs) if images else []
    return docs + tables + image_docs


def embed(embeddings, texts):
    for attempt in range(5):  # 503 등 일시 오류는 백오프 후 재시도
        try:
            return embeddings.embed_documents(texts)
        except Exception as e:
            if attempt == 4:
                raise
            print(f"  retry {attempt + 1}: {str(e)[:80]}")
            time.sleep(2 ** (attempt + 1))


def ingest(chunk_size=500, chunk_overlap=50, tables=False):
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    embeddings = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME)
    name = index_name(chunk_size, chunk_overlap, tables)

    # 1단계: PDF별로 청킹·임베딩하고 결과를 pickle에 캐시 (재실행 시 API를 다시 부르지 않는다)
    EMB_CACHE_DIR.mkdir(exist_ok=True)
    cache_path = EMB_CACHE_DIR / f"{name}.pkl"
    cache = pickle.loads(cache_path.read_bytes()) if cache_path.exists() else {}
    for path in sorted(DATA_DIR.glob("*/*.pdf")):
        key = f"{path.parent.name}/{path.name}"
        if key in cache:
            continue
        # 페이지 단위로 분할하므로 청크가 페이지를 넘지 않아 출처 표시가 정확하다.
        docs = load_pdf_with_tables(path, chunk_size, images=tables == "image") if tables else load_pdf(path)
        chunks = []
        for d in docs:
            chunks += [d] if d.metadata.get("content_type") == "table" else splitter.split_documents([d])
        rows = []
        for s in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[s : s + BATCH_SIZE]
            vectors = embed(embeddings, [c.page_content for c in batch])
            for i, (c, v) in enumerate(zip(batch, vectors), start=s):
                c.metadata["chunk_id"] = f"{key}#{i}"
                rows.append((c.metadata["chunk_id"], c.page_content, c.metadata, v))
        cache[key] = rows
        cache_path.write_bytes(pickle.dumps(cache))
        print(f"embedded {path.name}: {len(chunks)} chunks")

    # 2단계: 캐시된 벡터로 Chroma를 처음부터 다시 만든다 (한꺼번에 빠르게 쓴다)
    vectorstore = get_vectorstore(chunk_size, chunk_overlap, tables)
    vectorstore.delete_collection()
    vectorstore = get_vectorstore(chunk_size, chunk_overlap, tables)
    rows = [r for file_rows in cache.values() for r in file_rows]
    for s in range(0, len(rows), BATCH_SIZE):
        ids, texts, metas, vectors = zip(*rows[s : s + BATCH_SIZE])
        vectorstore._collection.upsert(ids=list(ids), documents=list(texts), metadatas=list(metas), embeddings=list(vectors))
    print(f"total chunks: {vectorstore._collection.count()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--chunk-overlap", type=int, default=50)
    parser.add_argument("--tables", action="store_true", help="pdfplumber로 표를 따로 추출한다")
    args = parser.parse_args()
    ingest(args.chunk_size, args.chunk_overlap, args.tables)
