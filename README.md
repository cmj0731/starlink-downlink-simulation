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

## 팀 공통 연구 baseline

OFDM·채널·수신 필터가 서로 다른 수치를 사용하지 않도록 임시 공통 설정을
`configs/ofdm_baseline.yaml`에 둔다. 이 파일은 실제 Starlink 독점 파형
규격을 나타내지 않으며, 팀 통합과 비교 실험을 위한 명시적인 연구 가정이다.

```powershell
starlink-config configs/ofdm_baseline.yaml
```

검증 명령은 설정을 읽어 다음 관계와 모듈 간 제약을 확인한다.

\[
f_s=N_{\mathrm{FFT}}\Delta f,
\qquad
B_{\mathrm{occupied}}\approx K_{\mathrm{active}}\Delta f
\]

현재 임시 baseline은 다음과 같다.

| 항목 | 값 |
|---|---:|
| 링크 | Ku-band downlink 연구 시나리오 |
| 대표 반송파 | 11.7 GHz |
| FFT 크기 | 256 |
| 부반송파 간격 | 30 kHz |
| 활성 부반송파 수 | 200 |
| CP | 32 samples |
| 파형 샘플레이트 | 7.68 MHz |
| 파형 샘플주기 | 약 130.21 ns |
| 점유대역폭 근사 | 6 MHz |
| CP 포함 심벌시간 | 37.5 us |
| 원본 기하 상태 간격 | 1 s |
| 채널 갱신 간격 | 1 ms |
| 상태 재표본화 | cubic Hermite, 직접 SGP4로 검증 완료 |
| 채널 grid 시간 기준 | OFDM FFT 구간 중앙 |
| 부반송파 인덱스 | signed FFT index |

활성 부반송파의 정확한 배치, pilot 위치 및 파형 정규화는 팀 통합 전에
확정해야 하며 YAML의 `team_confirmation.fields`에 표시한다. 기존 10 GHz
ideal·SGP4 산출물은 재현성 보존을 위해 이 설정으로 자동 변경하지 않는다.

## OFDM 채널 grid 축

`build_ofdm_channel_grid_axes`는 아직 채널값을 계산하지 않고 SISO 채널
`H[m, k]`의 좌표만 정의한다. 배열의 첫 번째 축 `m`은 OFDM 심벌, 두 번째
축 `k`는 활성 부반송파이다. 시간은 `DownlinkStateSI.time_s`와 동일한 상대
시간 원점을 사용한다.

```python
from starlink_isl import build_ofdm_channel_grid_axes, load_research_baseline

baseline = load_research_baseline("configs/ofdm_baseline.yaml")
axes = build_ofdm_channel_grid_axes(
    baseline.ofdm,
    baseline.radio.carrier_frequency_hz,
    symbol_count=8,
    symbol_time_reference=baseline.channel_grid.symbol_time_reference,
)

assert axes.shape == (8, 200)
```

현재 임시 활성 배치는 DC를 비우고
`[-100, ..., -1, 1, ..., 100]`으로 둔다. 이는 중심주파수 기준 signed
index이며 NumPy FFT 배열에서 바로 사용할 `fft_bin_indices`도 함께 제공한다.

\[
f_k=k\Delta f,\qquad f_{\mathrm{RF},k}=f_{\mathrm{carrier}}+f_k
\]

기본 채널 평가 시각은 CP 뒤 유효 FFT 구간의 중앙이다.

\[
t_m=t_{\mathrm{frame}}
+mT_{\mathrm{OFDM}}+T_{\mathrm{CP}}+\frac{T_{\mathrm{useful}}}{2}
\]

1 ms `channel_state.update_interval_s`는 전체 패스의 상태 기록과 블록 채널에
사용하는 기준 갱신 간격이고, `H[m,k]`는 프레임 안의 실제 OFDM 심벌 시각에
평가한다. Cubic Hermite는 1 ms에 제한되지 않으므로 필요한 심벌 시각을
직접 목표 시각으로 전달할 수 있다. 정확한 활성 배치와 심벌 시간 기준은
민영님의 송수신기와 합칠 때 YAML 값 또는 명시적 index 입력만 교체한다.

