# 백엔드 구현 가이드

> 이 문서만 보고 다른 세션·다른 AI가 백엔드 작업을 이어받을 수 있도록 쓴 작업 지시서다.
> 작성 2026-11-05. 단계(Phase)를 끝낼 때마다 **1장 현재 상태**와 각 단계의 체크박스를 갱신한다.

## 0. 먼저 읽을 것 (우선순위 순)

| 순위 | 문서 | 역할 |
|---|---|---|
| 1 | `C:/Users/김나린/Downloads/product-spec.md` (사용자 제공) | 기능의 최종 기준. 5절 "필수"만 구현 |
| 2 | [`db-design.md`](db-design.md), [`bank.dbml`](bank.dbml) | 테이블·컬럼·설계 결정 |
| 3 | **이 문서** | 구현 순서, API 계약, 에러 코드, 완료 기준 |
| 4 | `src/store.tsx`, `src/data/mock.ts` (프론트 Mock) | 화면이 기대하는 동작. 백엔드가 이 함수들을 대체한다 |
| 5 | [`backend-design.md`](backend-design.md), [`agent-design.md`](agent-design.md) | 스택 선택 이유, 이체 함수 원형, 에이전트 설계 |

문서끼리 충돌하면 위 순위를 따르고, 이 문서 **2장 결정 사항**에 기록한다.

## 1. 현재 상태

### 있는 것 (`backend/`)
| 파일 | 내용 | 상태 |
|---|---|---|
| `app/main.py` | FastAPI 앱, `BankError` → JSON 응답 | 동작 |
| `app/config.py`, `app/db.py` | `.env`의 `DATABASE_URL`, `JWT_SECRET` / 세션 | 동작 |
| `app/models.py` | 15개 테이블. `bank.dbml`과 이름 1:1 (uuid / bigint id 포함) | ✅ Phase 0 |
| `app/security.py` | argon2 해시, JWT(sub=uuid) 발급·검증, PIN 확인 (D4: 계좌 작업 중 5회 → 계좌 거래중지, 아니면 회원 잠금) | ✅ |
| `app/services/transfers.py` | 이체 공통 함수 (행 잠금, 상태·한도·잔액 검사, 원장 2행, 멱등키). 에러 코드는 5장 기준 | ✅ D7도 Phase 2에서 반영 |
| `app/services/accounts.py` | 계좌 개설·조회·검색·관리·해지·다운로드, 소유자·상태 검사, 한도 사용액 | ✅ Phase 2 |
| `app/api/auth.py`, `app/services/auth.py` | 가입·약관·기본 통장, 비밀번호/PIN 로그인·접속 기록·이상 접속, 내 정보·탈퇴·비밀번호 재설정 | ✅ Phase 1 |
| `app/services/verification.py`, `app/services/mail.py` | 인증번호 생성·검증·소비, SMTP, CSV 첨부 | ✅ 실제 인증메일 수신·검증 사용자 확인. 첨부는 SMTP 모의 테스트 |
| `app/api/accounts.py` | 상품·계좌·거래·관리·해지·다운로드·PIN 확인 API (서비스 호출만) | ✅ Phase 2 |
| `app/api/transfers.py`, `app/services/transfers.py` | 받는 분 확인·PIN 이체·결과 재조회·최근 계좌·받는 계좌 즐겨찾기 CRUD·중복/동시 이체 | ✅ Phase 3 (분리 컨테이너 검증, 실행 중 API는 재빌드하지 않음) |
| `app/api/agent.py`, `app/agent/` | 조회·송금·카드 정지·PIN 확인 (사용자 완료 보고) | Claude 담당. 프론트 연결 및 공통 카드 서비스 교체 필요 |
| `app/services/cards.py`, `app/api/cards.py` | 암호화 카드 발급·관리·해지·재발급·결제·사용내역 | ✅ Phase 5 |
| `app/services/auto_transfers.py`, `app/api/auto_transfers.py`, `app/scheduler.py` | 정기/예약이체·취소·원자적 회차 실행, APScheduler 1분 루프 | ✅ Phase 4 |
| `app/services/notifications.py`, `app/api/notifications.py` | 알림 목록·미확인 개수·모두 읽음 | ✅ Phase 6 |
| `alembic/versions/0001_initial_tables.py` | 15개 테이블 생성 | ✅ SQLite에서 upgrade·downgrade·check 확인 |
| `alembic/versions/0002_seed_products_terms.py` | 상품 5개(D9), 데모 약관 5개(가입 3, 계좌개설 2) | ✅ |
| `tests/test_transfer.py` | 이체 함수 테스트 (SQLite 메모리) | 14개 통과 |
| `tests/test_transfers_api.py`, `tests/check_transfer_postgres.py` | 이체 API·재조회·마스킹·즐겨찾기·동시 송금 | 이체 전용 31개 통과 + PostgreSQL 동시성 4종 및 실제 API 검증 |
| `tests/test_auth.py` | 가입 원자성, 인증번호·약관, 로그인·잠금·토큰·탈퇴·SMTP 응답 | 14개 통과 |
| `tests/test_accounts.py` | 개설·UNIQUE 충돌 재시도·소유자·검색·한도·해제·해지·CSV | 19개 통과 |
| `tests/test_cards_auto.py`, `tests/check_banking_postgres.py` | 카드·자동이체·알림·스케줄러·rollback·PostgreSQL 동시성 | 새 테스트 18개, 전체 은행 테스트 82개 통과 |
| `../compose.yaml`, `Dockerfile` | PostgreSQL 17 + FastAPI, DB healthcheck 후 마이그레이션·시드 자동 적용 | ✅ 실제 Docker 실행·HTTP 흐름 확인. 현재 API_PORT=8001 |

