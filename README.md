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

## 이상적 운동 모델

```python
import numpy as np

from starlink_isl import ground_station_state, satellite_state

times_s = np.arange(-1_000.0, 1_001.0)
ground_station = ground_station_state(times_s)
satellite = satellite_state(times_s)

print(ground_station.position_km.shape)
print(satellite.position_km.shape)
```

위치와 속도는 지구중심 관성좌표계(ECI)에서 각각 km와 km/s 단위로
반환됩니다. 기본 모델은 `t=0`에 STARLINK-5285가 성균관대 지상국의
천정을 북향으로 통과하도록 구성되어 있습니다.

## Downlink 기하

```python
from starlink_isl import downlink_geometry, visibility_window

geometry = downlink_geometry(times_s, minimum_elevation_deg=10.0)
window = visibility_window(minimum_elevation_deg=10.0)

print(window.start_s, window.end_s, window.duration_s)
print(geometry.slant_range_km)
print(geometry.elevation_deg)
```

대권거리는 지상궤적 분석용으로만 계산하며, 실제 전파거리에는 위성과
지상국 사이의 3차원 경사거리를 사용합니다. 방위각은 북쪽 기준 시계방향이며,
정확한 천정에서는 방향이 정의되지 않으므로 `NaN`을 반환합니다.

## 전파 지연과 도플러

```python
from starlink_isl import downlink_dynamics

dynamics = downlink_dynamics(times_s, carrier_frequency_hz=10.0e9)

print(dynamics.propagation_delay_s)
print(dynamics.radial_velocity_km_s)
print(dynamics.doppler_shift_hz)
print(dynamics.doppler_phase_rad)
```

시선방향 속도는 거리가 증가할 때 양수입니다. 프로젝트의 도플러 부호 규칙은
`f_D = -(v_r/c) f_c`이므로 위성이 접근할 때 양의 편이, 이탈할 때 음의
편이가 발생합니다. 누적 위상은 기본적으로 천정 통과 시각 `t=0`을 기준으로
하며 시간 미분은 `2*pi*f_D`입니다.

## 자유공간 링크 버짓과 열잡음

```python
from starlink_isl import LinkBudgetConfig, link_budget

radio = LinkBudgetConfig(
    carrier_frequency_hz=10.0e9,
    bandwidth_hz=100.0e6,
    transmit_power_dbw=10.0,
    transmit_antenna_gain_dbi=30.0,
    receive_antenna_gain_dbi=40.0,
    system_noise_temperature_k=290.0,
    other_losses_db=2.0,
)
budget = link_budget(times_s, radio, minimum_elevation_deg=10.0)

print(budget.received_power_dbw)
print(budget.thermal_noise_power_dbw)
print(budget.snr_db)
```

위 무선 파라미터는 사용법을 보여주기 위한 예시이며 실제 Starlink 장비
사양을 의미하지 않습니다. 잡음전력은 `k*T*B`로 계산합니다. 실제 링크에는
안테나 잡음과 수신기 등가 잡음온도를 합친 시스템 잡음온도를 입력해야 합니다.
가시구간 밖의 수치도 계산되지만 물리적으로 사용할 수 없으므로 반환되는
`visible` 마스크를 적용해야 합니다.

## 시뮬레이션 실행과 그래프

```powershell
starlink-simulate `
  --carrier-ghz 10 `
  --bandwidth-mhz 100 `
  --minimum-elevation-deg 10 `
  --time-step-s 1
```

기본 출력 디렉터리 `outputs/ideal_downlink/`에 `results.csv`,
`summary.json`, 궤도·지상궤적·기하·도플러·링크 버짓 PNG가 생성됩니다.
기본 무선 파라미터는 시각화용 예시이며 실제 Starlink 사양이 아닙니다.
CSV 시간 배열에는 가시 시작·종료, 최근접점과 `t=0`이 정확히 포함되며
`event` 열에서 해당 행을 확인할 수 있습니다. 궤도 그림은 전체 한 궤도를
기준선으로 표시하되 CSV에는 기존 패스 분석 시간 범위만 저장합니다.

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
