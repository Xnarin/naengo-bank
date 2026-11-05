"""seed products and terms

상품 5개 (프론트 src/data/mock.ts의 products와 code·이름·금리가 같다)와 데모용 약관.
약관 본문은 데모 요약이다. 실제 예금거래기본약관 전문은 data/rag/terms/에 있다.

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRODUCTS = [
    ("basic", "내금고 입출금통장", 0.1, "수수료 걱정 없이 매일 쓰는 기본 통장"),
    ("parking", "내금고 파킹통장", 2.5, "하루만 맡겨도 이자가 붙는 파킹통장"),
    ("youth", "내금고 청년 입출금통장", 3.0, "사회초년생을 위한 높은 금리 입출금통장"),
    ("living", "내금고 생활비통장", 1.2, "급여를 받으면 금리가 올라가는 생활비 통장"),
    ("group", "내금고 모임통장", 0.5, "친구·가족과 회비를 투명하게 관리해요"),
]

TERMS = [
    ("내금고 서비스 이용약관", True, "SIGNUP", "내금고 모바일 뱅킹 서비스의 이용 조건과 절차, 회사와 회원의 권리·의무를 정합니다. (데모 요약)"),
    ("개인정보 수집·이용 동의", True, "SIGNUP", "수집 항목: 이름, 이메일, 휴대폰 번호. 목적: 회원 식별, 본인확인, 거래 안내. 보유 기간: 회원 탈퇴 후 관계 법령에서 정한 기간. (데모 요약)"),
    ("마케팅 정보 수신 동의", False, "SIGNUP", "이벤트·혜택 안내를 이메일로 받습니다. 동의하지 않아도 서비스를 이용할 수 있습니다. (데모 요약)"),
    ("예금거래기본약관", True, "ACCOUNT_OPEN", "예금 거래에 관한 기본 사항을 정한 표준약관입니다. 전문: 공정거래위원회 표준약관 제10012호. (데모 요약)"),
    ("입출금통장 상품설명서 확인", True, "ACCOUNT_OPEN", "금리, 이자 지급 방식, 수수료, 예금자보호 여부를 확인했습니다. 이 예금은 예금자보호법에 따라 1인당 1억원까지 보호됩니다. (데모 요약)"),
]


def upgrade() -> None:
    products = sa.table("account_products", sa.column("code"), sa.column("product_name"),
                        sa.column("interest_rate"), sa.column("description"))
    op.bulk_insert(products, [dict(code=c, product_name=n, interest_rate=r, description=d) for c, n, r, d in PRODUCTS])
    terms = sa.table("terms", sa.column("title"), sa.column("content"), sa.column("version"),
                     sa.column("required"), sa.column("category"))
    op.bulk_insert(terms, [dict(title=t, required=req, category=cat, content=body, version="2026-11-05")
                           for t, req, cat, body in TERMS])


def downgrade() -> None:
    op.execute("DELETE FROM terms WHERE version = '2026-11-05'")
    op.execute("DELETE FROM account_products WHERE code IN ('basic', 'parking', 'youth', 'living', 'group')")