Docker 환경: 루트 `.env.docker` 사용 (무작위 DB 비밀번호·JWT 키 생성, Git 제외). DB는 내부 네트워크만 사용하고 데이터는 `postgres_data` 볼륨에 보관한다. Docker Desktop의 오래된 소켓 문제는 `Docker/run`, `docker-secrets-engine` 임시 폴더를 백업한 뒤 재시작해 복구했다. 사용자명·프로필 경로 변경 없음. 실제 HTTP 검사로 개발 DB에 `docker-check-…@example.com` 테스트 회원 1명과 기본 통장·원장 1건을 생성했다.

### 남은 통합 작업
- Claude 담당: 프론트의 Mock 교체, JWT·thread_id·confirm 연동, 카드 끝자리/상태 변경을 공통 서비스로 교체.
- 전체 통합 이미지 재빌드 및 화면→실제 DB 흐름 검증. 이번 Phase 4~6도 임시 컨테이너에서 새 파일만 연결해 검사했으며, 실행 중 API는 아직 재빌드하지 않음.
- 실제 CSV 첨부메일 수신 확인. 스케줄러는 단일 API 프로세스 운영을 전제로 함.

## 2. 결정 사항

기획서·DBML·프론트 Mock이 서로 다른 곳을 이렇게 정했다. **바꾸려면 사용자에게 먼저 확인한다.**

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| D1 | 로그인 ID | **이메일**을 로그인 ID로 쓴다. `users.login_id` 컬럼은 만들지 않는다 | 프론트가 이메일+비밀번호로 가입·로그인 (`store.signup/login`). 기획서 "ID/PW"를 이메일로 충족 |
| D2 | 본인확인 | 이메일 인증번호 (`verification_codes.email`) | db-design.md 3.1 |
| D3 | 로그인 유지 | JWT access token 15분, refresh token 없음, 만료 시 PIN 재로그인 | db-design.md 3.2 |
| D4 | PIN 5회 오류 | **이체 등 계좌 작업 중 틀리면 그 계좌를 거래중지(SUSPENDED)**, PIN 로그인 중 틀리면 회원 잠금(LOCKED). 카운터는 `users.pin_fail_count` 하나 | 프론트 `verifyPin(pin, accountId)` 동작, 기획서 "비밀번호 오류 누적 → 거래중지 → 인증번호로 해제" |
| D5 | 통장 비밀번호 | 계좌 개설 시 설정·확인만 한다 (B1.3, B1.7). 다른 화면에서는 쓰지 않으므로 `accounts.password_fail_count`는 컬럼만 둔다 | 기획서·프론트 모두 이체 인증은 PIN |
| D6 | 자동이체 vs 예약이체 | `auto_transfers` 하나로 둘 다 처리. `cycle`에 `ONCE`(예약이체) 추가, `next_run_date date` → **`next_run_at timestamptz`** | 기획서 C2.1 자동이체 필수, 프론트는 일시 지정 예약송금(`scheduleTransfer`)을 이미 구현 |
| D7 | 한도 집계 | **내 계좌끼리 옮긴 돈은 한도에서 뺀다** | 프론트 `usageOf` 동작 |
| D8 | 가입 축하금 | 가입 시 기본 입출금통장(`basic`) 자동 개설 + 1,000,000원 입금 거래 1건 (상대방 "내금고", 적요 "가입 축하 가상머니") | 프론트 `signup` 동작 (데모용 가상머니) |
| D9 | 상품 | `account_products`에 `code varchar unique` 추가 (`basic`, `parking`, `youth`, `living`, `group`). 상품 설명·혜택 원문은 당분간 프론트 `mock.ts`가 원본이고, DB에는 code·이름·금리만 둔다 | 프론트와 RAG(`rag/chunk.py`)가 `mock.ts` 상품을 읽음 |
| D10 | 카드 결제 분류 | `card_payments.category varchar` 추가 | 프론트 `CardTx.category`, 챗봇 소비 분석 |
| D11 | 에러 코드 | 프론트 `BankError` 코드를 그대로 쓴다 (5장) | 프론트 교체 시 화면 코드 수정 없음 |
| D12 | 한도 상한 | 1일 10,000,000원, 1달 50,000,000원, 1일 ≤ 1달 | 프론트 `MAX_LIMITS`, 기획서 미정 → 프론트 값 채택 |
| D13 | 받는 분 이름 | 조회 응답에서 **마스킹** (`홍*동`). 본인 계좌면 계좌 별칭 그대로 | 기획서 9.2 마스킹. 프론트 Mock은 원문 노출 중 → 프론트도 맞춰야 함 |
| D14 | AI 송금 | 2026-11-05 사용자 진행 승인 후 Claude 구현에 맞춤: `/agent/chat` → 확인 화면 → PIN → `/agent/confirm`에서 공통 이체 실행. 일반 이체 화면은 `/transfers` 사용. 동일 AI 확인에서 두 API를 함께 호출하지 않는다 | 사용자가 보고한 에이전트 구현과 이후 제안·진행 승인. 이전 프론트 Mock 방식 교체 필요 |
| D15 | 결제 시뮬레이션 | 실제 카드사 연동이 없으므로 `POST /cards/{id}/payments` 시뮬레이션 API로 결제를 만든다 | D1.3 사용내역, D1.5 결제 알림 시연 |

D1, D6, D9, D10은 `bank.dbml` / `db-design.md`에도 반영해야 한다 (Phase 0 첫 작업).