## 복소 OFDM 채널 grid 생성

`starlink-channel-grid`는 기존 SGP4 패스의 OMM과 요약 파일을 읽어 선택한
이벤트 주변의 프레임 크기 복소 채널 `H[m,k]`를 생성한다. 기본값은
최근접 시각을 중심으로 한 256개 OFDM 심벌이다.

```powershell
starlink-channel-grid
```

직접 모듈로 실행할 수도 있다.

```powershell
python -m starlink_isl.channel_grid_simulate
```

기본 출력은 `outputs/channel_grid`에 생성된다.

| 파일 | 내용 |
|---|---|
| `channel_grid.npz` | 복소 `H[m,k]`, 두 축, 거리·지연·Doppler·FSPL |
| `time_axis.csv` | 심벌 번호, 시작 시각, 채널 평가 시각 및 UTC |
| `frequency_axis.csv` | signed index, FFT bin, baseband/RF 주파수 |
| `summary.json` | 모델 범위, grid 크기 및 물리량 최솟값·최댓값 |
| `channel_grid_heatmap.png` | `H[m,k]` 크기와 wrapped phase heatmap |
| `channel_grid_slices.png` | 특정 시각·부반송파의 주파수/시간 단면 |

채널식은 다음과 같다.

\[
H[m,k]=a[m,k]e^{j\phi_D[m]}e^{-j2\pi f_k\tau[m]}
\]

`a[m,k]`는 각 RF 부반송파에서 계산한 FSPL 진폭이며, `phi_D[m]`은 기준
이벤트 거리에서 시작하는 반송파 Doppler 위상이다. 마지막 항은 절대 전파
지연의 주파수별 위상이다.

이 grid는 한 OFDM 심벌을 한 시각으로 대표하는 대각 채널이다. 큰 미보상
Doppler가 심벌 안에서 만드는 ICI는 포함하지 않으며 시간영역 CFO 또는 별도
ICI 연산자가 필요하다. 또한 절대 지연을 주파수 위상으로 기록한 것이므로,
실제 FFT 심벌에 적용하기 전에는 수신기 timing alignment 기준과 맞춰야 한다.
CP가 수 ms 절대 전파 지연을 대신 보상하는 것은 아니다.

## 채널 상태 재표본화

`resample_downlink_state_si`는 1초 간격 SGP4 anchor 상태를 1 ms 등 임의의
채널 갱신 시각으로 cubic Hermite 보간한다. SGP4를 대체하지 않으며 목표
시각은 반드시 원본 시간 범위 안에 있어야 한다.

```python
import numpy as np

from starlink_isl import resample_downlink_state_si

# source는 같은 반송파에서 계산한 1초 간격 DownlinkStateSI
target_time_s = np.arange(0.0, 2.0 + 0.001, 0.001)
dense_state = resample_downlink_state_si(
    source,
    target_time_s,
    carrier_frequency_hz=11.7e9,
    minimum_elevation_rad=np.deg2rad(10.0),
)
```

위성 및 지상국 위치는 양 끝의 위치·속도를 함께 사용하는 cubic Hermite로
보간한다. 보간된 벡터에서 LOS, 경사거리, range rate, 지연 및 Doppler를
다시 계산하고, 위상은 직접 보간하지 않고 경사거리에서 다시 계산한다.

STARLINK-5285의 최근접점 부근에서 1초 SGP4 anchor를 1 ms로 보간해 같은
시각의 직접 SGP4 결과와 비교한 회귀 테스트 한계는 위치 2 cm, 속도
2 cm/s, 경사거리 2 mm, Doppler 0.05 Hz, 위상 0.5 rad이다. 현재 관측된
최대 Doppler 오차는 약 0.018 Hz이고 위상 오차는 약 0.22 rad이다.

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

## 팀 통합용 SI 인터페이스

기존 분석 API와 CSV의 `km`, `km/s`, `deg` 필드는 하위 호환성을 위해
유지한다. OFDM·채널·빔포밍 모듈을 연결할 때는 `DownlinkStateSI`를 사용한다.

