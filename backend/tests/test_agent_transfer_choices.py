from types import SimpleNamespace

from sqlalchemy import func, select

from app.agent import graph as agent
from app.models import FavoriteRecipient, Transfer
from app.services.transfers import transfer
from test_transfers_api import bank  # noqa: F401


def test_transfer_choices_select_exact_recipient_without_model(bank, monkeypatch):
    _, db, user, _, source, mine, target = bank
    source.is_favorite = True
    db.add(FavoriteRecipient(user_id=user.id, account_num=target.account_num, holder_name="홍길동", alias="길동이"))
    transfer(db, source.id, target.id, 1000, "이전 송금")

    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="TRANSFER")))
    monkeypatch.setattr(agent, "slot_llm", SimpleNamespace(invoke=lambda _: agent.TransferSlots(amount=10_000)))
    start = agent.run("1만원 송금해줘", db=db, user_id=user.id)
    favorite, recent, own, direct = start["blocks"]
    assert favorite["title"] == "즐겨찾기"
    assert favorite["options"] == [{"label": "길동이 · 333-****-3333", "value": target.account_num}]
    assert recent["title"] == "최근 송금한 사람"
    assert recent["options"][0]["label"] == "홍*동 · 333-****-3333"
    assert own["title"] == "내 계좌" and mine.account_num in [item["value"] for item in own["options"]]
    assert direct["options"] == [{"label": "계좌번호 직접 입력"}]

    def unexpected_model_call(_):
        raise AssertionError("계좌 선택은 코드에서 처리해야 한다")

    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=unexpected_model_call))
    monkeypatch.setattr(agent, "slot_llm", SimpleNamespace(invoke=unexpected_model_call))
    selected = agent.run(favorite["options"][0]["value"], thread_id=start["thread_id"], db=db, user_id=user.id)
    assert selected["status"] == "confirm"
    assert selected["confirm"]["받는 계좌"] == "333-****-3333"
    assert selected["confirm"]["금액"] == 10_000
    assert db.scalar(select(func.count()).select_from(Transfer)) == 1


def test_unknown_name_and_inactive_account_show_fallback(bank, monkeypatch):
    _, db, user, _, source, mine, target = bank
    target.status = "SUSPENDED"
    mine.status = "SUSPENDED"
    db.add(FavoriteRecipient(user_id=user.id, account_num=target.account_num, holder_name="홍길동"))
    db.commit()
    config = {"configurable": {"db": db, "user_id": user.id}}
    monkeypatch.setattr(agent, "slot_llm", SimpleNamespace(invoke=lambda _: agent.TransferSlots(recipient="김나연")))
    unknown = agent.transfer_slots({"message": "김나연"}, config)
    assert "즐겨찾기와 송금 내역" in unknown["answer"]
    assert all(block.get("title") is None for block in unknown["blocks"])
    invalid = agent.transfer_slots({"message": target.account_num.replace("-", ""), "draft": unknown["draft"]}, config)
    assert "송금할 수 있는 계좌를 찾지 못했어요" in invalid["answer"]
    assert invalid["blocks"][-1]["options"] == [{"label": "계좌번호 직접 입력"}]
    same_account = agent.transfer_slots({"message": source.account_num, "draft": invalid["draft"]}, config)
    assert "출금 계좌가 없어요" in same_account["answer"]
    assert "to" not in same_account["draft"]


def test_self_transfer_offers_only_owned_destinations(bank, monkeypatch):
    _, db, user, _, source, mine, _ = bank
    config = {"configurable": {"db": db, "user_id": user.id}}
    monkeypatch.setattr(agent, "slot_llm", SimpleNamespace(invoke=lambda _: agent.TransferSlots(recipient="나")))
    result = agent.transfer_slots({"message": "나한테 송금", "draft": {"amount": 10_000}}, config)
    assert result["answer"] == "내 계좌 중 어디로 보낼까요?"
    assert {item["value"] for item in result["blocks"][0]["options"]} == {source.account_num, mine.account_num}
    assert result["draft"] == {"amount": 10_000}
    mine.status = "SUSPENDED"
    db.flush()
    result = agent.transfer_slots({"message": "나한테 송금"}, config)
    assert "두 개 이상" in result["answer"]
    assert all(block.get("title") != "내 계좌" for block in result["blocks"])