## 3. 코드 규칙

### 3.1 폴더와 계층
```text
backend/app/
  main.py            라우터 등록, 예외 핸들러
  config.py, db.py   설정, DB 세션
  models.py          모든 테이블 (bank.dbml과 1:1)
  security.py        해시, JWT, current_user 의존성, PIN 확인
  errors.py          BankError(code, message, status)
  services/          업무 규칙. DB를 직접 다루는 유일한 곳 (API·스케줄러·에이전트가 공유)
    accounts.py  transfers.py  auth.py  verification.py  auto_transfers.py
    cards.py  notifications.py  mail.py
  api/               HTTP 입출력만 (pydantic 검증 → service 호출 → dict 반환)
    auth.py  accounts.py  transfers.py  auto_transfers.py  cards.py  notifications.py  agent.py
  scheduler.py       자동이체 실행 루프
  agent/             LangGraph (graph.py, rag.py)
tests/               pytest, SQLite 메모리 DB
```
- **API 라우터에 업무 규칙을 쓰지 않는다.** 검증·상태 판단은 `services/`에 둬야 스케줄러와 에이전트가 같은 규칙을 쓴다.
- 새 파일은 위 목록 안에서만 만든다. 한 서비스에 함수가 몇 개뿐이면 기존 파일에 넣는다.

### 3.2 필수 규칙
| 규칙 | 방법 |
|---|---|
| 소유자 확인 (B5.1) | 계좌·카드·거래를 id로 받으면 반드시 `get_owned_account(db, user_id, id)` 같은 함수로 `user_id` 조건을 걸어 조회. 남의 것은 **404** (존재 여부를 숨김) |
| 상태별 허용 (B5.2) | `assert_allowed(account, action)` 하나로 검사. action: `READ / DEPOSIT / WITHDRAW / MANAGE / CLOSE`. SUSPENDED의 `UNLOCK`만 예외 |
| 돈이 움직이는 작업 | 반드시 `services/transfers.transfer()` 또는 같은 패턴(계좌 id 오름차순 `with_for_update` + `populate_existing`, 한 트랜잭션, 성공 시 commit·실패 시 rollback) |
| 중복 제출 (기획서 공통) | 이체: `idempotency_key`. 카드 발급·해지·계좌 개설: 상태 검사로 중복 차단 (예: 같은 계좌에 발급 처리 중 카드가 있으면 거부) |
| 금액 | Python `int`, DB `bigint`. float 금지. 입력은 `Field(gt=0)` |
| 시간 | `models.now_kst()` 사용. 날짜 경계(오늘·이번 달)는 KST 기준 |
| 비밀값 | 비밀번호·PIN·통장비번·인증번호는 `security.hash_secret`. 응답·로그·예외 메시지에 원문 금지 |
| 카드번호 | 암호화 저장 (`cryptography.Fernet`, 키는 `.env`의 `CARD_KEY`). 응답은 `last4`만 |
| 마스킹 | 계좌번호는 목록 응답에서 `123-****-5678`, 상세에서만 전체. 타인 이름은 `mask_name` |
| 에러 | `raise BankError(code, message, status)`. code는 5장 표에 있는 것만. 메시지는 프론트 문구와 같은 한국어 존댓말 |

### 3.3 응답 형식
- 성공: 리소스 JSON (camelCase 아님, **snake_case**). 프론트 API 클라이언트가 변환한다.
- 실패: `{"code": "...", "message": "..."}` + HTTP 상태 (400 입력/업무 오류, 401 인증, 403 잠김, 404 없음·남의 것, 409 중복).
- 날짜·시각: ISO 8601 문자열.

## 4. 작업 단계

각 단계는 **완료 조건의 테스트가 통과해야 끝**이다. 테스트는 `tests/test_<영역>.py`에 SQLite 메모리 DB로 작성 (`tests/test_transfer.py` 픽스처 참고). API 수준 테스트는 FastAPI `TestClient` + `app.dependency_overrides[get_db]` (httpx를 dev 의존성에 추가).

### Phase 0. 스키마 정렬 ✅ (2026-11-05, Docker PostgreSQL 적용·alembic check 완료)
- [x] `docs/bank.dbml`, `docs/db-design.md`에 결정 D1·D6·D9·D10 반영
- [x] `app/models.py`를 `bank.dbml`과 1:1로 다시 작성 (uuid id는 `sqlalchemy.Uuid`, CHECK `balance >= 0` 유지)
- [x] 서비스·API·테스트를 새 이름으로 수정, 에러 코드를 5장 표로 교체, D4 PIN 규칙 구현
- [x] 마이그레이션 재생성: `0001_initial_tables.py` (rev-id를 `0001`, `0002`처럼 짧게 붙인다: `alembic revision --autogenerate --rev-id 0003 -m "..."`)
- [x] 시드 `0002_seed_products_terms.py`: 상품 5개, 약관 5개
- [x] SQLite에서 `upgrade head` → `alembic check` 차이 없음 → `downgrade base` 확인, API 흐름(가입→로그인→개설→이체→같은 키 재전송→PIN 5회 오류→거래중지, 남의 계좌 404, 토큰 없음 401) 확인
- [x] 사용자 요청에 따라 로컬 PostgreSQL 대신 Docker Compose 사용. PostgreSQL 17 컨테이너에 `0001`, `0002` 적용 후 실제 가입·로그인·기본 통장·원장·잠금·비밀번호 재설정 흐름 확인.

