"""Download and cache Starlink OMM records from CelesTrak."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

CELESTRAK_STARLINK_URL = (
    "https://celestrak.org/NORAD/elements/gp.php"
    "?GROUP=STARLINK&FORMAT=JSON"
)
DEFAULT_CACHE_PATH = Path("data/raw/starlink_omm.json")
MIN_CACHE_AGE = timedelta(hours=2)
USER_AGENT = "starlink-isl-research/0.1"


class CelesTrakError(RuntimeError):
    """Raised when CelesTrak data cannot be downloaded or validated."""


def cache_is_fresh(
    path: Path,
    *,
    now: datetime | None = None,
    max_age: timedelta = MIN_CACHE_AGE,
) -> bool:
    """Return whether an existing cache file is younger than ``max_age``."""
    if not path.is_file():
        return False

    current = now or datetime.now(timezone.utc)
    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return current - modified < max_age


def load_omm(path: Path) -> list[dict[str, Any]]:
    """Load and minimally validate cached OMM JSON records."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CelesTrakError(f"캐시 파일을 읽을 수 없습니다: {path}") from exc

    if not isinstance(payload, list):
        raise CelesTrakError("CelesTrak 응답은 JSON 배열이어야 합니다.")
    if payload and not all(
        isinstance(item, dict)
        and "OBJECT_NAME" in item
        and "NORAD_CAT_ID" in item
        and "EPOCH" in item
        for item in payload
    ):
        raise CelesTrakError("OMM 응답에 필수 필드가 없습니다.")
    return payload


def fetch_starlink_omm(
    cache_path: Path = DEFAULT_CACHE_PATH,
    *,
    force: bool = False,
    timeout: float = 30.0,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Return Starlink OMM data, downloading only when the cache is stale.

    CelesTrak updates GP data at most once every two hours and asks clients not
    to retry HTTP errors. This function therefore makes exactly one request.
    """
    if not force and cache_is_fresh(cache_path):
        return load_omm(cache_path)

    client = session or requests.Session()
    try:
        response = client.get(
            CELESTRAK_STARLINK_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise CelesTrakError(
            "CelesTrak 요청에 실패했습니다. 자동 재시도하지 않습니다."
        ) from exc

    if not isinstance(payload, list) or not payload:
        raise CelesTrakError("CelesTrak이 비어 있거나 잘못된 응답을 반환했습니다.")
    if not all(
        isinstance(item, dict)
        and "OBJECT_NAME" in item
        and "NORAD_CAT_ID" in item
        and "EPOCH" in item
        for item in payload
    ):
        raise CelesTrakError("OMM 응답에 필수 필드가 없습니다.")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(cache_path)
    return payload


def main() -> None:
    """Run the CelesTrak downloader from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help=f"캐시 파일 경로 (기본값: {DEFAULT_CACHE_PATH})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="2시간 캐시를 무시합니다. CelesTrak 갱신 확인 시에만 사용하세요.",
    )
    args = parser.parse_args()

    try:
        records = fetch_starlink_omm(args.output, force=args.force)
    except CelesTrakError as exc:
        parser.exit(1, f"오류: {exc}\n")
    print(f"{len(records)}개 OMM 레코드 준비 완료: {args.output}")


if __name__ == "__main__":
    main()

