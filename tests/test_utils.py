from src.core.utils import normalize_url, tokenize


def test_normalize_url_basics() -> None:
    assert normalize_url("HTTPS://Example.com/path/#frag") == "https://example.com/path"
    assert normalize_url("/a", base_url="https://example.com/base") == "https://example.com/a"
    assert normalize_url("mailto:test@example.com") is None


def test_tokenize_lowercases_and_filters_short_tokens() -> None:
    tokens = tokenize("AI, web-crawler v1! a I test TEST")
    assert "test" in tokens
    assert "ai" in tokens
    assert "a" not in tokens