### Phase 1. 회원·인증 (A1, A2, A3) ✅ (2026-11-05)
- [x] `services/mail.py`: STARTTLS 메일 발송. 8장의 비밀값 로그 금지에 맞춰 콘솔 출력 대신 **명시적 DEVELOPMENT=true + SMTP 미설정일 때만 dev_code 응답**. 실제 Gmail 수신·검증과 발신자 이름 '내금고' 표시를 사용자가 확인함.
- [x] `services/verification.py`: 6자리, 3분, 해시 저장, 최신 행·용도·5회 제한, 인증 후 10분 유효. 가입·비밀번호 재설정 성공 시 소비해 재사용 차단.
- [x] 가입: 이메일 중복 확인 → 인증번호 → 필수 약관 동의 확인 → 회원 생성 + 약관 동의 기록 + D8 기본 통장 (한 트랜잭션)
- [x] 로그인: 이메일+비밀번호 / 이메일+PIN. 실패 시 `login_histories` 기록, 5회 → `LOCKED` (존재하지 않는 회원은 FK 제약상 접속 기록을 저장하지 않음)
- [x] 이상 접속: 성공 로그인의 IP·user_agent가 직전 성공 기록과 다르면 `notifications`에 `SUSPICIOUS_LOGIN`
- [x] PIN 확인 공통 함수: D4 규칙 (`verify_pin(db, user, pin, account=None)`), 사용자·계좌 행 잠금
- [x] 계정 관리: 내 정보 조회·변경(이름·휴대폰), 비밀번호 재설정(인증번호 `RESET_PW`), 탈퇴(`WITHDRAWN`, 해지 안 된 계좌가 있으면 거부 — 기획서 미정이라 기본값). 기존 JWT도 매 요청 회원 상태 확인.
- **완료 조건 (기획서 TC)**: TC-F-001 가입, TC-F-002 로그인, TC-E-001 필수 미동의·인증 실패·PIN 불일치 차단, TC-S-002 5회 잠금·만료 토큰 거부

### Phase 2. 계좌 (B1~B5) ✅ (2026-11-05)
- [x] 개설: 상품 code, 필수 약관 동의, 통장 비밀번호 4자리+확인, 개설 목적(`opening_info`, 비어 있으면 거부) → 계좌번호 3-4-4 발급(UNIQUE 충돌 시 저장점으로 최대 5회 재시도), 기본 한도. 계좌·약관 기록 한 트랜잭션.
- [x] 목록(즐겨찾기 먼저, 해지 제외, 계좌번호 마스킹) / 해지 계좌 목록 / 상세(전체 번호, `today_used`, `month_used`). 사용액과 이체 검사에 D7을 함께 반영.
- [x] 거래내역: 달력 기준 기본 3개월(말일 보정), 입출금, 정렬, 정확한 금액·범위, 상대방·적요 검색, 거래유형, 거래 상세. `from/to`와 기존 `start/end` 지원.
- [x] 즐겨찾기 토글, 한도 변경(PIN, D12 검증), 거래중지 해제(내 이메일의 인증번호 `UNLOCK_ACCOUNT` → `ACTIVE`, `pin_fail_count` 0), 해제 번호 소비. `/pin/verify`도 추가.
- [x] 해지: `close-check` + PIN 해지. 거래중지·잔액·연결 카드·출금계좌의 ACTIVE 자동/예약이체 차단. 이미 폐기된 `CANCELED/REISSUED` 카드는 차단에서 제외. 해지 후 거래내역 보관·조회, PIN 오류로 해지 계좌가 다시 열리는 경로 차단.
- [x] 다운로드 신청: `statement_requests` → UTF-8 BOM CSV 첨부 → `SENT/FAILED`. 모의 SMTP 테스트와 PostgreSQL API 흐름 확인. 실제 첨부메일 수신은 미확인. 개발 모드 SMTP 미설정도 실제 발송이 아니므로 `FAILED`.
- **검증 결과**: SQLite 전체 43개 통과. Docker PostgreSQL에서 FastAPI TestClient로 개설·조회·검색·한도·잠금·해제·해지·CSV·타인 차단 확인. 검사 데이터는 외부 트랜잭션으로 모두 rollback, 실제 메일은 보내지 않음.
- **완료 조건**: TC-F-003, TC-F-004, TC-F-007, TC-F-008, TC-E-005, TC-S-001(남의 계좌 404), TC-S-003

