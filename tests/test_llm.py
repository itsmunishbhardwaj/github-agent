from researcher import llm


def test_get_client_is_built_lazily_and_cached(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    llm.get_client.cache_clear()
    assert llm.get_client() is llm.get_client()
