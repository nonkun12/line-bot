import os
from unittest.mock import patch

from agents.normal import node


def test_normal_provider_defaults_to_groq(monkeypatch):
    monkeypatch.delenv("NORMAL_AGENT_PROVIDER", raising=False)
    assert node._normal_provider() == "groq"


def test_unknown_normal_provider_falls_back_to_groq(monkeypatch):
    monkeypatch.setenv("NORMAL_AGENT_PROVIDER", "unknown")
    assert node._normal_provider() == "groq"


def test_gemini_provider_uses_n8n(monkeypatch):
    monkeypatch.setenv("NORMAL_AGENT_PROVIDER", "gemini")
    with patch.object(node, "call_gemini_via_n8n", return_value="Gemini reply") as gemini:
        with patch.object(node, "handle_normal_message") as groq:
            result = node._generate_normal_reply("こんにちは", "U123", lambda *args: None)

    assert result == "Gemini reply"
    gemini.assert_called_once_with("こんにちは", "U123")
    groq.assert_not_called()


def test_gemini_failure_falls_back_to_groq(monkeypatch):
    monkeypatch.setenv("NORMAL_AGENT_PROVIDER", "gemini")
    with patch.object(
        node,
        "call_gemini_via_n8n",
        side_effect=node.GeminiN8nError("timeout"),
    ):
        with patch.object(node, "handle_normal_message", return_value="Groq reply") as groq:
            result = node._generate_normal_reply("こんにちは", "U123", lambda *args: None)

    assert result == "Groq reply"
    groq.assert_called_once()


def test_groq_provider_uses_existing_handler(monkeypatch):
    monkeypatch.setenv("NORMAL_AGENT_PROVIDER", "groq")
    with patch.object(node, "handle_normal_message", return_value="Groq reply") as groq:
        result = node._generate_normal_reply("こんにちは", "U123", lambda *args: None)

    assert result == "Groq reply"
    groq.assert_called_once()
