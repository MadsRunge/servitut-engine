import json
from typing import Any
from urllib import error, request

import anthropic

from app.core.config import settings

_anthropic_client: anthropic.Anthropic | None = None


def _resolve_provider(provider: str | None = None) -> str:
    if provider and provider.strip():
        return provider.strip().lower()
    return settings.LLM_PROVIDER.strip().lower()


def _require_value(name: str, value: str) -> str:
    if not value.strip():
        raise RuntimeError(f"{name} er ikke sat i .env")
    return value.strip()


def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(
            api_key=_require_value("ANTHROPIC_API_KEY", settings.ANTHROPIC_API_KEY)
        )
    return _anthropic_client


def _extract_anthropic_text(message: Any) -> str:
    parts: list[str] = []
    for block in getattr(message, "content", []):
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _resolve_model(model: str | None, default_model: str | None = None) -> str:
    if model and model.strip():
        return model.strip()
    if default_model and default_model.strip():
        return default_model.strip()
    return settings.MODEL


def _generate_with_anthropic(
    prompt: str,
    max_tokens: int,
    model: str | None = None,
    default_model: str | None = None,
) -> str:
    message = _get_anthropic_client().messages.create(
        model=_resolve_model(model, default_model=default_model),
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_anthropic_text(message)


def _normalize_openai_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
        return "\n".join(part for part in text_parts if part).strip()
    return ""


def _generate_with_deepseek(
    prompt: str,
    max_tokens: int,
    model: str | None = None,
    default_model: str | None = None,
) -> str:
    api_key = _require_value("DEEPSEEK_API_KEY", settings.DEEPSEEK_API_KEY)
    url = settings.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": _resolve_model(model, default_model=default_model),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    http_request = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=settings.LLM_TIMEOUT_SECONDS) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API error ({exc.code}): {error_body[:300]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"DeepSeek connection error: {exc.reason}") from exc

    choices = response_data.get("choices", [])
    if not choices:
        raise RuntimeError("DeepSeek returnerede ingen choices")

    content = choices[0].get("message", {}).get("content")
    text = _normalize_openai_content(content)
    if not text:
        raise RuntimeError("DeepSeek returnerede tom tekst")
    return text


def generate_text(
    prompt: str,
    max_tokens: int,
    model: str | None = None,
    provider: str | None = None,
    default_model: str | None = None,
) -> str:
    provider_name = _resolve_provider(provider)
    if provider_name == "anthropic":
        return _generate_with_anthropic(
            prompt,
            max_tokens,
            model=model,
            default_model=default_model,
        )
    if provider_name == "deepseek":
        return _generate_with_deepseek(
            prompt,
            max_tokens,
            model=model,
            default_model=default_model,
        )
    raise RuntimeError(f"Ukendt LLM_PROVIDER: {provider or settings.LLM_PROVIDER}")