```python
import numpy as np

from starlink_isl import ideal_downlink_state_si

state = ideal_downlink_state_si(
    np.arange(0.0, 11.0),
    carrier_frequency_hz=10.0e9,
    minimum_elevation_rad=np.deg2rad(10.0),
)

print(state.satellite_position_m.shape)       # (sample_count, 3)
print(state.los_satellite_to_ue_unit.shape)   # (sample_count, 3)
print(state.slant_range_m)
print(state.elevation_rad)
```

공통 규칙은 다음과 같다.

| 항목 | 규칙 |
|---|---|
| 위치·거리 | m |
| 속도·radial velocity | m/s |
| 시간 | 시뮬레이션 기준 s |
| 각도 | rad |
| radial velocity 부호 | 멀어지면 `+`, 접근하면 `-` |
| LOS | 위성에서 UE로 향하는 단위벡터 |
| 위치·속도·LOS 형상 | `(sample_count, 3)` |
| 향후 안테나 신호 형상 | `(antenna_count, sample_count)` |

`ideal_downlink_state_si`는 ECI 좌표를, `sgp4_downlink_state_si`는 ECEF
좌표를 반환하며 `coordinate_frame` 필드로 이를 명시한다. 방위각은 지상국의
북쪽에서 동쪽으로 증가한다. 천정에서는 방위각이 정의되지 않으므로 `NaN`이다.
SGP4 인터페이스의 `time_s`는 기본적으로 첫 입력 UTC를 정확히 `0 s`로 둔다.

## 파형 독립 SISO 위성 채널

`apply_siso_downlink_channel`은 OFDM 프레임을 생성하거나 해석하지 않는다.
다른 모듈이 만든 임의의 복소 기저대역 신호에 자유공간 경로손실, Doppler
위상 회전과 선택적 열잡음만 적용한다.

```python
import numpy as np

from starlink_isl import (
    SISOChannelConfig,
    apply_siso_downlink_channel,
    ideal_downlink_state_si,
)

state = ideal_downlink_state_si(0.0, carrier_frequency_hz=10.0e9)
tx_signal = np.ones((1, 288), dtype=np.complex128)
config = SISOChannelConfig(
    carrier_frequency_hz=10.0e9,
    sample_rate_hz=1.0e6,  # 파형 모듈과 합의한 값으로 교체
    transmit_power_w=1.0,
    noise_bandwidth_hz=1.0e6,
    add_awgn=True,
)
result = apply_siso_downlink_channel(tx_signal, state, config)

print(result.received_signal.shape)       # (1, 288)
print(result.free_space_path_loss_db)
print(result.doppler_shift_hz)
print(result.propagation_delay_s)
```

입력은 무차원 복소 신호이며 평균전력 정규화는 송신 파형 모듈의 책임이다.
단위 평균전력 입력에는 `transmit_power_w`의 제곱근이 곱해진다. 반환 신호의
단위는 `sqrt(W)`이고 잡음전력은 `k*T*B`이다. 안테나 이득과 beamforming
이득은 포함하지 않으므로 이후 배열 모듈에서 중복 없이 추가해야 한다.

첫 구현은 한 채널 블록 동안 거리와 Doppler 주파수가 일정하다고 가정하되,
Doppler 위상은 모든 파형 샘플에서 증가시킨다. OFDM 연결 시 심볼마다
`state_index`를 갱신할 수 있다. 절대 전파 지연은 메타데이터로 반환하며
샘플 이동은 하지 않는다. 따라서 현재 수신 신호는 완벽한 타이밍 동기화로
정렬된 기준선이다.

긴 연속 파형에서는 `apply_siso_downlink_sequence`로 샘플을 여러 채널
블록으로 나눌 수 있다. 블록은 OFDM 심벌을 뜻하지 않고 거리·경로손실·
Doppler를 갱신하는 계산 단위다. 블록 내부에서는 이 값들이 일정하고,
Doppler 위상은 블록 경계에서도 초기화되지 않고 연속으로 이어진다.

