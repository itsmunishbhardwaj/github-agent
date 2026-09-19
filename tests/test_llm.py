from researcher import llm


def test_get_client_is_built_lazily_and_cached(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    llm.get_client.cache_clear()
    assert llm.get_client() is llm.get_client()


def test_ask_sends_system_and_json_payload_and_returns_the_parsed_output(monkeypatch):
    from pydantic import BaseModel

    from .fakes import FakeClaude

    class Out(BaseModel):
        ok: bool

    fake = FakeClaude(Out(ok=True))
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    assert llm.ask("be brief", {"goal": "x"}, Out) == Out(ok=True)
    call = fake.calls[0]
    assert call["system"] == "be brief"
    assert call["messages"] == [{"role": "user", "content": '{"goal": "x"}'}]
    assert call["output_format"] is Out and call["model"] == llm.MODEL
