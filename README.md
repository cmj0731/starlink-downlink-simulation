# Starlink ISL

CelesTrak의 Starlink 궤도 데이터를 이용해 위성 위치와 위성 간 링크
(Inter-Satellite Link, ISL)를 분석하는 프로젝트입니다.

## 개발 환경

Anaconda Prompt에서 다음 명령을 실행합니다.

```powershell
conda env create -f environment.yml
conda activate starlink-isl
```

환경 정의를 변경한 경우:

```powershell
conda env update -f environment.yml --prune
```

## CelesTrak 데이터 받기

```powershell
starlink-fetch
```

데이터는 `data/raw/starlink_omm.json`에 저장됩니다. 기본적으로 2시간 동안
캐시를 재사용하며, `--force`는 CelesTrak의 갱신 주기를 확인한 경우에만
사용해야 합니다.

```powershell
starlink-fetch --force
```

프로그램에서 사용하려면:

```python
from pathlib import Path

from starlink_isl.celestrak import fetch_starlink_omm

records = fetch_starlink_omm(Path("data/raw/starlink_omm.json"))
print(len(records))
```

## 데이터 정책

- 공식 엔드포인트 `https://celestrak.org`만 사용합니다.
- OMM JSON 형식을 사용해 기존 TLE의 5자리 카탈로그 번호 한계를 피합니다.
- 같은 Starlink 데이터는 최소 2시간 동안 다시 요청하지 않습니다.
- HTTP 오류가 발생하면 반복 요청하지 않고 즉시 중단합니다.
- 원본 궤도 데이터와 생성 결과는 Git에 커밋하지 않습니다.

## 모델 문서

- [이상적 STARLINK-5285 downlink 모델 정의](docs/model.md)

## 테스트

```powershell
pytest
```

## 예정 작업

1. OMM 데이터를 SGP4 위성 상태로 변환
2. 특정 시각의 ECI/ECEF 위치 계산
3. 지구 차폐를 고려한 위성 간 가시선 판정
4. 거리·지연·링크 수 제한을 반영한 ISL 그래프 구성
5. 경로 탐색 및 네트워크 성능 분석

## 출처

- [CelesTrak](https://celestrak.org/)
- [CelesTrak GP 데이터 형식과 질의 방법](https://celestrak.org/NORAD/documentation/gp-data-formats.php)