```python
from starlink_isl import apply_siso_downlink_sequence

state = ideal_downlink_state_si(
    [0.0, 0.001, 0.002],
    carrier_frequency_hz=10.0e9,
)
tx_signal = np.ones((1, 3000), dtype=np.complex128)
sequence = apply_siso_downlink_sequence(
    tx_signal,
    state,
    config,
    block_boundaries=[0, 1000, 2000, 3000],
    state_indices=[0, 1, 2],
)
```

`block_boundaries`는 전체 파형을 나누는 샘플 인덱스이고 각
`state_indices`는 해당 블록 시작 시각의 기하 상태를 고른다. 선택한 상태
시각은 `첫 상태 시각 + 블록 시작 인덱스 / sample_rate_hz`와 일치해야 한다.
전체 신호에 하나의 AWGN 난수열을 사용하므로 블록마다 같은 잡음이 반복되지
않는다.

## 파형 독립 CFO·Doppler 보상

CFO는 수신기가 예상한 반송파와 실제 수신 반송파 사이의 주파수 차이다.
위성 Doppler와 발진기 오차가 주요 원인이며, 복소 기저대역 신호의 위상을
샘플마다 계속 회전시킨다. `compensate_cfo`는 변조 방식과 관계없이 추정한
CFO와 초기 위상의 반대 회전을 적용한다.

```python
from starlink_isl import compensate_siso_channel_doppler

# 채널의 실제 Doppler를 사용하는 완벽한 기준선
perfect = compensate_siso_channel_doppler(result)

# 실제값보다 300 Hz 작게 추정한 경우: +300 Hz residual CFO
imperfect = compensate_siso_channel_doppler(
    result,
    estimated_doppler_hz=result.doppler_shift_hz - 300.0,
)

print(perfect.residual_cfo_hz)    # 0.0
print(imperfect.residual_cfo_hz)  # 300.0
```

보상기는 위상과 주파수만 교정한다. 경로손실로 줄어든 진폭과 AWGN은 그대로
남는다. 현재 구현은 완벽한 보상 및 외부 추정값 보상을 제공한다. SGP4 예측값
또는 이후 pilot 추정값을 같은 입력 필드에 전달할 수 있으며, pilot 생성·배치와
OFDM 처리는 이 모듈에 포함하지 않는다.

다중 블록 결과에는 `compensate_siso_channel_sequence_doppler`를 사용한다.
추정값을 생략하면 완벽한 기준 보상이 되고, 스칼라 또는 블록별 배열을
전달하면 추정 오차가 있는 경우를 계산한다. 보상기의 위상도 블록 경계에서
초기화되지 않으므로 앞 블록에서 생긴 잔류 주파수 오차가 자연스럽게
누적된다.

## 파형 독립 수신 FIR 필터

`apply_receiver_filter`는 복소 기저대역 신호의 각 행을 독립적으로
저역통과 필터링한다. OFDM 심벌, pilot, FFT 및 변조 방식은 해석하지 않으며,
여러 행을 입력해도 결합하거나 beamforming하지 않는다.

```python
from starlink_isl import ReceiverFilterConfig, apply_receiver_filter

filter_config = ReceiverFilterConfig(
    sample_rate_hz=1.0e6,
    passband_edge_hz=100.0e3,  # 실제 점유 대역폭의 절반 이상
    stopband_edge_hz=180.0e3,
    num_taps=129,
)
filtered = apply_receiver_filter(
    perfect.compensated_signal,
    filter_config,
)

print(filtered.group_delay_samples)              # 64
print(filtered.equivalent_noise_bandwidth_hz)
```

현재 수신 기준선은 큰 위성 Doppler를 먼저 보상한 뒤 디지털 수신 필터를
적용한다. 그래야 필터 통과대역이 수백 kHz의 원래 Doppler까지 불필요하게
포함하지 않아도 된다. FIR은 인과적으로 적용되며 출력 길이는 입력과 같다.
군지연을 자동 제거하거나 마지막 convolution tail을 덧붙이지 않으므로,
OFDM 모듈은 `group_delay_samples`를 이용해 심벌 경계를 정렬해야 한다.

