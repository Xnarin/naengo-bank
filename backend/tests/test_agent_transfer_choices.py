from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.agent import graph as agent
from app.models import AutoTransfer, FavoriteRecipient, Transfer
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


@pytest.mark.parametrize("scheduled", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_source_choice_advances_without_model(bank, monkeypatch, scheduled, legacy):
    _, db, user, _, source, mine, target = bank
    source.nickname = "내금고 입출금통장"
    mine.nickname = "내금고 파킹통장"
    db.commit()
    intent = "AUTO_TRANSFER" if scheduled else "TRANSFER"
    slots = agent.AutoTransferSlots(amount=10000, cycle="MONTHLY") if scheduled else agent.TransferSlots(amount=10000)
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent=intent)))
    monkeypatch.setattr(agent, "auto_slot_llm" if scheduled else "slot_llm", SimpleNamespace(invoke=lambda _: slots))
    start = agent.run("매월 15일에 만원 자동이체해줘" if scheduled else "만원 보내줘", db=db, user_id=user.id)
    choose_source = agent.run(target.account_num, thread_id=start["thread_id"], db=db, user_id=user.id)
    assert choose_source["answer"] == "어느 계좌에서 보낼까요?"
    options = choose_source["blocks"][0]["options"]
    assert {o["value"] for o in options} == {f"{source.account_num}에서", f"{mine.account_num}에서"}

    def unexpected_model_call(_):
        raise AssertionError("출금 계좌 버튼은 모델 없이 처리해야 한다")

    for name in ("router_llm", "slot_llm", "auto_slot_llm"):
        monkeypatch.setattr(agent, name, SimpleNamespace(invoke=unexpected_model_call))
    message = "내금고 입출금통장에서" if legacy else options[0]["value"]
    selected = agent.run(message, thread_id=start["thread_id"], db=db, user_id=user.id)
    assert selected["status"] == "confirm"
    assert selected["intent"] == intent
    assert selected["confirm"]["출금 계좌"].endswith("111-****-1111")
    assert selected["confirm"]["받는 계좌"] == "333-****-3333"
    assert selected["confirm"]["금액"] == 10000
    if scheduled:
        assert selected["confirm"]["주기"] == "매월 15일"
    assert db.scalar(select(func.count()).select_from(Transfer)) == 0
    assert db.scalar(select(func.count()).select_from(AutoTransfer)) == 0


def test_source_choices_distinguish_duplicate_names_and_reject_invalid_accounts(bank, monkeypatch):
    _, db, user, _, source, mine, target = bank
    source.nickname = mine.nickname = "같은 이름"
    config = {"configurable": {"db": db, "user_id": user.id}}
    draft = {"auto": True, "amount": 10000, "cycle": "MONTHLY", "run_day": 15,
             "to": {"account_id": str(target.id), "account_num": target.account_num,
                    "holder_name": "홍길동", "alias": None}}

    def unexpected_model_call(_):
        raise AssertionError("계좌번호로 선택한 출금 계좌는 모델에 전달하지 않는다")

    monkeypatch.setattr(agent, "auto_slot_llm", SimpleNamespace(invoke=unexpected_model_call))
    assert agent.source_choice_hint({"message": "같은 이름에서", "draft": draft}, config) is None
    for invalid in (target.account_num, "999-9999-9999"):
        result = agent.transfer_slots({"message": f"{invalid}에서", "intent": "AUTO_TRANSFER", "draft": draft}, config)
        assert result["status"] == "ask" and "from_id" not in result["draft"]
        options = result["blocks"][0]["options"]
        assert len({o["label"] for o in options}) == 2
    result = agent.transfer_slots({"message": f"{mine.account_num}에서", "intent": "AUTO_TRANSFER", "draft": draft}, config)
    assert result["pending_action"]["from_account_id"] == str(mine.id)
    mine.status = "SUSPENDED"
    result = agent.transfer_slots({"message": f"{mine.account_num}에서", "intent": "AUTO_TRANSFER", "draft": draft}, config)
    assert result["status"] == "ask" and "from_id" not in result["draft"]
