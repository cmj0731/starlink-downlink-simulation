# 팀 OFDM·채널 통합 계약 v1

이 문서는 채널 모듈과 OFDM 송수신기 사이의 최종 결합 규칙이다. 기준 파일은
`configs/ofdm_baseline.yaml`이며 `scenario.status`가
`team_integration_v1`, `team_confirmation.required_before_final_integration`가
`false`인 설정만 v1 계약으로 인정한다. 이 값들은 연구용 합의이며 실제 Starlink
독점 파형 규격에 대한 주장이 아니다.

## 1. 고정 OFDM 기준

| 항목 | v1 값 |
|---|---:|
| 반송파 주파수 | 11.7 GHz |
| 링크 방향 | downlink |
| FFT 크기 | 256 |
| 부반송파 간격 | 120 kHz |
| 샘플레이트 | 30.72 MHz |
| 샘플주기 | 약 32.552 ns |
| 활성 부반송파 | 223 |
| CP | 0 samples |
| OFDM 심벌시간 | 약 8.333 us |
| 변조 baseline | QPSK |
| 파일럿 | frequency comb, 활성 열 기준 간격 16 |
| 파일럿/데이터 열 | 15 / 208 |
| 채널 평가 시각 | 유효 FFT 구간 중앙 |

활성 부반송파의 signed index와 `fftshift` bin은 각각

\[
k\in\{-112,\ldots,-1,1,\ldots,111\},
\qquad
b_{\rm shift}\in\{16,\ldots,127,129,\ldots,239\}
\]

이다. DC bin 128과 양쪽 guard bin은 `H[m,k]`에 포함하지 않는다.

## 2. 복소 채널 배열

채널의 기본 전달 배열은 `channel_response`, 즉 `H[m,k]`다.

- dtype: `complex128`
- shape: `(ofdm_symbol_count, 223)`
- 첫 번째 축 `m`: 시간, OFDM 심벌 순서
- 두 번째 축 `k`: 주파수, signed index가 증가하는 순서
- 단위: 무차원 복소 전압비
- 사용식: `Y_active[m,k] = H[m,k] * X_active[m,k]`

OFDM 팀은 `frequency_mapping.csv`의 `fftshift_bin_index`를 사용해 256-bin
파형 배열에서 활성 열만 선택한다. guard와 DC가 `H`에서 생략된 것은 해당
주파수의 물리 채널 이득이 0이라는 뜻이 아니다. 송신 심벌이 없는 열이므로
인터페이스에서 제외한 것이다.

원시 채널은

\[
H[m,k]=a[m,k]e^{j\phi_D[m]}e^{-j2\pi f_k\tau[m]}
\]

이며 FSPL, 반송파 Doppler 위상과 지연 위상 기울기를 포함한다. synchronized
채널은 FSPL을 유지하면서 예측값을 제거한 뒤의 잔류 위상을 포함한다. 두 배열은
파일명과 `prediction_label`로 구분하고 섞어 사용하지 않는다.

## 3. 파형 정규화

데이터 QPSK 심벌의 평균 에너지는 1이고 파일럿 크기도 1이다. `fftshift`
주파수 배열을 NumPy 기본 IFFT 규칙으로 변환할 때는 다음 배율을 사용한다.

\[
x[n]
=\frac{N_{\rm FFT}}{\sqrt{K_{\rm active}}}
\operatorname{IFFT}
\left\{\operatorname{IFFTShift}(X_{\rm shift}[k])\right\}
\]

현재 배율은

\[
\frac{256}{\sqrt{223}}\simeq17.143
\]

이다. 모든 활성 열의 심벌 에너지가 1이면 `mean(abs(x)**2) = 1`이 된다.
채널의 시간영역 입력은 이 단위 평균전력 복소 포락선이며, 물리 송신전력은 채널
모듈이 별도로 `sqrt(transmit_power_w)`를 곱한다. 따라서 OFDM 수치 정규화와
물리 W 단위를 중복 적용하지 않는다.

## 4. 시간, 단위와 부호

`DownlinkStateSI`와 채널 grid는 다음 규칙을 사용한다.

| 값 | 단위/규칙 |
|---|---|
| 시간 | s, 프레임 또는 시뮬레이션 상대시간 |
| 위치·거리 | m |
| 속도·range rate | m/s |
| 각도·위상 | rad |
| Doppler | Hz |
| LOS | 위성에서 UE로 향하는 단위벡터 |
| 벡터 배열 | `(sample_count, 3)` |
| radial velocity 부호 | 거리가 증가하면 `+`, 접근하면 `-` |
| Doppler 부호 | `f_D = -v_r f_c/c` |
| 예측 bias | `prediction - truth` |
| 보상 후 residual | `truth - prediction` |
| 정규화 CFO | `residual_cfo_hz / subcarrier_spacing_hz` |

