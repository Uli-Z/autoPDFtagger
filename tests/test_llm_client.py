import os

import pytest

from autoPDFtagger import llm_client


def test_infer_provider_mappings():
    assert llm_client.infer_provider("openai/gpt-4o")["provider"] == "openai"
    assert llm_client.infer_provider("gemini/gemini-1.5-pro")["provider"] == "gemini"
    assert llm_client.infer_provider("ollama/llava")["provider"] == "ollama"
    assert llm_client.infer_provider("custom-model")["provider"] == "unknown"


def test_run_chat_computes_cost(monkeypatch):
    # Ensure env for OpenAI
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [{"message": {"content": "{\"ok\": true}"}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 1000, "total_tokens": 2000},
        }

    monkeypatch.setattr(llm_client, "completion", fake_completion)

    text, usage = llm_client.run_chat(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        json_mode=True,
    )
    assert text.strip().startswith("{")
    # 1000 * 0.0005/1000 + 1000 * 0.0015/1000 = 0.002
    assert pytest.approx(usage.get("cost", 0.0), rel=1e-3, abs=1e-6) == 0.002
    assert captured["model"] == "openai/gpt-4o-mini"


def test_run_chat_missing_env_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm_client, "completion", lambda **kwargs: kwargs)
    with pytest.raises(RuntimeError):
        llm_client.run_chat("openai/gpt-4o-mini", messages=[{"role": "user", "content": "x"}])


def test_run_vision_builds_image_parts(monkeypatch):
    calls = {}

    def fake_completion(**kwargs):
        calls.update(kwargs)
        return {
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    monkeypatch.setattr(llm_client, "completion", fake_completion)

    text, usage = llm_client.run_vision(
        model="ollama/llava",
        prompt="describe",
        images_b64=["aGVsbG8=", "d29ybGQ="]
    )
    assert text == "{}"
    assert usage.get("cost", 0.0) == 0.0  # unknown model → zero cost
    msgs = calls["messages"]
    assert msgs[0]["role"] == "user"
    parts = msgs[0]["content"]
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url" and parts[2]["type"] == "image_url"

