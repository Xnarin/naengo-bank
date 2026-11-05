# Bank Clone Backend

작업 지시서: [`../docs/backend-implementation.md`](../docs/backend-implementation.md) — 이어서 작업한다면 이것부터 읽기
DB: [`../docs/db-design.md`](../docs/db-design.md) · 설계: [`../docs/backend-design.md`](../docs/backend-design.md)

## Docker로 실행 (권장)

저장소 루트에서 실행합니다. FastAPI와 PostgreSQL 17을 함께 실행하며, DB 준비 후 마이그레이션과 상품·약관 시드를 자동 적용합니다.

```powershell
Copy-Item .env.docker.example .env.docker
# .env.docker의 POSTGRES_PASSWORD와 JWT_SECRET을 긴 무작위 값으로 입력
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker ps
```

이미 `.env.docker`가 있다면 복사하지 말고 기존 값을 사용합니다. API 문서: http://localhost:8000/docs · 준비 상태: http://localhost:8000/health

현재 PC는 8000번 포트가 이미 사용 중이어서 `.env.docker`의 `API_PORT=8001`로 실행 중입니다. 현재 API 문서는 http://localhost:8001/docs 입니다.

DB는 내부 네트워크의 `db:5432`로 연결하고 외부 포트는 열지 않습니다. 데이터는 `postgres_data` 볼륨에 남습니다. 종료는 `docker compose --env-file .env.docker down`을 사용합니다.

루트 `.env`는 기존 AI의 Gemini 키를 읽기 위해 읽기 전용으로 연결됩니다. AI를 사용하지 않으면 빈 `.env` 파일만 있어도 은행 API는 실행됩니다. 비밀값과 RAG 데이터는 이미지에 포함하지 않습니다.

`DEVELOPMENT=true`이고 SMTP가 없을 때 `/auth/codes` 응답에만 `dev_code`가 포함됩니다. 로그에는 번호를 출력하지 않습니다. 실제 메일 발송은 `.env.docker`에 `SMTP_HOST/PORT/USER/PASSWORD/FROM`을 설정합니다. SMTP 연결은 STARTTLS를 사용합니다.

## 회원·인증 확인 순서

1. `GET /terms?category=SIGNUP`에서 약관 ID를 확인합니다.
2. `POST /auth/codes`에 `{email, purpose: "SIGNUP"}`을 보냅니다.
3. 받은 번호로 `POST /auth/codes/verify`에 `{email, purpose: "SIGNUP", code}`를 보냅니다.
4. `POST /auth/signup`에 `{email, password, pin, user_name, agreed_term_ids}`를 보냅니다. `name`도 호환됩니다.
5. `/auth/login` 또는 `/auth/login/pin`으로 토큰을 받습니다. 보호 API에는 `Authorization: Bearer <access_token>`을 넣습니다.

가입하면 기본 통장과 가입 축하 가상머니 100만원 입금 원장이 함께 생성됩니다. 비밀번호/PIN 로그인은 각각 5회 실패 시 회원 잠금, 계좌 작업의 PIN은 5회 실패 시 해당 계좌만 거래중지됩니다. `/auth/password/reset`은 `RESET_PW` 인증번호로 비밀번호와 잠금을 재설정합니다.

`GET/PATCH /me`로 정보 조회·변경, `DELETE /me`에 `{password}`를 보내 탈퇴합니다. 탈퇴 전에 모든 계좌를 해지해야 합니다. 잠김·탈퇴 회원은 기존 JWT로도 보호 API에 접근할 수 없습니다.

## 계좌 기능

- 개설: `GET /terms?category=ACCOUNT_OPEN` 후 `POST /accounts`에 `{product_code, password, password_confirm, opening_info, agreed_term_ids, nickname?}`를 보냅니다. 비밀번호는 숫자 4자리, `opening_info`는 개설 목적·거래정보를 담은 비어 있지 않은 객체입니다.
- 조회: `GET /accounts`는 계좌번호를 마스킹하고 즐겨찾기를 먼저 표시합니다. `?status=closed`로 해지 목록을 보고, `GET /accounts/{id}`로 전체 번호·한도 사용액을 확인합니다. 내 계좌끼리 이체와 카드 결제는 이체한도에서 제외됩니다.
- 거래내역: `GET /accounts/{id}/transactions?from=2026-01-01&to=2026-12-31&direction=OUT&type=TRANSFER&min=1000&max=50000&q=메모&order=desc`. `amount`는 정확한 금액, 기간 기본값은 달력 기준 3개월입니다. 거래 상세는 `/transactions/{tx_id}`입니다.
- 관리: `POST /accounts/{id}/favorite`, `PUT /accounts/{id}/limits`에 `{daily_limit, month_limit, pin}`. 한도는 일 1천만원·월 5천만원 이하이고 일 한도가 월 한도보다 클 수 없습니다.
- 거래중지 해제: `UNLOCK_ACCOUNT` 용도로 본인 이메일 인증번호를 받은 뒤 `POST /accounts/{id}/unlock`에 `{code}`를 보냅니다. 번호는 한 번만 사용합니다.
- 해지: `GET /accounts/{id}/close-check`로 제한 사유를 확인하고 `POST /accounts/{id}/close`에 `{pin}`을 보냅니다. 잔액·연결 카드·대기 중 출금 자동이체가 있으면 거부합니다. 해지 후에도 거래내역은 조회할 수 있습니다.
- 다운로드: `POST /accounts/{id}/statements`에 `{from_date, to_date, email}`을 보냅니다. 현재 요청 안에서 CSV를 생성·발송한 후 `202 {id, status: SENT|FAILED}`를 반환합니다. SMTP 미설정은 발송 실패로 기록됩니다. CSV에는 한글 Excel용 BOM과 수식 실행 방지 처리가 포함됩니다.