SGP4 상태는 ECEF, 이상적 모델 상태는 ECI이므로 `coordinate_frame`을 확인한다.
좌표계가 다른 위치·속도 벡터를 직접 빼지 않는다.

외부 위성 상태 CSV의 v1 입력 계약은 다음과 같다.

- `schema_version=2`
- `utc`: timezone 포함 ISO-8601, 엄격히 증가하고 중복 없음
- `coordinate_frame`: 파일 전체가 `TEME` 또는 `ECEF` 중 하나
- `position_unit=m`, `velocity_unit=m/s`: 파일 전체에서 고정
- 위치: `satellite_{x,y,z}_m`, 단위 m
- 속도: `satellite_v{x,y,z}_m_s`, 단위 m/s
- 선택 identity: `object_name`, `norad_catalog_id`

`TEME` 입력만 ECEF 회전과 `omega_E x r` 보정을 적용한다. 이미 ECEF인 속도를
다시 회전하지 않는다. 입력 위치·속도를 Hermite 보간한 뒤 LOS, range rate와
Doppler를 다시 계산하며, 제공된 Doppler를 별도 truth로 간주하지 않는다.

외부 상태 CSV로 채널을 생성할 때는 지상국의 WGS-84 geodetic 위도·경도·고도를
모두 명시한다. 기존 산출물의 지상국 좌표를 묵시적으로 상속하지 않으며, 실제
사용 좌표는 채널 `summary.json`의 `station` 객체에 반드시 기록한다.

외부 위치·속도는 좌표계 변환 전에 같은 프레임에서 구간별 위치 차분 속도와
양 끝 제공 속도의 평균을 비교한다. 벡터 오차가 `50 m/s + 기준 속력의 5%`를
넘으면 입력을 거부한다. 통과한 오차 지표는 `summary.json`에 기록하며, 이
검사는 km/m 또는 km/s/m/s 혼동과 위치·속도 시각 불일치를 조기에 찾기 위한
입력 계약 검증이다.

필수 수치 열의 NaN/Inf를 거부하고, 표시 단위와 실제 크기의 불일치를 찾기 위해
지구 중심 반지름 `6.3e6~1.0e8 m`와 최대 속력 `2.0e4 m/s`도 검사한다. 이
범위는 현재 지구궤도 위성 채널 입력 계약이며 심우주 궤도 입력을 위한 범위가
아니다.

## 5. 역할 경계

채널 담당은 `H[m,k]`, 두 축, 거리·지연·range rate·Doppler·경로 이득과
명시적으로 이름 붙인 보상 채널을 제공한다. OFDM 담당은 비트/QPSK 매핑,
파일럿 심벌, FFT/IFFT, 등화·판정과 BER·EVM·ICI 계산을 담당한다. 결합부에서는
`frequency_mapping.csv`로 열을 맞추고 위 정규화만 적용한다.

기본 교환 파일은 `channel_grid.npz`이고, CSV 기반 모듈에는
`channel_grid.csv`를 제공한다. CSV는 time-major long format이며 한 행이
한 `(m,k)` 셀이다. 복소 채널은 `h_real`, `h_imag` 두 열로 전달한다.
`symbol_index`, `channel_evaluation_time_s`, `grid_column`, signed/FFT bin,
baseband/RF 주파수도 같은 행에 포함한다. CSV를 wide matrix로 임의 변환하여
주파수 열 순서를 잃지 않는다.

CSV schema v2에서 `channel_variant`, `delay_compensation`,
`doppler_compensation`은 파일 전체에서 하나의 값이어야 한다. 현재 CSV는
`raw/none/none`이며, 보상 채널로 해석하거나 다시 이름만 바꾸지 않는다.
NPZ와 `summary.json`도 `raw`, `perfectly_compensated`,
`block_start_compensated`를 같은 이름으로 기록한다.

빔포밍/안테나 배열 차원, 다중경로 tap, 실제 Starlink 파형 주장은 v1 SISO
계약에 포함하지 않는다. 이후 MIMO·빔포밍을 도입할 때는 `H[m,k]`의 앞 또는
뒤에 안테나 축을 추가하는 별도 버전으로 올린다.

## 6. 생성과 확인

다음 명령은 설정을 검증하고 기계 판독형 계약을 생성한다.

```powershell
starlink-team-interface
```

기본 산출물은 다음과 같다.

- `outputs/team_interface/interface_manifest.json`
- `outputs/team_interface/frequency_mapping.csv`
- `outputs/channel_grid/channel_grid.npz`
- `outputs/channel_grid/channel_grid.csv`
- `outputs/channel_grid/time_axis.csv`
- `outputs/channel_grid/frequency_axis.csv`

결합 전에 두 팀은 FFT 크기, 120 kHz spacing, CP=0, 223개 활성 열,
`fftshift` bin, `H`의 `(time, frequency)` 축, 심벌 중앙 시각과 정규화 식이
일치하는지만 확인하면 된다.
