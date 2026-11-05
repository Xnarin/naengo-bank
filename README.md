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

현재 프론트는 Mock 저장소 대신 실제 FastAPI·PostgreSQL을 사용합니다. 루트에서 Docker 서버와 Vite를 실행합니다.

```powershell
docker compose --env-file .env.docker up -d --build
npm run dev
```

앱: http://127.0.0.1:5173 · API 문서: http://127.0.0.1:8001/docs

개발용 테스트 계정: `test1@example.com`, `test2@example.com`. 공통 비밀번호 `Test1234!`, PIN `493827`. 서로 다른 탭에서 각각 로그인해 송금·입금 알림을 확인할 수 있습니다. 신규 개발 DB에서는 다음으로 가상 체험 계정·계좌·카드를 준비할 수 있습니다. 실제 이메일은 발송하지 않습니다.

```powershell
Get-Content -Raw -Encoding utf8 backend/tests/seed_demo.py | docker compose --env-file .env.docker exec -T api python -
```

프론트의 `/api` 요청을 Vite가 Docker API 8001번 포트로 전달합니다. 로그인 토큰은 현재 탭의 sessionStorage에, 계좌·거래·카드·일정·알림은 서버 DB에 저장합니다. 상품 설명과 가상 가맹점 목록은 예시 콘텐츠를 사용합니다. 운영용 프론트 호스팅에는 같은 `/api` 경로의 역방향 프록시 구성이 필요합니다.

일반 화면 송금은 `/transfers`, AI 확인 송금·카드 조치는 `/agent/confirm`을 각각 한 번 호출합니다. 응답 유실 시 일반 이체는 요청 키로 결과를 재조회합니다. PIN은 작업 요청에 전달하며 브라우저 저장소에 보관하지 않습니다.

가상 카드 결제도 요청 키로 중복 처리를 방지합니다. 통신 오류가 나면 브라우저의 localStorage에 보관한 요청 내용·키로 같은 결제를 재시도하며, 성공 후에는 이를 지우고 다음 결제에 새 키를 씁니다. 새로고침·탭 종료 후에도 미확인 요청을 유지합니다. 미확인 결제가 남아 있으면 다른 금액·가맹점 결제에 앞서 원래 조건으로 재시도해야 합니다.

앱을 보는 동안 10초마다, 화면 이동·창 복귀·인터넷 재연결 시 계좌·거래·이체 일정·알림을 갱신합니다. 다른 사람의 입금과 자동·예약이체 성공/실패는 앱 안의 알림에 표시됩니다. 알림을 읽는 중 새로 도착한 항목은 읽지 않은 상태를 유지합니다. 브라우저를 닫은 상태의 푸시 알림은 지원하지 않습니다.

AI 채팅에서 소비 패턴 분석·이번 달/다음 달 지출 및 잔액 예측·정기결제 후보 탐지를 사용할 수 있습니다. 모든 수치는 Python 도구가 계산하고 AI는 결과를 설명합니다. 예측은 미래 입금 0원 가정의 추정이며 데이터가 부족하면 보류합니다. [계산 방식과 검사 방법](docs/agent-insights.md)을 참고하세요. 테스트1에는 잔액을 유지한 채 3개월치 가상 분석 이력을 추가했고, 테스트2는 짧은 이력에서 예측을 보류하는 경우를 확인할 수 있습니다.

검증: 프론트 빌드 통과, 백엔드 87개 테스트 통과. 실제 브라우저에서 로그인·계좌 조회·일반 송금·AI PIN 확인 송금·가상 카드 결제·새로고침 후 서버 데이터 복원을 확인했습니다. `/api` 프록시로 자동이체 등록·취소와 알림 읽음도 확인했습니다.

| 대상 | 명령 | 위치 |
|---|---|---|
| 프론트엔드 | `npm install` → `npm run dev` (http://localhost:5173) | 루트 |
| 백엔드 | `uv sync` → `uv run uvicorn app.main:app --reload --env-file .env` | `backend/` |
| 백엔드 테스트 | `uv run pytest` | `backend/` |
| 로그인·알림·갱신 상태 검사 | `node tests/session.mjs` | 루트 |
| AI 분석 카드·차트 표시 검사 | `node tests/insight-cards.mjs` | 루트 |
| RAG 청킹 | `python rag/chunk.py` | 루트 |
| RAG 데이터 수집 | `node scripts/fetch-rag-data.mjs` | 루트 |
| 챗봇 시나리오 체크 | `node scripts/check-chat.mjs` | 루트 |

## 환경 변수

- 루트 `.env`: 에이전트/RAG의 `GEMINI_API_KEY`. 브라우저에 키를 전달하지 않습니다.
- 루트 `.env.docker`: PostgreSQL·JWT·카드 암호화 키·SMTP 등 Docker 서버 설정.
- `backend/.env`: `DATABASE_URL`, `JWT_SECRET`. 예시는 `backend/.env.example`.
- `.env`는 커밋하지 않는다 (`.gitignore`에 포함).
