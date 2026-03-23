import pytest

from app.core.config import Settings


def test_cors_allowed_origins_supports_comma_separated_values():
    settings = Settings(
        CORS_ALLOW_ORIGINS="http://localhost:3000, https://servitut.example.com",
    )

    assert settings.cors_allowed_origins == [
        "http://localhost:3000",
        "https://servitut.example.com",
    ]


def test_cors_allowed_origins_supports_json_array():
    settings = Settings(
        CORS_ALLOW_ORIGINS='["http://localhost:3000", "https://servitut.example.com"]',
    )

    assert settings.cors_allowed_origins == [
        "http://localhost:3000",
        "https://servitut.example.com",
    ]


def test_cors_allowed_origins_rejects_invalid_json_shapes():
    settings = Settings(CORS_ALLOW_ORIGINS='{"origin": "http://localhost:3000"}')

    with pytest.raises(ValueError, match="CORS_ALLOW_ORIGINS must be a JSON string array"):
        _ = settings.cors_allowed_origins
