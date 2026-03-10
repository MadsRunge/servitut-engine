import json
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.services import llm_service


@pytest.fixture(autouse=True)
def reset_provider_settings(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.setattr(settings, "DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setattr(settings, "MODEL", "test-model")
    monkeypatch.setattr(settings, "LLM_TIMEOUT_SECONDS", 5)
    llm_service._anthropic_client = None


def test_generate_text_uses_anthropic_provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")

    with patch("app.services.llm_service._generate_with_anthropic", return_value="hej") as mock_fn:
        assert llm_service.generate_text("prompt", max_tokens=123) == "hej"

    mock_fn.assert_called_once_with("prompt", 123, model=None, default_model=None)


def test_generate_text_uses_deepseek_provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "deepseek")

    with patch("app.services.llm_service._generate_with_deepseek", return_value="svar") as mock_fn:
        assert llm_service.generate_text("prompt", max_tokens=321) == "svar"

    mock_fn.assert_called_once_with("prompt", 321, model=None, default_model=None)


def test_generate_text_passes_model_override(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "deepseek")

    with patch("app.services.llm_service._generate_with_deepseek", return_value="svar") as mock_fn:
        assert llm_service.generate_text("prompt", max_tokens=321, model="deepseek-reasoner") == "svar"

    mock_fn.assert_called_once_with(
        "prompt",
        321,
        model="deepseek-reasoner",
        default_model=None,
    )


def test_generate_text_passes_provider_override():
    with patch("app.services.llm_service._generate_with_deepseek", return_value="svar") as mock_fn:
        assert llm_service.generate_text("prompt", max_tokens=321, provider="deepseek") == "svar"

    mock_fn.assert_called_once_with("prompt", 321, model=None, default_model=None)


def test_generate_text_passes_default_model_override():
    with patch("app.services.llm_service._generate_with_anthropic", return_value="hej") as mock_fn:
        assert (
            llm_service.generate_text(
                "prompt",
                max_tokens=123,
                provider="anthropic",
                default_model="claude-sonnet-4-6",
            )
            == "hej"
        )

    mock_fn.assert_called_once_with(
        "prompt",
        123,
        model=None,
        default_model="claude-sonnet-4-6",
    )


def test_generate_text_rejects_unknown_provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "unknown")

    with pytest.raises(RuntimeError, match="Ukendt LLM_PROVIDER"):
        llm_service.generate_text("prompt", max_tokens=1)


def test_generate_with_deepseek_parses_chat_completion_response():
    response_body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": "DeepSeek svar",
                    }
                }
            ]
        }
    ).encode("utf-8")
    mock_response = MagicMock()
    mock_response.__enter__.return_value.read.return_value = response_body
    mock_response.__exit__.return_value = None

    with patch("app.services.llm_service.request.urlopen", return_value=mock_response) as mock_urlopen:
        assert llm_service._generate_with_deepseek("hej", max_tokens=42) == "DeepSeek svar"

    request_obj = mock_urlopen.call_args.args[0]
    assert request_obj.full_url == "https://api.deepseek.com/chat/completions"
    assert request_obj.get_header("Authorization") == "Bearer sk-deepseek-test"


def test_generate_with_deepseek_uses_model_override():
    response_body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": "DeepSeek svar",
                    }
                }
            ]
        }
    ).encode("utf-8")
    mock_response = MagicMock()
    mock_response.__enter__.return_value.read.return_value = response_body
    mock_response.__exit__.return_value = None

    with patch("app.services.llm_service.request.urlopen", return_value=mock_response) as mock_urlopen:
        assert (
            llm_service._generate_with_deepseek("hej", max_tokens=42, model="deepseek-reasoner")
            == "DeepSeek svar"
        )

    request_obj = mock_urlopen.call_args.args[0]
    payload = json.loads(request_obj.data.decode("utf-8"))
    assert payload["model"] == "deepseek-reasoner"


def test_generate_with_deepseek_uses_default_model_override():
    response_body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": "DeepSeek svar",
                    }
                }
            ]
        }
    ).encode("utf-8")
    mock_response = MagicMock()
    mock_response.__enter__.return_value.read.return_value = response_body
    mock_response.__exit__.return_value = None

    with patch("app.services.llm_service.request.urlopen", return_value=mock_response) as mock_urlopen:
        assert (
            llm_service._generate_with_deepseek(
                "hej",
                max_tokens=42,
                default_model="deepseek-reasoner",
            )
            == "DeepSeek svar"
        )

    request_obj = mock_urlopen.call_args.args[0]
    payload = json.loads(request_obj.data.decode("utf-8"))
    assert payload["model"] == "deepseek-reasoner"


def test_generate_with_anthropic_extracts_text():
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Claude svar")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    with patch("app.services.llm_service._get_anthropic_client", return_value=mock_client):
        assert llm_service._generate_with_anthropic("hej", max_tokens=55) == "Claude svar"
