# 백엔드 설계 (Backend Design)

> 기준 문서: `product-spec.md` v0.1 | 범위: 회원·인증, 계좌, 이체, 카드 (AI Agent는 `agent-design.md`)

## 1. 기술 스택

| 구성 | 선택 | 이유 |
|---|---|---|
| API | FastAPI | AI Agent(LangGraph, Python)가 이체·조회 함수를 HTTP 없이 직접 import해서 재사용 |
| DB | PostgreSQL | `SELECT ... FOR UPDATE` 행 잠금, 트랜잭션, CHECK 제약 |
| ORM·마이그레이션 | SQLAlchemy 2.0 + Alembic | |
| 인증 | PyJWT + argon2 | 비밀번호·PIN·통장 비밀번호는 모두 해시 저장 |
| 스케줄러 | APScheduler (앱 프로세스 내장) | 하루 1회 `next_run_date <= 오늘`인 자동이체 실행 |
| 프론트 | React + Vite (모바일 웹) | |

## 2. DB

테이블 구조와 설계 결정은 [`db-design.md`](db-design.md), 스키마 원본은 [`bank.dbml`](bank.dbml)을 본다.

## 3. 이체 공통 함수

즉시이체·자동이체 스케줄러·AI Agent가 모두 이 함수 하나를 호출한다.

```python
def transfer(db, from_id, to_id, amount, idem_key, memo=None, auto_id=None):
    with db.begin():
        if db.scalar(select(Transfer).where(Transfer.idempotency_key == idem_key)):
            return  # 중복 요청
        # 데드락 방지: 항상 id 오름차순으로 잠금
        locked = {x.id: x for x in db.scalars(
            select(Account).where(Account.id.in_([from_id, to_id]))
            .order_by(Account.id).with_for_update())}
        src, dst = locked[from_id], locked[to_id]
        assert_allowed(src, "WITHDRAW"); assert_allowed(dst, "DEPOSIT")  # B5.2
        check_limits(db, src, amount)                                     # 1일·1달 한도
        if src.balance < amount:
            raise InsufficientBalance
        src.balance -= amount
        dst.balance += amount
        t = Transfer(...); db.add(t); db.flush()
        db.add_all([
            Transaction(account_id=src.id, direction="OUT", balance_after=src.balance, transfer_id=t.id, ...),
            Transaction(account_id=dst.id, direction="IN",  balance_after=dst.balance, transfer_id=t.id, ...),
        ])
```

## 4. 계좌 상태별 허용 동작 (B5.2)

`assert_allowed(account, action)` 하나로 모든 계좌 API에서 검사한다.

```python
ALLOWED = {
    "ACTIVE":    {"READ", "DEPOSIT", "WITHDRAW", "MANAGE", "CLOSE"},
    "SUSPENDED": {"READ"},
    "CLOSED":    {"READ"},
}
```

해지 가능 여부 (B4.1): `balance == 0` AND 활성 카드 0개 AND 활성 자동이체 0개.

## 5. 범위에서 제외

- 타행 이체: 자행 계좌 간만 지원 (필요 시 `bank_code` 컬럼 추가)
- 신용카드(D2): 선택 기능, 테이블 미생성
- 신분증·추가 본인확인(B1.5, B1.6): 선택 기능, 진행 시 `accounts.opening_info`에 결과만 저장
