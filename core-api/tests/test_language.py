import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import dispatch, i18n, translate
from app.agent import gemini
from app.agent import service as agent
from app.agent.safety import check_emergency, emergency_reply
from app.db import get_engine
from app.main import app
from app.security import create_access_token
from tests.test_dispatch import (  # noqa: F401  (world is a fixture)
    new_handyman,
    new_ticket,
    new_user,
    post_sms,
    ticket_status,
    world,
)

client = TestClient(app)
db = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set")


def auth(uid, role):
    return {"Authorization": f"Bearer {create_access_token(str(uid), role)}"}


def set_lang(uid, lang):
    with get_engine().begin() as c:
        c.execute(text("UPDATE users SET language = :l WHERE id = :u"), {"l": lang, "u": uid})


def customer_of(tid):
    with get_engine().connect() as c:
        return c.execute(
            text(
                "SELECT customer_id, u.phone_e164 FROM tickets t JOIN users u "
                "ON u.id = t.customer_id WHERE t.id = :t"
            ),
            {"t": tid},
        ).one()


@pytest.fixture
def fake_translate(monkeypatch):
    calls = []

    def fake(text_in, target):
        calls.append((text_in, target))
        return f"[{target}] {text_in}"

    monkeypatch.setattr(translate, "translate", fake)
    return calls


# ---------- pure helpers ----------
def test_detect_language():
    assert translate.detect("The key is under the mat") == "en"
    assert translate.detect("钥匙在垫子下面") == "zh"
    assert translate.detect("我在 92101 附近 ok") == "zh"
    assert translate.detect("#1042 92101") == "en"
    assert translate.detect("") == "en"


def test_text_tables_have_the_same_keys_and_fall_back_to_english():
    assert set(i18n.STR["en"]) == set(i18n.STR["zh"])
    assert i18n.t("fr", "closed", n=5) == i18n.t("en", "closed", n=5)
    assert i18n.t(None, "closed", n=5).startswith("Job #5")
    assert "工单 #5" in i18n.t("zh", "closed", n=5)
    assert i18n.category("zh", "CARPENTRY") == "木工/地板"
    assert i18n.duration("zh", 900) == "15 分钟" and i18n.duration("en", 7200) == "2 h"


def test_chinese_emergencies_are_caught_and_answered_in_chinese():
    for message, category in [
        ("我闻到煤气味", "gas"),
        ("厨房着火了", "fire"),
        ("插座冒火花", "fire"),
        ("天花板塌了", "structural"),
        ("一氧化碳报警器响了", "carbon_monoxide"),
        ("配电箱进水了", "flood_electric"),
    ]:
        assert check_emergency(message) == category, message
    assert check_emergency("厨房水槽在滴水") is None
    reply = emergency_reply("gas", "zh")
    assert "911" in reply and "煤气" in reply
    assert emergency_reply("gas", "en").startswith("This could be a gas leak")


def test_assistant_reply_language_follows_the_user(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    seen = {}

    def fake(contents, tools=None, note="", system=None):
        seen["note"] = note
        return gemini.GeminiResult("ok")

    monkeypatch.setattr(gemini, "generate", fake)

    class Row:
        sender, body, media_ids = "USER", "my sink drips", []

    agent.respond([Row()], "my sink drips", lang="zh")
    assert "Simplified Chinese" in seen["note"]
    agent.respond([Row()], "my sink drips", lang="en")
    assert "Simplified Chinese" not in seen["note"]
    emergency = agent.respond([Row()], "厨房着火了", lang="zh")
    assert emergency.emergency and "911" in emergency.text and "起火" in emergency.text
    assert agent.respond([Row()], "I smell gas", lang="en").text.startswith("This could be")


# ---------- account language ----------
@db
def test_language_is_saved_per_user_and_validated(world):  # noqa: F811
    uid = new_user(world, "CUSTOMER")
    h = auth(uid, "CUSTOMER")
    assert client.get("/me", headers=h).json()["language"] == "en"
    assert client.put("/me/language", json={"language": "zh"}, headers=h).json() == {
        "language": "zh"
    }
    assert client.get("/me", headers=h).json()["language"] == "zh"
    assert client.put("/me/language", json={"language": "fr"}, headers=h).status_code == 422
    assert client.put("/me/language", json={"language": "zh"}).status_code == 401


# ---------- texts in the reader's language ----------
@db
def test_offer_sms_reminder_and_reply_words_are_chinese_for_a_chinese_handyman(world):  # noqa: F811
    hid, phone = new_handyman(world, "Best", 4.9)
    set_lang(hid, "zh")
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid)
    body = world.messages[0][1]
    assert "工单" in body and "水管" in body and f"ACCEPT {num}" in body and "15 分钟" in body
    answer, _ = dispatch.handle_handyman_reply(hid, f"接单 {num}")
    assert "已分配给你" in answer
    assert ticket_status(tid) == "ASSIGNED"