### Phase 3. 이체 (C1, C3) ✅ (2026-11-05)
- [x] 받는 분 조회 (D13 마스킹, `mine` 여부). 거래중지·해지 계좌는 수취 불가 응답.
- [x] 즉시이체: PIN(D4) → `transfer()`. 양의 정수만 허용, 한도·잔액·계좌 상태와 소유자 검증. 기존 `transfer(db, from_account_id, to_account_id, amount, idempotency_key, memo=None, auto_transfer_id=None)` 호출 규격 유지.
- [x] 결과 조회: `GET /transfers/by-key/{idempotency_key}`. 사용자별 키 범위·소유자 검증, 당시 OUT 원장의 `new_balance` 반환. 같은 키에 다른 수취인·금액·메모를 보내면 `INVALID_AMOUNT` + 409로 거부.
- [x] 최근 보낸 계좌: 성공 이체에서 받는 계좌별 최신 10개. `GET/POST /favorite-recipients`, `PATCH/DELETE /favorite-recipients/{id}`. 예금주명은 DB에서 가져와 응답에서 마스킹. 같은 회원·계좌 중복 등록은 별칭 갱신으로 처리.
- **완료 조건**: TC-F-005, TC-E-002(잔액 부족·한도 초과·거래중지 각각 원장 변경 없음), TC-E-003(같은 키 2번 → 1번만 송금), TC-E-004
- [x] **동시성 확인**: PostgreSQL에서 첫 중복 조회를 barrier로 동기화해 ① 동일 요청 2개 → 이체 1건 ② 잔액 부족 동시 출금 → 한 건 거부 ③ 반대 방향 송금 → 교착 없음 ④ 서로 다른 계좌 쌍의 동일 키 → 한 건만 확정 확인. 임시 스키마에서 검사 후 제거.
- **병행 작업 보호**: Claude는 `app/agent/`와 `api/agent.py`를 작업 중이다. 이번 변경은 이체 API·서비스·이체 전용 테스트·이 문서만 수정. 공유 인증·모델·앱 등록·에이전트·설정은 변경하지 않음. 전체 이미지 재빌드 대신 이체 파일만 읽기 전용 연결한 별도 임시 컨테이너에서 검사했다. 실행 중 8001 API에 반영하려면 병행 작업 완료 후 재빌드해야 한다.
- **요청 키 길이**: HTTP 키는 8~58자. `user:{UUID}:` 접두사와 합쳐 기존 DB의 100자 제한을 지킨다. 에이전트가 직접 호출하는 서비스의 키 규격은 유지.

### Phase 4. 자동이체·예약이체 (C2) + 스케줄러 ✅ (2026-11-05)
- [x] PIN 등록(ONCE: 시간대 포함 미래 시각 / WEEKLY·MONTHLY: 실행일·시작일·종료일 검증), 본인 목록, 해지(`CANCELED`)
- [x] `scheduler.py`: APScheduler를 FastAPI lifespan에서 시작, **1분마다** due 행 조회. 프로세스 시작 시에도 한 번 조회. 건별로 `transfer(..., idempotency_key=f"auto:{id}:{KST시각:%Y%m%d%H%M}", auto_transfer_id=id, commit=False)` 사용.
  - 성공·실패 모두 다음 회차 계산 (ONCE는 `ENDED`, 종료일 지나면 `ENDED`). 매월 31일처럼 없는 날은 **그 달 말일**에 실행 (기획서 미정, 기본값)
  - 실패 시 `notifications`에 `AUTO_TRANSFER_FAIL` (사유 포함). 재시도 없음 (기획서 미정)
  - 서버 여러 대는 고려하지 않음 (`ponytail:` 주석으로 표시)
- [x] 회차 이체·원장·성공/실패 결과·다음 회차·실패 알림을 한 트랜잭션으로 저장. `transfer`는 기존 호출을 유지하고 선택 키워드 `commit=False`만 추가. 실패는 저장점 rollback 후 FAILED 이체 기록, 회차 재시도 없음.
- [x] PostgreSQL 동시 실행: `FOR UPDATE SKIP LOCKED`로 같은 회차의 성공·실패 중복 실행 차단. 이체 후 다음 회차 계산에서 오류가 나도 돈과 원장이 모두 rollback되는지 검증.
- 정기 이체 시각은 기획서 미정 기본값 **KST 09시**. 중단 기간의 누락 회차는 한 번만 처리하고 다음 미래 회차로 이동. 종료일이 지난 일정은 실행하지 않고 종료. `SCHEDULER_ENABLED`는 로컬 기본 false, Compose 기본 true.
- **완료 조건**: TC-F-006 (같은 회차를 두 번 실행해도 이체 1건), 다음 회차 날짜 계산 테스트 (월말·종료일)

### Phase 5. 카드 (D1) ✅ (2026-11-05)
- [x] 발급: 본인 ACTIVE 계좌, 일일 한도, 해외결제 → Luhn 16자리, Fernet 암호화, +5년 유효기간. 같은 계좌의 사용 가능한 카드 중복 발급은 계좌 잠금과 상태 검사로 거부.
- [x] 목록·상세, PIN 한도·해외결제 변경, 분실·정지/해제·해지(`/cancel`), 재발급(이전 카드 REISSUED, 새 카드 reissued_from_id). 분실·폐기 카드 재활성화 차단.
- [x] 결제 시뮬레이션(D15): ACTIVE·미만료 카드, 출금 가능 계좌, 카드 일일 한도·해외결제 검사 → 결제·원장·CARD_PAYMENT 알림 원자적 저장. 계좌→카드 순서 잠금. 잔액/한도 동시 결제 검증 완료.
- [x] 카드별·월별 사용내역. 실제 카드번호·CVC는 응답하지 않음. 가상 카드 네트워크 LOCAL. 카드 일일 한도 상한은 데모 기본값 1천만원.
- **Claude 연결 함수**: `cards.last4(card)`로 끝자리 표시·매칭 (`card.card_number[-4:]`는 암호문이므로 금지). PIN 확인 후 `cards.set_card_status(db, user_id, card_id, status)`로 상태 변경. 기존 agent 함수와 동일한 인자·Card 반환. API 직렬화는 `cards.card_out(card)`.
- `CARD_KEY`를 `.env.docker`에 생성·보관했으며 Compose로 주입. 기존 키를 바꾸면 저장된 카드번호를 읽을 수 없으므로 유지할 것. 모델·마이그레이션 변경 없음.
- **완료 조건**: TC-F-009, 정지·분실 카드 결제 거부, 카드 한도 초과 거부