계좌 테스트는 타인 계좌 404, PIN 5회 오류, 번호 충돌 재시도, 해지 제한, 한도 집계, CSV 내용을 검증합니다. PostgreSQL에서도 같은 주요 API 흐름을 확인했고, 검사 데이터는 rollback했습니다. 실제 CSV 첨부 메일 수신은 별도 확인이 필요합니다.

## 카드·자동이체·알림 연결

- 카드: `POST/GET /cards`, `GET/PATCH /cards/{id}`, `POST /cards/{id}/lost|suspend|resume|cancel|reissue`, `GET/POST /cards/{id}/payments`. 변경·해지·재발급은 `{pin}`이 필요합니다. 결제 API는 가상 결제 시연용이며 `idempotency_key`(8~64자)가 필수입니다. 같은 카드에서 같은 키·내용은 최초 결과를 반환하고, 같은 키로 내용을 바꾸면 409를 반환합니다.
- 자동이체: `POST /auto-transfers`는 `{from_account_id, to_account_num, amount, pin, cycle, ...}`를 받습니다. ONCE는 시간대가 포함된 `run_at`, WEEKLY는 `run_day=0~6`, MONTHLY는 `run_day=1~31`과 선택 `start_date/end_date`를 보냅니다. 목록은 `GET /auto-transfers?status=ACTIVE`, 취소는 `DELETE /auto-transfers/{id}`입니다.
- 정기 이체는 기본 KST 09시이고 없는 날은 말일로 보정합니다. 스케줄러는 1분마다 확인하며 서버 시작 시에도 지난 일정을 확인합니다. 종료일이 지난 일정은 실행하지 않습니다. 단일 API 프로세스를 기준으로 합니다.
- 알림: `GET /notifications`는 `{items, unread}`, `POST /notifications/read-all`은 204입니다. 카드 결제·자동이체 실패·이상 접속을 저장합니다.

`CARD_KEY`는 Fernet 키이며 Docker 설정에 생성해 두었습니다. 재시작·재빌드 때 같은 키를 유지해야 기존 카드를 읽을 수 있습니다. 새 환경에서는 `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`로 생성해 `.env.docker`에 저장합니다. `SCHEDULER_ENABLED=true`가 스케줄러를 켭니다 (Compose 기본 true, 로컬 기본 false).

Claude 연결 시 `from app.services import cards`를 사용합니다. 카드 끝자리 표시·매칭은 `cards.last4(card)`, 직렬화는 `cards.card_out(card)`, PIN 확인 후 상태 변경은 `cards.set_card_status(db, user_id, card_id, status)`입니다. 암호문 `card.card_number`에서 직접 끝자리를 자르면 안 됩니다.

AI 확인은 `/agent/confirm`, 일반 화면 송금은 `/transfers`로 실행합니다. AI 승인 한 번에 두 API를 모두 호출하지 않습니다. 프론트와 에이전트를 연결하고 전체 Docker 이미지를 재빌드했습니다. 현재 8001 API와 5173 앱이 같은 PostgreSQL 데이터를 사용합니다.

은행 테스트 82개 통과. PostgreSQL 임시 스키마에서 동시 카드 결제·중복 회차 실행·처리 도중 rollback·카드/자동이체/알림 API를 확인했고, 검사 스키마는 제거했습니다. 실제 카드사·푸시 연동은 범위 밖입니다.

## 로컬 Python 실행

```bash
uv sync
cp .env.example .env          # DATABASE_URL, JWT_SECRET 채우기
"/c/Program Files/PostgreSQL/17/bin/createdb.exe" -U postgres bank
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --env-file .env
```

API 문서: http://localhost:8000/docs

## 테스트

```bash
uv run pytest
```

## 구조

```text
app/
  models.py           # 모든 테이블
  services/
    transfers.py      # 이체 공통 함수 (API·스케줄러·Agent 공용)
    accounts.py       # 소유자 확인, 상태별 허용 동작, 계좌번호 발급
  api/                # auth, accounts, transfers, agent 라우터
  agent/              # AI 어시스턴트 LangGraph (graph.py: router, rag.py: CRAG). 현황은 docs/agent-design.md §0
                      # 확인: uv run python -m app.agent.graph "통장 빌려주면 처벌받나요?" (루트 .env의 GEMINI_API_KEY 필요)
  security.py         # JWT, argon2, PIN 확인
alembic/              # 마이그레이션
tests/
```
