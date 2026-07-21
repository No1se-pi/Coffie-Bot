from datetime import UTC, datetime, timedelta

import pytest

from app.security.sessions import hash_session_token, issue_session_token


def test_session_token_is_opaque_hashed_and_short_lived() -> None:
    now = datetime(2026, 7, 21, 12, tzinfo=UTC)

    issued = issue_session_token(ttl=timedelta(minutes=15), pepper="test-pepper", now=now)

    assert issued.raw_token.startswith("cbs_")
    assert issued.raw_token not in issued.token_hash
    assert len(issued.token_hash) == 64
    assert issued.token_hash == hash_session_token(issued.raw_token, pepper="test-pepper")
    assert issued.expires_at == now + timedelta(minutes=15)


def test_session_tokens_are_unique() -> None:
    first = issue_session_token(ttl=timedelta(minutes=15))
    second = issue_session_token(ttl=timedelta(minutes=15))

    assert first.raw_token != second.raw_token
    assert first.token_hash != second.token_hash


def test_rejects_non_positive_session_ttl() -> None:
    with pytest.raises(ValueError, match="ttl must be positive"):
        issue_session_token(ttl=timedelta(0))