@db
def test_decline_and_unavailable_replies_are_chinese(world):  # noqa: F811
    hid, _ = new_handyman(world, "Best", 4.9)
    set_lang(hid, "zh")
    tid, num = new_ticket(world)
    dispatch.start_dispatch(tid)
    assert "已转给" in dispatch.handle_handyman_reply(hid, f"拒绝 {num}")[0]
    assert "已不可接" in dispatch.handle_handyman_reply(hid, f"ACCEPT {num}")[0]


@db
def test_customer_notices_use_the_customers_language(world):  # noqa: F811
    hid, _ = new_handyman(world, "Mike R.", 4.9)
    tid, num = new_ticket(world)
    cust, _ = customer_of(tid)
    set_lang(cust, "zh")
    dispatch.start_dispatch(tid, hid)
    dispatch.handle_handyman_reply(hid, f"ACCEPT {num}")
    with get_engine().connect() as c:
        body = c.execute(
            text(
                "SELECT m.body FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                "WHERE c.ticket_id = :t AND m.sender = 'BOT'"
            ),
            {"t": tid},
        ).scalar()
    assert body.startswith("好消息：Mike R. 已接受维修请求")
    unmatched, _ = new_ticket(world)
    with get_engine().begin() as c:  # a ZIP nobody serves
        c.execute(text("UPDATE tickets SET location_zip = '99999' WHERE id = :t"), {"t": unmatched})
        cc = c.execute(
            text("SELECT customer_id FROM tickets WHERE id = :t"), {"t": unmatched}
        ).scalar()
        c.execute(text("UPDATE users SET language = 'zh' WHERE id = :u"), {"u": cc})
    dispatch.start_dispatch(unmatched)
    with get_engine().connect() as c:
        notice = c.execute(
            text(
                "SELECT m.body FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                "WHERE c.ticket_id = :t AND m.sender = 'BOT'"
            ),
            {"t": unmatched},
        ).scalar()
    assert "没有找到可接单的师傅" in notice


@db
def test_sms_keywords_switch_language(world, monkeypatch):  # noqa: F811
    uid = new_user(world, "CUSTOMER", "+1619" + "5550" + "321")
    r = post_sms(monkeypatch, "+16195550321", "中文")
    assert "中文回复" in r.text
    with get_engine().connect() as c:
        assert (
            c.execute(text("SELECT language FROM users WHERE id = :u"), {"u": uid}).scalar() == "zh"
        )
    r = post_sms(monkeypatch, "+16195550321", "NEW")
    assert "新的请求" in r.text
    r = post_sms(monkeypatch, "+16195550321", "English")
    assert "English" in r.text


# ---------- automatic translation of messages ----------
def assigned(world, channel="WEB"):  # noqa: F811
    hid, hphone = new_handyman(world, "Mike R.", 4.9)
    tid, num = new_ticket(world, channel=channel)
    cust, cphone = customer_of(tid)
    dispatch.start_dispatch(tid, hid)
    dispatch.handle_handyman_reply(hid, f"ACCEPT {num}")
    world.messages.clear()
    return hid, hphone, cust, cphone, tid, num


def chat(tid, headers):
    return client.get(f"/threads/{tid}/messages", headers=headers).json()["messages"]