긴 신호를 여러 번 호출해 처리할 때는 앞 결과의 `final_state`를 다음 호출의
`initial_state`로 전달한다. 전체 다중 블록 신호를 한 번에 전달하면 채널
블록 경계에서도 필터 상태가 자동으로 유지된다.

채널 AWGN과 이 필터를 함께 사용할 때는 `SISOChannelConfig`의
`noise_bandwidth_hz=sample_rate_hz`로 필터 전 백색잡음을 생성하는 것이
기준이다. 그러면 필터 뒤 잡음전력은 근사적으로
`k*T*equivalent_noise_bandwidth_hz`가 된다. 채널에서 이미 최종 수신
대역폭으로 `kTB`를 만든 뒤 같은 필터를 다시 적용하면 잡음 대역폭을 두 번
반영하게 되므로 피해야 한다.

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

### 실제 CelesTrak OMM·SGP4 패스

```powershell
starlink-simulate `
  --model sgp4 `
  --norad-id 55296 `
  --start-utc 2026-07-29T00:00:00Z `
  --search-hours 24 `
  --minimum-elevation-deg 10
```

실제 모델은 성균관대 자연과학캠퍼스의 WGS-84 좌표
`37.2934° N, 126.9747° E`를 사용합니다. 검색 구간의 모든 패스를
`outputs/sgp4_downlink/passes.csv`에 기록하고, 최대 앙각 패스의 상세
결과와 그래프를 같은 디렉터리에 생성합니다. 이상 모델 결과가 있는
`outputs/ideal_downlink/`는 변경하지 않습니다.

프로그램 간 연결에는 동일한 SI 인터페이스를 사용할 수 있다.

```python
from starlink_isl import sgp4_downlink_state_si

state = sgp4_downlink_state_si(
    datetimes,
    satellite,
    carrier_frequency_hz=10.0e9,
    minimum_elevation_rad=np.deg2rad(10.0),
)
```

### SGP4 좌표와 거리 필드

SGP4 `ground_track.png`와 `results.csv`의
`satellite_geodetic_longitude_deg`,
`satellite_geodetic_latitude_deg`,
`satellite_geodetic_altitude_km`는 모두 WGS-84 측지 좌표이다. 지상국도
동일한 측지 위도·경도 기준으로 표시한다. 하위 호환성을 위한
`satellite_longitude_deg`와 `satellite_latitude_deg` 별칭 역시 SGP4
결과에서는 같은 측지 좌표를 담는다.

`surface_distance_km`는 두 ECEF 위치벡터의 지심각에 평균 지구 반지름
6,371.0088 km를 곱한 **spherical central-angle approximation**이다.
WGS-84 타원체상의 정밀 측지선 거리가 아니다.

### QPSK 파형·AWGN·도플러 기준선

SGP4 패스 산출물을 만든 뒤 다음 명령으로 단일 반송파 QPSK 수신 성능을
계산할 수 있다.

```powershell
starlink-waveform `
  --geometry-results outputs/sgp4_downlink/results.csv `
  --geometry-summary outputs/sgp4_downlink/summary.json `
  --symbol-rate-msps 1 `
  --pilot-symbol-count 256 `
  --symbol-count 8192
```

결과는 기본적으로 `outputs/qpsk_downlink/`에 저장된다. 각 패스 시각을
국소적으로 정지한 채 알려진 QPSK 파일럿과 데이터 심볼에 복소 AWGN 및
도플러 회전을 적용한다. 파일럿의 연속 위상차로 도플러를 추정하고 공통
위상까지 보상한 수신기를 무보상·완벽 보상 기준과 비교한다. 기본값은
파일럿 256심볼과 데이터 8,192심볼로, 파일럿 오버헤드는 약 3.03%이다.
심볼 SNR인 \(E_s/N_0\)는 기존 링크 버짓의 \(C/N_0\)와 설정한 심볼률로부터
계산한다. 절대 전파 지연은 완벽한 타이밍 동기화로 정렬되었다고 가정하며,
아직 채널 코딩, 펄스 성형, 다중경로, 페이딩 및 발진기 오차는 포함하지
않는다.

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