### Phase 6. 알림 (A2.4, D1.5) ✅ (2026-11-05)
- [x] 본인 알림 최신순 목록·안 읽은 개수·모두 읽음. 타인 알림 미노출·읽음 상태 유지 검증.
- 카드 결제와 자동이체 실패를 저장하며, 이상 접속 알림은 기존 회원 서비스가 저장한다.
- 프론트 Mock의 `notices`는 입금·예약 결과를 거래에서 계산한다. 백엔드는 알림을 **저장**하므로, 입금(`DEPOSIT`/이체 IN)도 알림으로 남길지는 프론트 연결 때 정한다 (기본: 카드결제·이상접속·자동이체 결과만)

### Phase 7. 에이전트 2단계 (agent-design.md)
현재는 Claude가 조회·송금·카드 정지·PIN 확인을 구현했고 사용자가 완료를 보고했다. 아래 항목은 이전 계획이며, D14의 현재 `/agent/confirm` 계약을 우선한다. 공통 카드 서비스 교체와 프론트 연결은 Claude 담당이다.
- 1단계(FINANCE_QA)는 `app/agent/`에 이미 있다. **수정 전에 사용자에게 다른 세션이 작업 중인지 확인한다.**
- [ ] `/agent/chat`에 `current_user_id` 필수화
- [ ] ACCOUNT_QUERY: `services/`의 조회 함수를 도구로 감싼다 (user_id는 클로저로 고정, LLM 인자에 없음) → `accounts`, `transactions`, `spending` 블록
- [ ] TRANSFER: 슬롯(받는 분·금액·출금계좌) 추출 → 받는 분은 코드가 즐겨찾기·최근 계좌에서 매칭 → 부족하면 `choices` 블록으로 되묻기 → 완성되면 `transferConfirm` 블록 반환 (D14, 실행은 프론트)
- [ ] 대화 맥락은 프론트가 보내는 `context`(ChatContext)로 유지. 서버 체크포인터 불필요
- **완료 조건**: 남의 계좌 조회 요청 거부, 적요에 넣은 지시문이 동작을 바꾸지 않음, 확인 없이 송금되는 경로 없음

### Phase 8. 프론트 연결 (백엔드 범위 밖, 참고)
`src/store.tsx`의 각 함수를 6장 API 호출로 바꾼다. 응답 snake_case → 프론트 타입 변환은 API 클라이언트 한 곳에서.

## 5. 에러 코드

프론트 `BankError` 코드와 같다. 백엔드의 기존 코드(`ACCOUNT_NOT_ALLOWED`, `DAILY_LIMIT_EXCEEDED` 등)는 Phase 0~3에서 이 표로 바꾼다.

| code | HTTP | 언제 | 메시지 예 |
|---|---|---|---|
| `AUTH` | 401 | 이메일·비밀번호 불일치, 토큰 만료·위조 | 이메일 또는 비밀번호가 일치하지 않아요. |
| `USER_LOCKED` | 403 | 회원 잠금 상태로 로그인 | 잠긴 계정이에요. 비밀번호 재설정으로 풀어 주세요. |
| `DUPLICATE_EMAIL` | 409 | 가입 이메일 중복 | 이미 가입된 이메일이에요. |
| `CODE` | 400 | 인증번호 불일치·만료·5회 초과·미인증 | 인증번호가 맞지 않아요. 다시 확인해 주세요. |
| `TERMS_REQUIRED` | 400 | 필수 약관 미동의 | 필수 약관에 동의해 주세요. |
| `PIN` | 401 | PIN 불일치 (n/5) | 비밀번호가 맞지 않아요. (2/5) |
| `PIN_LOCKED` | 403 | PIN 5회 → 거래중지, 또는 거래중지 계좌에 PIN 시도 | 비밀번호를 5회 틀려 이 계좌의 거래가 중지됐어요. … |
| `INVALID_FROM` | 404 | 출금 계좌 없음·남의 것·해지됨 | 출금 계좌를 찾을 수 없어요. |
| `INVALID_ACCOUNT` | 404/400 | 받는 계좌 없음, 받을 수 없는 상태 | 존재하지 않는 계좌예요. 계좌번호를 다시 확인해 주세요. |
| `SAME_ACCOUNT` | 400 | 같은 계좌로 이체 | 출금 계좌와 같은 계좌로는 보낼 수 없어요. |
| `SUSPENDED` | 400 | 거래중지 계좌에서 출금·관리 | 거래가 중지된 계좌예요. 계좌 관리에서 본인인증으로 해제해 주세요. |
| `INVALID_AMOUNT` | 400/409 | 0 이하·정수 아님, 또는 이미 처리된 키에 다른 요청(409) | 송금 금액을 확인해 주세요. |
| `PASSWORD_MISMATCH` | 400 | 계좌 개설 4자리 비밀번호 확인 불일치 (기존 API 코드 유지) | 통장 비밀번호가 서로 달라요. |
| `LIMIT` | 400 | 1일·1달 이체한도 초과 (남은 금액 포함) | 1일 이체한도를 넘어요. 오늘 300,000원까지 보낼 수 있어요. |
| `INSUFFICIENT` | 400 | 잔액 부족 (출금 가능액 포함) | 잔액이 부족해요. 출금 가능 금액은 12,000원이에요. |
| `INVALID_LIMIT` | 400 | 한도 변경값 오류 (D12) | 1일 한도는 1달 한도보다 클 수 없어요. |
| `INVALID_TIME` | 400 | 예약 시각이 과거, 날짜 조합 오류 | 예약 시각은 지금 이후로 골라 주세요. |
| `CLOSE_BLOCKED` | 400 | 해지 차단 사유 있음 (첫 사유) | 잔액 5,000원이 남아 있어요. 다른 계좌로 옮긴 뒤 해지할 수 있어요. |
| `INVALID_PRODUCT` | 404 | 없는 상품 code | 상품 정보를 찾을 수 없어요. |
| `CARD_NOT_FOUND` | 404 | 카드 없음·남의 것 | 카드를 찾을 수 없어요. |
| `CARD_UNAVAILABLE` | 400 | 정지·분실·재발급된 카드로 결제·변경 | 사용할 수 없는 카드예요. |
| `CARD_LIMIT` | 400 | 카드 일일 사용한도 초과 | 오늘 카드 사용한도를 넘어요. |
| `OVERSEAS_BLOCKED` | 400 | 해외결제 꺼진 카드로 해외결제 | 해외결제가 꺼져 있어요. |

