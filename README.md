# 내금고

AI 금융 어시스턴트를 결합한 모바일 인터넷뱅킹 클론 프로젝트.

## 폴더 구조

```text
bank_clone/
├─ README.md              이 파일 (전체 지도)
├─ PRODUCT.md, DESIGN.md  제품 정의·디자인 시스템 (impeccable 스킬이 루트에서 읽음)
│
├─ docs/                  설계 문서
│  ├─ db-design.md        DB 구조와 설계 결정 (먼저 읽기)
│  ├─ bank.dbml           DB 스키마 원본 (drawDB로 가져오기)
│  ├─ backend-implementation.md  백엔드 작업 지시서 (단계, API 명세, 에러 코드)
│  ├─ backend-design.md   백엔드 스택, 이체 공통 함수
│  └─ agent-design.md     AI Agent (LangGraph) 설계
│
├─ src/, index.html       프론트엔드 (React + Vite + Tailwind)
├─ package.json, vite.config.ts, tsconfig.json
│
├─ backend/               API 서버 (FastAPI + PostgreSQL) — backend/README.md
│
├─ rag/                   챗봇 RAG 파이프라인 (청킹 → 임베딩 → 검색 → 평가)
├─ data/rag/              RAG 원천 데이터와 골든셋 — data/rag/README.md
├─ scripts/               보조 스크립트 (RAG 데이터 수집, 챗봇 시나리오 체크)
│
└─ rag-agent-practice/    이전 RAG 실습 (참고용, 이 앱과 별개)
```

## 실행

| 대상 | 명령 | 위치 |
|---|---|---|
| 프론트엔드 | `npm install` → `npm run dev` (http://localhost:5173) | 루트 |
| 백엔드 | `uv sync` → `uv run uvicorn app.main:app --reload --env-file .env` | `backend/` |
| 백엔드 테스트 | `uv run pytest` | `backend/` |
| RAG 청킹 | `python rag/chunk.py` | 루트 |
| RAG 데이터 수집 | `node scripts/fetch-rag-data.mjs` | 루트 |
| 챗봇 시나리오 체크 | `node scripts/check-chat.mjs` | 루트 |

## 환경 변수

- 루트 `.env`: 프론트(`VITE_CHAT_API_URL`)와 RAG(`GEMINI_API_KEY`) 등. 예시는 `.env.example`.
- `backend/.env`: `DATABASE_URL`, `JWT_SECRET`. 예시는 `backend/.env.example`.
- `.env`는 커밋하지 않는다 (`.gitignore`에 포함).
