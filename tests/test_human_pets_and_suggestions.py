"""Запросы «человек-питомец» и канал предложений участников."""

import inspect
import importlib

import bot
import db
panel = importlib.import_module("webpanel.app")


def test_таблица_людей_питомцев_создаётся_миграцией():
    source = inspect.getsource(db.ensure_human_pets_table)
    assert "CREATE TABLE IF NOT EXISTS human_pets" in source
    assert "pending" in source and "active" in source


def test_принять_и_отклонить_может_только_будущий_питомец():
    accepted = inspect.getsource(bot.human_pet_accept)
    declined = inspect.getsource(bot.human_pet_decline)
    assert "callback.from_user.id != pet_id" in accepted
    assert "callback.from_user.id != pet_id" in declined


def test_человек_питомец_вызывается_через_челопет():
    source = inspect.getsource(bot.cmd_human_pet_request)
    assert "челопет" in source
    assert bot.resolve_command_key("челопет @username") == "human_pet"


def test_сво_имеет_все_шуточные_команды_и_отдельные_ключи_чата():
    source = inspect.getsource(bot.cmd_svo)
    assert all(word in source for word in ("отправить", "вернуть", "выкл", "вкл", "статус"))
    assert bot.resolve_command_key("СВО статус") == "svo"
    assert bot._svo_enabled_key(-100) != bot._svo_sent_key(-100)


def test_анкета_показывает_обе_стороны_кликабельными():
    source = inspect.getsource(bot.build_profile_card)
    assert 'href="tg://user?id={other_id}"' in source
    assert 'Питомец: {other_link}' in source
    assert 'Хозяин: {other_link}' in source


def test_предложения_из_бота_и_сайта_идут_в_notify_chat():
    bot_source = inspect.getsource(bot.cmd_improvement_suggestion)
    web_source = inspect.getsource(panel.api_member_suggestion)
    assert 'settings.get("notify_chat_id")' in bot_source
    assert 'settings.get("notify_topic_id")' in bot_source
    assert 'settings.get("notify_chat_id")' in web_source
    assert 'settings.get("notify_topic_id")' in web_source


def test_сайт_ограничивает_размер_предложения_и_проверяет_csrf():
    source = inspect.getsource(panel.api_member_suggestion)
    assert "auth.verify_csrf(request)" in source
    assert "len(suggestion) > 2000" in source