@db
def test_messages_are_translated_for_the_reader_and_the_original_is_kept(world, fake_translate):  # noqa: F811
    hid, hphone, cust, _, tid, num = assigned(world)
    set_lang(cust, "zh")
    set_lang(hid, "en")
    c, h = auth(cust, "CUSTOMER"), auth(hid, "HANDYMAN")
    r = client.post(f"/threads/{tid}/messages", json={"body": "钥匙在垫子下面"}, headers=c)
    assert r.status_code == 201
    assert fake_translate == [("钥匙在垫子下面", "en")]
    theirs = chat(tid, h)[0]
    assert theirs["body"] == "[en] 钥匙在垫子下面"
    assert theirs["translated"] is True and theirs["original"] == "钥匙在垫子下面"
    mine = chat(tid, c)[0]
    assert mine["body"] == "钥匙在垫子下面" and mine["mine"] is True and mine["translated"] is False
    # And the other way round.
    client.post(f"/threads/{tid}/messages", json={"body": "Running 10 minutes late"}, headers=h)
    assert fake_translate[-1] == ("Running 10 minutes late", "zh")
    back = chat(tid, c)[1]
    assert back["body"] == "[zh] Running 10 minutes late"
    assert back["original"] == "Running 10 minutes late"
    # Both versions are stored.
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT body, lang, translations FROM messages WHERE relay_ticket_id = :t "
                "ORDER BY created_at LIMIT 1"
            ),
            {"t": tid},
        ).one()
    assert (
        row.body == "钥匙在垫子下面"
        and row.lang == "zh"
        and row.translations == {"en": "[en] 钥匙在垫子下面"}
    )


@db
def test_same_language_is_not_translated(world, fake_translate):  # noqa: F811
    hid, _, cust, _, tid, _ = assigned(world)
    set_lang(cust, "en")
    set_lang(hid, "en")
    client.post(
        f"/threads/{tid}/messages", json={"body": "Hello there"}, headers=auth(cust, "CUSTOMER")
    )
    assert fake_translate == []
    assert chat(tid, auth(hid, "HANDYMAN"))[0]["translated"] is False


@db
def test_typing_in_the_readers_language_is_not_translated(world, fake_translate):  # noqa: F811
    hid, _, cust, _, tid, _ = assigned(world)
    set_lang(cust, "en")  # an English-speaking customer...
    set_lang(hid, "zh")  # ...and a handyman who reads Chinese but wrote Chinese anyway
    client.post(
        f"/threads/{tid}/messages", json={"body": "我快到了"}, headers=auth(hid, "HANDYMAN")
    )
    assert fake_translate == [("我快到了", "en")]
    client.post(
        f"/threads/{tid}/messages", json={"body": "好的，谢谢"}, headers=auth(hid, "HANDYMAN")
    )
    assert chat(tid, auth(cust, "CUSTOMER"))[-1]["body"] == "[en] 好的，谢谢"


@db
def test_translation_failure_falls_back_to_the_original(world, monkeypatch):  # noqa: F811
    hid, _, cust, _, tid, _ = assigned(world)
    set_lang(cust, "zh")
    set_lang(hid, "en")
    monkeypatch.setattr(translate, "translate", lambda text_in, target: None)
    r = client.post(
        f"/threads/{tid}/messages", json={"body": "你好"}, headers=auth(cust, "CUSTOMER")
    )
    assert r.status_code == 201
    shown = chat(tid, auth(hid, "HANDYMAN"))[0]
    assert shown["body"] == "你好" and shown["translated"] is False


@db
def test_sms_fallback_carries_the_translation_in_the_readers_wrapper(world, fake_translate):  # noqa: F811
    hid, hphone, cust, cphone, tid, num = assigned(world, channel="SMS")
    set_lang(cust, "zh")
    set_lang(hid, "en")
    client.post(
        f"/threads/{tid}/messages", json={"body": "我在门口"}, headers=auth(cust, "CUSTOMER")
    )
    to, body = world.messages[-1]
    assert to == hphone and body.startswith(f"Job #{num} customer: [en] 我在门口")
    world.messages.clear()
    with get_engine().begin() as c:  # the customer has left the app, so a text is due
        c.execute(text("UPDATE users SET last_seen_at = NULL WHERE id = :u"), {"u": cust})
    _, out = dispatch.handle_handyman_reply(hid, f"#{num} Opening the door now")
    dispatch.deliver(out)
    to, body = world.messages[-1]
    assert to == cphone and "[zh] Opening the door now" in body and "请求 #" in body


@db
def test_thread_list_preview_is_translated_too(world, fake_translate):  # noqa: F811
    hid, _, cust, _, tid, _ = assigned(world)
    set_lang(cust, "zh")
    set_lang(hid, "en")
    client.post(
        f"/threads/{tid}/messages",
        json={"body": "Come at noon please"},
        headers=auth(hid, "HANDYMAN"),
    )
    last = client.get("/threads", headers=auth(cust, "CUSTOMER")).json()["threads"][0]
    assert last["last_body"] == "[zh] Come at noon please"
    own = client.get("/threads", headers=auth(hid, "HANDYMAN")).json()["threads"][0]
    assert own["last_body"] == "Come at noon please"
