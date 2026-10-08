from types import SimpleNamespace

import httpx
import pytest

from app.agent import gemini, service
from app.agent.context import build_contents


def row(sender, body):
    return SimpleNamespace(sender=sender, body=body)


def test_context_maps_roles_merges_and_starts_with_user():
    rows = [row("BOT", "hi"), row("USER", "a"), row("USER", "b"), row("BOT", "c"), row("USER", "d")]
    contents = build_contents(rows)
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert contents[0]["parts"][0]["text"] == "a\nb"


def test_context_keeps_only_recent_turns():
    rows = [row("USER" if i % 2 == 0 else "BOT", f"m{i}") for i in range(50)]
    contents = build_contents(rows, max_turns=4)
    assert [c["parts"][0]["text"] for c in contents] == ["m46", "m47", "m48", "m49"]


def test_emergency_never_calls_gemini_even_with_a_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(
        gemini, "generate", lambda c, **kw: pytest.fail("Gemini must not be called")
    )
    reply = service.respond([row("USER", "I smell gas")], "I smell gas")
    assert reply.emergency and reply.source == "safety"
    assert "911" in reply.text


def test_without_key_falls_back_to_echo():
    reply = service.respond([row("USER", "hello")], "hello")
    assert (reply.text, reply.source, reply.emergency) == ("Echo: hello", "echo", False)


def test_with_key_uses_gemini_with_history(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    seen = {}
    monkeypatch.setattr(
        gemini,
        "generate",
        lambda c, **kw: seen.setdefault("c", c) and gemini.GeminiResult("Where is it?"),
    )
    reply = service.respond([row("USER", "my sink is leaking")], "my sink is leaking")
    assert reply.text == "Where is it?" and reply.source == "gemini"
    assert seen["c"][0]["parts"][0]["text"] == "my sink is leaking"


@pytest.mark.parametrize("error", [httpx.ConnectError("boom"), gemini.GeminiError("SAFETY")])
def test_gemini_failure_returns_fallback_with_911_reminder(monkeypatch, error):
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    def boom(contents, **kw):
        raise error

    monkeypatch.setattr(gemini, "generate", boom)
    reply = service.respond([row("USER", "my sink is leaking")], "my sink is leaking")
    assert reply.source == "fallback" and "911" in reply.text


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code, self.text = payload, status, str(payload)

    def json(self):
        return self.payload


def test_gemini_client_builds_request_and_parses_reply(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json)
        return FakeResponse(
            {"candidates": [{"content": {"parts": [{"text": "Hello "}, {"text": "there"}]}}]}
        )

    monkeypatch.setattr(gemini.httpx, "post", fake_post)
    out = gemini.generate([{"role": "user", "parts": [{"text": "hi"}]}])
    assert out.text == "Hello there" and out.function_call is None
    assert captured["url"].endswith("/models/gemini-test:generateContent")
    assert captured["headers"]["x-goog-api-key"] == "secret-key"
    assert "secret-key" not in captured["url"]
    assert "systemInstruction" in captured["json"]
    assert "tools" not in captured["json"]
    assert captured["json"]["contents"][0]["role"] == "user"


def test_gemini_client_raises_on_blocked_or_empty_reply(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(
        gemini.httpx,
        "post",
        lambda *a, **k: FakeResponse({"promptFeedback": {"blockReason": "SAFETY"}}),
    )
    with pytest.raises(gemini.GeminiError, match="SAFETY"):
        gemini.generate([{"role": "user", "parts": [{"text": "x"}]}])


def test_gemini_http_error_includes_googles_message(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-key")
    body = {"error": {"message": "models/nope is not found"}}
    monkeypatch.setattr(gemini.httpx, "post", lambda *a, **k: FakeResponse(body, status=404))
    with pytest.raises(gemini.GeminiError, match="HTTP 404: models/nope is not found") as info:
        gemini.generate([{"role": "user", "parts": [{"text": "x"}]}])
    assert "super-secret-key" not in str(info.value)


def test_images_attach_to_last_user_turn_only():
    rows = [
        SimpleNamespace(sender="USER", body="old", media_ids=["x"]),
        SimpleNamespace(sender="BOT", body="ok", media_ids=[]),
        SimpleNamespace(sender="USER", body="", media_ids=["y"]),
    ]
    contents = build_contents(rows, images=[("image/jpeg", b"\xff\xd8abc")])
    assert contents[0]["parts"] == [{"text": "old [photo attached]"}]
    last = contents[-1]["parts"]
    assert last[0] == {"text": "[photo attached]"}
    assert last[1]["inline_data"]["mime_type"] == "image/jpeg"


def test_echo_mentions_photos():
    reply = service.respond([row("USER", "look")], "look", images=[("image/jpeg", b"1")] * 2)
    assert reply.text == "Echo: look (received 2 photos)"


def test_gemini_client_sends_tools_and_parses_function_call(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    captured = {}
    reply = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "thinking...", "thought": True},
                        {"text": "Creating it."},
                        {"functionCall": {"name": "create_repair_ticket", "args": {"a": 1}}},
                    ]
                }
            }
        ]
    }

    def fake_post(url, headers, json, timeout):
        captured.update(json=json)
        return FakeResponse(reply)

    monkeypatch.setattr(gemini.httpx, "post", fake_post)
    out = gemini.generate([], tools=[{"name": "create_repair_ticket"}], note="ticket #1 exists")
    assert out.text == "Creating it."
    assert out.function_call == gemini.FunctionCall("create_repair_ticket", {"a": 1})
    assert captured["json"]["tools"] == [
        {"functionDeclarations": [{"name": "create_repair_ticket"}]}
    ]
    assert "ticket #1 exists" in captured["json"]["systemInstruction"]["parts"][0]["text"]


def test_service_returns_ticket_request_from_function_call(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    call = gemini.FunctionCall("create_repair_ticket", {"category": "HVAC"})
    monkeypatch.setattr(gemini, "generate", lambda c, **kw: gemini.GeminiResult("", call))
    reply = service.respond([row("USER", "yes")], "yes", want_ticket=True)
    assert reply.ticket_request == {"category": "HVAC"} and reply.text == ""


def test_function_call_is_ignored_when_the_tool_was_not_offered(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    call = gemini.FunctionCall("create_repair_ticket", {"category": "HVAC"})
    monkeypatch.setattr(gemini, "generate", lambda c, **kw: gemini.GeminiResult("", call))
    assert service.respond([row("USER", "yes")], "yes").ticket_request is None


def test_service_ignores_unknown_function_calls(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    call = gemini.FunctionCall("delete_everything", {})
    monkeypatch.setattr(gemini, "generate", lambda c, **kw: gemini.GeminiResult("", call))
    reply = service.respond([row("USER", "yes")], "yes")
    assert reply.ticket_request is None and reply.source == "fallback"