## 6. API 명세

인증: 🔒 = `Authorization: Bearer <JWT>` 필요. 프론트 함수는 `src/store.tsx` 기준.

### 6.1 회원·인증
| Method | Path | 🔒 | 요청 | 응답 | 프론트 함수 | 기획서 |
|---|---|---|---|---|---|---|
| GET | `/auth/email-available?email=` | | | `{available}` | `checkEmail` | A1 |
| POST | `/auth/codes` | | `{email, purpose}` | `{expires_at}` (개발 모드면 `dev_code` 포함) | `sendUnlockCode` 등 | A1, A3, B3.3.2 |
| POST | `/auth/codes/verify` | | `{email, purpose, code}` | `{verified: true}` | | A1 |
| GET | `/terms?category=` | | | `[{id, title, version, required, content}]` | | A1, B1.2 |
| POST | `/auth/signup` | | `{email, password, pin, name, phone_num?, agreed_term_ids}` | `{id}` 201 | `signup` | A1 |
| POST | `/auth/login` | | `{email, password}` | `{access_token}` | `login` | A2.1 |
| POST | `/auth/login/pin` | | `{email, pin}` | `{access_token}` | | A2.1 |
| POST | `/auth/password/reset` | | `{email, code, new_password}` | 204 | | A3 |
| GET | `/me` | 🔒 | | `{id, email, user_name, phone_num, created_at}` | `user` | A3 |
| PATCH | `/me` | 🔒 | `{user_name?, phone_num?}` | `/me`와 같음 | | A3 |
| DELETE | `/me` | 🔒 | `{password}` | 204 | | A3 |

로그아웃은 API 없음 (프론트가 토큰 삭제, D3).

### 6.2 계좌
| Method | Path | 🔒 | 요청 | 응답 | 프론트 함수 | 기획서 |
|---|---|---|---|---|---|---|
| GET | `/products` | | | `[{code, product_name, interest_rate}]` | `products` | B1.1 |
| POST | `/accounts` | 🔒 | `{product_code, password, password_confirm, opening_info, agreed_term_ids}` | 계좌 | `openAccount` | B1 |
| GET | `/accounts?status=active\|closed` | 🔒 | | `[계좌]` 즐겨찾기 먼저 | `myAccounts`, `closedAccounts` | B2.1 |
| GET | `/accounts/{id}` | 🔒 | | 계좌 + `today_used`, `month_used` | | B2.2, B2.8 |
| GET | `/accounts/{id}/transactions` | 🔒 | `from, to, direction, type, min, max, q, order` | `[거래]` | | B2.3~B2.6 |
| GET | `/accounts/{id}/transactions/{tx_id}` | 🔒 | | 거래 | | B2.4 |
| POST | `/accounts/{id}/favorite` | 🔒 | | `{is_favorite}` (토글) | `toggleFavorite` | B3.1 |
| PUT | `/accounts/{id}/limits` | 🔒 | `{daily_limit, month_limit, pin}` | 계좌 | `setLimits` | B3.2 |
| POST | `/accounts/{id}/unlock` | 🔒 | `{code}` (purpose=UNLOCK_ACCOUNT, 내 이메일) | 계좌 | `unlockAccount` | B3.3.2 |
| GET | `/accounts/{id}/close-check` | 🔒 | | `{closable, blockers:[{kind, text}]}` | `closeBlockers` | B4.1 |
| POST | `/accounts/{id}/close` | 🔒 | `{pin}` | 계좌 | `closeAccount` | B4.2, B4.3 |
| POST | `/accounts/{id}/statements` | 🔒 | `{from_date, to_date, email}` | `{id, status}` 202 | | B2.7 |
| POST | `/pin/verify` | 🔒 | `{pin, account_id?}` | 204 | `verifyPin` | D4 |

계좌 응답: `{id, product_code, product_name, account_num, nickname, balance, status, is_favorite, daily_limit, month_limit, created_at, closed_at}`
거래 응답: `{id, account_id, transaction_type, transaction_direction, amount, new_balance, counterparty_name, counterparty_account, memo, transaction_at}`

### 6.3 이체
| Method | Path | 🔒 | 요청 | 응답 | 프론트 함수 | 기획서 |
|---|---|---|---|---|---|---|
| GET | `/transfers/recipient?account_num=` | 🔒 | | `{account_num, holder_name(마스킹), mine}` | `lookupAccount` | C1.1 |
| POST | `/transfers` | 🔒 | `{from_account_id, to_account_num, amount, memo?, pin, idempotency_key}` | `{transfer_id, status, amount, to_name, to_account_num, new_balance}` 201 | `transfer` | C1 |
| GET | `/transfers/by-key/{idempotency_key}` | 🔒 | | 위와 같음 / 404 | | TC-E-004 |
| GET | `/transfers/recent` | 🔒 | | `[{account_num, holder_name, last_sent_at}]` | `recipients` | C3 |
| GET / POST / DELETE | `/favorite-recipients[/{id}]` | 🔒 | `{account_num, alias?}` | | | C3 |

