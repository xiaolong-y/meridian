from unittest.mock import patch
from src.connectors.extractor import extract_article


def test_extract_article_returns_none_for_empty_url():
    assert extract_article(None) is None
    assert extract_article("") is None


def test_extract_article_handles_request_error():
    with patch("src.connectors.extractor.requests.get") as mock_get:
        mock_get.side_effect = Exception("Connection error")
        result = extract_article("https://example.com/post")
        assert result is None
