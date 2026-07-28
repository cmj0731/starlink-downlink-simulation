import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from starlink_isl.celestrak import (
    CelesTrakError,
    cache_is_fresh,
    fetch_starlink_omm,
)


SAMPLE_RECORD = {
    "OBJECT_NAME": "STARLINK-TEST",
    "NORAD_CAT_ID": "99999",
    "EPOCH": "2026-01-01T00:00:00.000000",
}


class FakeResponse:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.response


def test_fresh_cache_avoids_network(tmp_path: Path):
    cache = tmp_path / "starlink.json"
    cache.write_text(json.dumps([SAMPLE_RECORD]), encoding="utf-8")
    session = FakeSession(FakeResponse(error=AssertionError("network used")))

    records = fetch_starlink_omm(cache, session=session)

    assert records == [SAMPLE_RECORD]
    assert session.calls == 0


def test_download_writes_valid_cache(tmp_path: Path):
    cache = tmp_path / "starlink.json"
    session = FakeSession(FakeResponse([SAMPLE_RECORD]))

    records = fetch_starlink_omm(cache, session=session)

    assert records == [SAMPLE_RECORD]
    assert json.loads(cache.read_text(encoding="utf-8")) == [SAMPLE_RECORD]
    assert session.calls == 1


def test_http_failure_is_not_retried(tmp_path: Path):
    session = FakeSession(
        FakeResponse(error=requests.HTTPError("403 rate limited"))
    )

    with pytest.raises(CelesTrakError, match="자동 재시도하지 않습니다"):
        fetch_starlink_omm(tmp_path / "starlink.json", session=session)

    assert session.calls == 1


def test_cache_age_boundary(tmp_path: Path):
    cache = tmp_path / "starlink.json"
    cache.write_text("[]", encoding="utf-8")
    modified = datetime.fromtimestamp(cache.stat().st_mtime, timezone.utc)

    assert cache_is_fresh(cache, now=modified + timedelta(minutes=119))
    assert not cache_is_fresh(cache, now=modified + timedelta(hours=2))