### 6.4 자동이체·예약이체
| Method | Path | 🔒 | 요청 | 응답 | 프론트 함수 | 기획서 |
|---|---|---|---|---|---|---|
| POST | `/auto-transfers` | 🔒 | `{from_account_id, to_account_num, amount, pin, memo?, cycle, run_at?(ONCE), run_day?, start_date?, end_date?}` | 자동이체 + `last_run` | `scheduleTransfer` | C2 |
| GET | `/auto-transfers?status=` | 🔒 | | `[자동이체 + 최근 실행 결과]` | `scheduled` | C2 |
| DELETE | `/auto-transfers/{id}` | 🔒 | | 204 (`CANCELED`) | `cancelScheduled` | C2 |

### 6.5 카드
| Method | Path | 🔒 | 요청 | 응답 | 기획서 |
|---|---|---|---|---|---|
| POST | `/cards` | 🔒 | `{account_id, daily_limit, overseas_enabled}` | 카드 | D1.1 |
| GET | `/cards` | 🔒 | | `[카드]` | D1.2 |
| GET | `/cards/{id}` | 🔒 | | 카드 | D1.3 |
| PATCH | `/cards/{id}` | 🔒 | `{daily_limit?, overseas_enabled?, pin}` | 카드 | D1.3 |
| POST | `/cards/{id}/lost` | 🔒 | `{pin}` | 카드 | D1.3 |
| POST | `/cards/{id}/suspend`, `/resume` | 🔒 | `{pin}` | 카드 | D1.3 |
| POST | `/cards/{id}/reissue` | 🔒 | `{pin}` | 새 카드 | D1.4 |
| POST | `/cards/{id}/cancel` | 🔒 | `{pin}` | 해지 카드 | 계좌 해지 제약 해소 |
| GET | `/cards/{id}/payments?month=YYYY-MM` | 🔒 | | `[결제]` | D1.3 |
| POST | `/cards/{id}/payments` | 🔒 | `{amount, place, category, overseas?}` | 결제 (시뮬레이션, D15) | D1.5 |

카드 응답: `{id, account_id, last4, expiry_date, card_network, daily_limit, overseas_enabled, status, created_at}` — 전체 카드번호는 어떤 응답에도 넣지 않는다.

### 6.6 알림·에이전트
| Method | Path | 🔒 | 요청 | 응답 | 프론트 함수 |
|---|---|---|---|---|---|
| GET | `/notifications` | 🔒 | | `{items:[...], unread}` | `notices`, `unread` |
| POST | `/notifications/read-all` | 🔒 | | 204 | `markNoticesRead` |
| POST | `/agent/chat` | 🔒(Phase 7부터) | `{message, context}` | `{blocks, context}` (`src/api/chat.ts` 타입) | `ChatClient.send` |

## 7. 실행·테스트 방법

```bash
cd backend
uv sync
cp .env.example .env    # DATABASE_URL, JWT_SECRET (사용자가 채움), CARD_KEY, SMTP_* (선택)
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --env-file .env   # http://localhost:8000/docs
uv run pytest
```
- 마이그레이션은 모델 수정 후 `uv run alembic revision --autogenerate -m "설명"` → 생성 파일을 **읽고** 확인 → `upgrade head`.
- PostgreSQL 비밀번호는 사용자만 안다. 추측하거나 다른 계정을 만들지 말고 사용자에게 `.env`를 채워 달라고 한다.

## 8. 하지 말 것
- CVC 저장, 카드번호 평문 저장·응답, PIN·비밀번호·인증번호 로그 출력
- float로 금액 계산, 원장(`account_transactions`) 행 수정·삭제
- API 라우터에서 직접 잔액 변경 (항상 서비스 함수)
- 기획서 "선택" 기능(소셜 로그인, 다건이체, 신용카드, 신분증 확인) 구현
- 기획서 미정 정책을 확정된 것처럼 문서에 쓰기 (기본값은 코드에 `ponytail:` 또는 주석으로 "기획서 미정, 기본값"이라 표시)
- 저장소 폴더 이동 (`rag/`, `data/rag/`, `src/`는 다른 작업과 경로로 연결됨)
- `app/agent/`, `rag/` 수정 (Phase 7 전까지. 다른 세션이 작업 중일 수 있음)

## 9. 기획서 미정 정책 — 지금 쓰는 기본값

| 항목 | 기본값 | 확정되면 바꿀 곳 |
|---|---|---|
| 잠금 횟수 | 로그인·PIN 모두 5회 | `security.MAX_FAILS` |
| 무활동 로그아웃 시간 | 토큰 15분 (프론트 타이머도 15분) | `config.access_token_minutes` |
| 거래중지 계좌 입금 | 차단 (상태표 제안안대로) | `services/accounts.ALLOWED` |
| 거래중지 계좌의 카드 결제 | 차단 | `services/cards` 결제 검사 |
| 자동이체 실패 재시도 | 없음, 알림만 | `scheduler.py` |
| 자동이체 말일 처리 | 없는 날짜면 그 달 말일 | `services/auto_transfers.next_run` |
| 다운로드 형식 | CSV, 이메일 첨부 | `services/mail.py` |
| 회원 탈퇴 제한 | 해지 안 된 계좌가 있으면 거부 | `services/auth.withdraw` |
| 카드 변경 인증 | PIN | `api/cards.py` |
