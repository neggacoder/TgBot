"""Очередь заявок рынка в админ-панели."""

from __future__ import annotations

import importlib
import asyncio
from datetime import datetime

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import db
from webpanel.auth import PanelUser

panel = importlib.import_module("webpanel.app")

CHAT_ID = -1001234567890
GOOD_ID = 42
SELLER_ID = 777


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text})


@pytest.fixture
def panel_client(monkeypatch):
    state = {
        "good": {
            "id": GOOD_ID, "chat_id": CHAT_ID, "seller_id": SELLER_ID,
            "item_key": "ogurec", "name": "Огурец", "price": 500,
            "status": "pending", "created_at": datetime(2026, 8, 13, 3, 35),
        },
        "logs": [],
    }
    bot = FakeBot()

    async def list_market_goods(chat_id, status="approved"):
        good = state["good"]
        return [dict(good)] if chat_id == CHAT_ID and good["status"] == status else []

    async def get_market_good_by_id(chat_id, good_id):
        if chat_id == CHAT_ID and good_id == GOOD_ID:
            return dict(state["good"])
        return None

    async def decide_market_good(chat_id, good_id, approve, admin_id):
        good = state["good"]
        if chat_id != CHAT_ID or good_id != GOOD_ID or good["status"] != "pending":
            return False
        good["status"] = "approved" if approve else "rejected"
        good["decided_by"] = admin_id
        return True

    async def get_known_user(chat_id, user_id):
        if chat_id == CHAT_ID and user_id == SELLER_ID:
            return {"full_name": "Коля", "username": "kolya"}
        return None

    async def add_log(kind, **kwargs):
        state["logs"].append(kind)

    async def allow(*args):
        return None

    monkeypatch.setattr(db, "list_market_goods", list_market_goods)
    monkeypatch.setattr(db, "get_market_good_by_id", get_market_good_by_id)
    monkeypatch.setattr(db, "decide_market_good", decide_market_good)
    monkeypatch.setattr(db, "get_known_user", get_known_user)
    monkeypatch.setattr(db, "add_log", add_log)
    monkeypatch.setattr(panel, "get_bot", lambda: bot)
    monkeypatch.setattr(panel.auth, "verify_csrf", lambda request: None)
    monkeypatch.setattr(panel.permissions, "ensure", allow)

    owner = PanelUser(id=1, username="owner", role="owner", tg_user_id=9)
    return {"state": state, "bot": bot, "user": owner}


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def decide(world, approve=True, good_id=GOOD_ID):
    return asyncio.run(panel.api_market_decision(
        good_id,
        panel.MarketDecisionBody(chat_id=CHAT_ID, approve=approve),
        _request(),
        world["user"],
    ))


def listing(world):
    return asyncio.run(panel.api_market_requests(CHAT_ID, world["user"]))


def test_очередь_показывает_заявку_с_продавцом(panel_client):
    item = listing(panel_client)["requests"][0]
    assert item["name"] == "Огурец"
    assert item["full_name"] == "Коля"


def test_одобрение_меняет_статус_и_уведомляет(panel_client):
    assert decide(panel_client)["ok"] is True
    assert panel_client["state"]["good"]["status"] == "approved"
    assert "market_approve" in panel_client["state"]["logs"]
    assert any(m["chat_id"] == CHAT_ID and "одобрена" in m["text"]
               for m in panel_client["bot"].sent)
    assert any(m["chat_id"] == SELLER_ID and "одобрен" in m["text"]
               for m in panel_client["bot"].sent)


def test_отклонение_убирает_заявку_из_очереди(panel_client):
    assert decide(panel_client, approve=False)["ok"] is True
    assert panel_client["state"]["good"]["status"] == "rejected"
    assert listing(panel_client)["requests"] == []
    assert "market_reject" in panel_client["state"]["logs"]


def test_повторное_решение_отвергается(panel_client):
    assert decide(panel_client)["ok"] is True
    with pytest.raises(HTTPException) as exc:
        decide(panel_client)
    assert exc.value.status_code == 409
