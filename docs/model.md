# 이상적 STARLINK-5285 Downlink 모델 정의

## 1. 목적과 범위

이 문서는 `STARLINK-5285`와 성균관대학교 자연과학캠퍼스 지상국 사이의
downlink를 분석하기 위한 1차 이상 모델을 정의한다. 이 단계의 목적은 실제
궤도를 그대로 재현하는 것이 아니라, 지구 자전과 경사 원궤도를 포함한
상대운동에서 거리, 전파 지연, 도플러 및 경로손실을 일관된 좌표계로 계산할
기준을 만드는 것이다.

실제 CelesTrak OMM과 SGP4를 이용한 모델은 이 이상 모델을 검증한 후 별도
단계에서 추가한다.

## 2. 기준 대상

| 항목 | 값 |
|---|---:|
| 위성 이름 | STARLINK-5285 |
| NORAD catalog ID | 55296 |
| 지상국 | 성균관대학교 자연과학캠퍼스 |
| 실제 측지 위도 | 37.2934 deg N |
| 실제 측지 경도 | 126.9747 deg E |

이상 모델에서는 구형 지구의 회전 대칭성을 이용해 지상국의 초기 경도를
`0 deg`로 둔다. 이는 실제 지상국을 다른 장소로 옮기는 것이 아니라 전체
관성좌표계를 실제 경도만큼 회전한 것과 같다. 실제 패스의 UTC 시각을 구하는
SGP4 모델에서는 실제 경도 `126.9747 deg E`를 사용한다.

## 3. 단위와 기호

내부 계산의 기본 단위는 다음과 같다.

- 거리: km
- 속도: km/s
- 시간: s
- 각도 입력과 표시: deg
- 삼각함수와 내부 각도: rad
- 주파수: Hz
- 전파 지연: s

주요 기호:

| 기호 | 의미 |
|---|---|
| \(R_E\) | 구형 지구 반지름 |
| \(h\) | 위성 고도 |
| \(r_s=R_E+h\) | 위성 공전 반지름 |
| \(T_s\) | 위성 궤도주기 |
| \(n=2\pi/T_s\) | 위성 평균 각속도 |
| \(\omega_E\) | 지구 자전 각속도 |
| \(i\) | 위성 궤도 경사각 |
| \(\phi_g\) | 지상국 위도 |
| \(\lambda_g\) | 지상국 경도 |
| \(\rho\) | 위성–지상국 경사거리 |
| \(e\) | 지상국에서 본 앙각 |

## 4. 기준 상수

| 상수 | 기준값 |
|---|---:|
| 지구 반지름 \(R_E\) | 6,378 km |
| 위성 고도 \(h\) | 572 km |
| 공전 반지름 \(r_s\) | 6,950 km |
| 궤도주기 \(T_s\) | 5,766.6 s |
| 궤도 경사각 \(i\) | 70 deg |
| 지상국 위도 \(\phi_g\) | 37.2934 deg |
| 이상 모델 초기 경도 \(\lambda_g(0)\) | 0 deg |
| 지구 자전 각속도 \(\omega_E\) | \(7.2921159\times10^{-5}\) rad/s |
| 진공 중 광속 \(c\) | 299,792.458 km/s |

이 값으로부터

\[
n=\frac{2\pi}{T_s}\approx1.08959\times10^{-3}\ {\rm rad/s}
\]

\[
v_s=r_s n\approx7.57\ {\rm km/s}
\]

를 얻는다.

## 5. 좌표계

지구중심 관성좌표계(ECI)를 이상 모델의 기본 좌표계로 사용한다.

- 원점: 지구 중심
- \(+z\)축: 지구 북극 방향, 자전축과 일치
- \(x\)-\(y\) 평면: 적도면
- \(+x\)축: \(t=0\)에서 지상국 경도 `0 deg`가 놓이는 방향
- 회전 방향: \(+z\)축에서 내려다볼 때 반시계 방향을 양의 방향으로 정의

지구는 ECI 안에서 각속도 \(\omega_E\)로 회전한다. 위성 궤도면은 ECI에
고정되어 있으며, 지구와 함께 회전하지 않는다.

## 6. 초기조건

### 6.1 지상국

구형 지구 모델에서 지상국의 초기 위치는

\[
\mathbf r_g(0)=R_E
\begin{bmatrix}
\cos\phi_g\\
0\\
\sin\phi_g
\end{bmatrix}
\]

이다. 지상국은 위도를 유지하면서 지구 자전축 주위를 회전한다.

\[
\mathbf r_g(t)=R_E
\begin{bmatrix}
\cos\phi_g\cos(\omega_Et)\\
\cos\phi_g\sin(\omega_Et)\\
\sin\phi_g
\end{bmatrix}
\]

### 6.2 위성

\(t=0\)에 위성이 지상국의 천정에 있도록 설정한다.

\[
\mathbf r_s(0)=\frac{r_s}{R_E}\mathbf r_g(0)
\]

따라서 지구 중심, 지상국 및 위성은 같은 반직선 위에 있고 초기 경사거리는

\[
\rho(0)=h=572\ {\rm km}
\]

이다.

경사각 \(i=70\ {\rm deg}\)인 궤도가 위도 \(\phi_g\)를 통과하려면
\(|\phi_g|\le i\)여야 한다. 현재 값은 이 조건을 만족한다.

초기 통과 방향은 북향(ascending)으로 고정한다. 원궤도의 argument of
latitude \(u\)와 RAAN \(\Omega\)는 다음과 같이 선택할 수 있다.

\[
u_0=\sin^{-1}\left(\frac{\sin\phi_g}{\sin i}\right)
\]

\[
\Omega=\operatorname{atan2}
\left(-\sin u_0\cos i,\ \cos u_0\right)
\]

위성의 시간별 argument of latitude는

\[
u(t)=u_0+nt
\]

이다. 이에 따른 ECI 위치는

\[
\mathbf r_s(t)=r_s
\begin{bmatrix}
\cos\Omega\cos u-\sin\Omega\sin u\cos i\\
\sin\Omega\cos u+\cos\Omega\sin u\cos i\\
\sin u\sin i
\end{bmatrix}
\]

로 정의한다.

남향(descending) 천정 통과는 별도 시나리오로 취급하며 초기 기준 모델에는
포함하지 않는다.

## 7. Downlink 기하량

지상국에서 위성으로 향하는 기존 분석용 상대 위치벡터와 경사거리는

\[
\boldsymbol\rho(t)=\mathbf r_s(t)-\mathbf r_g(t)
\]

\[
\rho(t)=\|\boldsymbol\rho(t)\|
\]

이다. 실제 전파는 이 경사거리만큼 이동한다.

팀 통합 인터페이스에서 사용하는 LOS는 전파의 진행 방향과 맞추어 반대
방향으로 정의한다.

\[
\hat{\boldsymbol\ell}_{s\rightarrow g}(t)=
\frac{\mathbf r_g(t)-\mathbf r_s(t)}{\rho(t)}
\]

위성과 지상국의 지구중심각은

\[
\psi(t)=\cos^{-1}
\left(
\frac{\mathbf r_s(t)\cdot\mathbf r_g(t)}{r_sR_E}
\right)
\]

이고, 지표면 대권거리는

\[
d_{\rm surface}(t)=R_E\psi(t)
\]

이다. 대권거리는 지상궤적 분석용이며 downlink 전파거리로 사용하지 않는다.

지상국의 국부 천정 단위벡터는

\[
\hat{\mathbf z}_g(t)=\frac{\mathbf r_g(t)}{R_E}
\]

이고 앙각은

\[
e(t)=\sin^{-1}
\left(
\frac{\boldsymbol\rho(t)\cdot\hat{\mathbf z}_g(t)}
{\rho(t)}
\right)
\]

으로 계산한다.

기준 모델의 기하학적 가시 조건은 \(e(t)\ge0\ {\rm deg}\)이다. 실제 링크
분석을 위한 최소 앙각은 이후 매개변수로 추가하며 기본 후보값은 `10 deg`로
둔다.

## 8. 이후 단계에서 사용할 채널량

이 문서에서는 구현하지 않지만, 이후 단계에서는 같은 경사거리와 상대속도를
사용해 다음 값을 계산한다.

전파 지연:

\[
\tau(t)=\frac{\rho(t)}{c}
\]

시선방향 상대속도:

\[
v_r(t)=
\frac{
\boldsymbol\rho(t)\cdot
\left(\mathbf v_s(t)-\mathbf v_g(t)\right)
}{\rho(t)}
\]

도플러 편이:

\[
f_D(t)=-\frac{v_r(t)}{c}f_c
\]

자유공간 경로손실:

\[
L_{\rm FSPL}(t)=
20\log_{10}
\left(
\frac{4\pi\rho(t)f_c}{c}
\right)
\]

도플러 부호는 위 식을 프로젝트 표준으로 사용한다. 이에 따라 접근 중
\(v_r<0\)이면 \(f_D>0\), 이탈 중 \(v_r>0\)이면 \(f_D<0\)이다.

## 9. 기준 모델의 가정

- 지구는 반지름 6,378 km의 완전한 구이다.
- 지구는 일정한 각속도로 자전한다.
- 위성은 일정한 고도와 속도의 원궤도를 운동한다.
- 위성 궤도면은 ECI에 고정되어 있다.
- \(t=0\)에 위성은 지상국 천정을 북향으로 통과한다.
- 지상국 고도는 0 km이다.
- 신호는 진공 중 광속으로 직선 전파한다.
- 위성과 지상국의 시계는 완전히 동기화되어 있다고 가정한다.

## 10. 현재 제외하는 효과

- 실제 TLE/OMM epoch와 위성의 실제 궤도상 위치
- SGP4 섭동과 궤도 이심률
- J2 등 비구면 중력장
- WGS-84 지구 편평도와 측지·지심 위도 차이
- 세차, 장동, 극운동 및 UT1–UTC 보정
- 지상국 실제 고도와 주변 지형 차폐
- 대기 굴절, 기체 흡수, 구름 및 강우 감쇠
- 전리층·대류권 지연
- 송수신 안테나 패턴, 편파 및 추적 오차
- 송신기 주파수 오차와 수신기 발진기 오차
- 다중경로, 페이딩, 간섭 및 열잡음
- 상대론적 시간·주파수 보정

이 효과들은 이상 모델의 수치 검증이 끝난 뒤 필요한 순서대로 추가한다.

## 11. 구현 검증 기준

다음 단계의 운동 모델은 최소한 아래 조건을 만족해야 한다.

1. 모든 시각에 \(\|\mathbf r_g(t)\|=R_E\)이다.
2. 모든 시각에 \(\|\mathbf r_s(t)\|=r_s\)이다.
3. 위성 궤도면의 경사각은 `70 deg`이다.
4. \(t=0\)에 위성·지상국 위치벡터가 같은 방향이다.
5. \(t=0\)의 경사거리는 `572 km`이고 앙각은 `90 deg`이다.
6. 위성은 한 궤도주기 후 ECI상의 초기 위치로 돌아온다.
7. 지구 자전을 끈 특수조건에서는 기존 정적 구면지구 해석 결과를 재현한다.

## 12. 팀 통합용 SI 인터페이스

기존 분석 모델의 내부 단위와 CSV 필드는 결과 재현성과 하위 호환성을 위해
`km`, `km/s`, `deg`를 유지한다. 송수신·채널·빔포밍 코드와 연결할 때는
`DownlinkStateSI`를 사용하며 다음 규칙을 적용한다.

- 위치와 거리: m
- 속도와 radial velocity: m/s
- 시간: 시뮬레이션 시작 기준 s
- 방위각과 고도각: rad
- radial velocity: 거리가 증가하면 양수, 접근하면 음수
- LOS: 위성에서 UE로 향하는 정규화 단위벡터
- 위치·속도·LOS 배열: `(sample_count, 3)`
- 향후 안테나 신호 배열: `(antenna_count, sample_count)`

공통 필드는 다음과 같다.

| 필드 | 의미 |
|---|---|
| `time_s` | 시뮬레이션 기준 시간 |
| `satellite_position_m` | 위성 위치 |
| `satellite_velocity_m_s` | 위성 속도 |
| `ue_position_m` | 지상 UE 위치 |
| `ue_velocity_m_s` | 지상 UE 속도 |
| `los_satellite_to_ue_unit` | 위성→UE LOS 단위벡터 |
| `slant_range_m` | 3차원 경사거리 |
| `azimuth_rad`, `elevation_rad` | UE에서 본 방위각과 고도각 |
| `radial_velocity_m_s` | 거리 변화율 |
| `propagation_delay_s` | 절대 전파 지연 |
| `doppler_shift_hz` | 1차 Doppler 편이 |
| `doppler_phase_rad` | 기준 시각 대비 Doppler 위상 |

이상 궤도 생성자는 ECI, SGP4 생성자는 ECEF 상태를 반환한다. 두 경우 모두
`coordinate_frame`에 좌표계를 명시하므로 서로 다른 프레임의 위치벡터를
직접 혼합하지 않는다. 거리, radial velocity, LOS, 방위각과 고도각은 동일한
물리적 규칙을 따른다.

## 13. 파형 독립 SISO 채널 경계

OFDM 구현과 위성 채널 구현의 역할을 분리하기 위해 첫 채널 함수는 입력
파형의 변조 방식, FFT 크기, CP 및 pilot 배치를 알지 못한다. 입력은
`(1, sample_count)` 형태의 무차원 복소 기저대역 신호이다.

선택한 채널 상태 하나에 대한 타이밍 정렬 수신 신호는

\[
y[n]=
\sqrt{P_t}\,x[n]
10^{-\left(L_{\rm FSPL}+L_{\rm other}\right)/20}
\exp\left(j\left[\phi_0+2\pi f_D\frac{n}{f_s}\right]\right)
+w[n]
\]

으로 정의한다. 여기서 (x[n])은 송신 파형, (P_t)는 `transmit_power_w`,
(f_s)는 샘플링 주파수이다. 잡음은

\[
E\{|w[n]|^2\}=kT_{\rm sys}B
\]

를 만족하는 원형 대칭 복소 AWGN이다. 복소 신호에 적용하는 경로손실은
전력 비가 아니라 진폭 비이므로 dB 값을 `20`으로 나누어 변환한다.

초기 모델의 경계는 다음과 같다.

- OFDM 비트·QAM·pilot·IFFT·CP는 채널 범위 밖이다.
- 안테나 이득과 TX/RX beamforming은 채널 범위 밖이다.
- 한 블록 동안 거리와 Doppler 주파수는 국소적으로 일정하다.
- Doppler 위상은 파형의 모든 샘플에서 진행한다.
- OFDM 통합 시 채널 상태를 심볼당 한 번 갱신할 수 있다.
- 절대 전파 지연은 반환하지만 신호 샘플을 이동시키지 않는다.
- 반환 신호와 잡음의 복소 포락선 단위는 `sqrt(W)`이다.

## 14. CFO와 Doppler 보상

수신 신호의 실제 주파수 오프셋과 초기 위상을 각각
\(\Delta f\), \(\phi_0\)라고 하면 CFO가 포함된 신호는

\[
r[n]=s[n]\exp\left(
j\left[\phi_0+2\pi\Delta f\frac{n}{f_s}\right]
\right)
\]

로 쓸 수 있다. 보상기는 추정값 \(\hat{\Delta f}\), \(\hat\phi_0\)를
사용해

\[
\hat s[n]=r[n]\exp\left(
-j\left[\hat\phi_0+2\pi\hat{\Delta f}\frac{n}{f_s}\right]
\right)
\]

를 계산한다. 보상 후 남는 잔류 CFO와 초기 위상은

\[
\Delta f_{\rm residual}=\Delta f-\hat{\Delta f}
\]

\[
\phi_{\rm residual}=\phi_0-\hat\phi_0
\]

로 정의한다. 현재 수신기 기준선은 다음을 구분한다.

1. 완벽한 보상: 채널이 사용한 실제 Doppler와 위상을 그대로 사용한다.
2. 궤도 예측 보상: SGP4 또는 궤도 모델의 예측값을 외부에서 전달한다.
3. Pilot 추정 보상: 이후 OFDM 모듈이 제공하는 pilot에서 얻은 추정값을
   전달한다.

`compensate_cfo`와 `compensate_siso_channel_doppler`는 첫 두 경우와 이후
pilot 추정값의 적용 경로를 제공한다. 보상 연산은 단위 크기의 복소 지수만
곱하므로 신호와 잡음의 평균전력을 바꾸지 않으며, 경로손실에 대한 진폭
equalization도 수행하지 않는다.

## 15. 다중 블록 시변 채널

긴 연속 파형은 경계 샘플 인덱스

\[
0=n_0<n_1<\cdots<n_B=N
\]

로 나눈다. 여기서 블록은 OFDM 프레임 구조가 아니라 채널 상태의 갱신
단위다. 블록 (b) 안에서는 거리, 자유공간 경로손실, 전파 지연 및 Doppler
주파수 (f_{D,b})를 국소적으로 일정하게 두고 위상은

\[
\phi[n]=\phi[n_b]+2\pi f_{D,b}\frac{n-n_b}{f_s},
\qquad n_b\le n<n_{b+1}
\]

로 진행시킨다. 다음 블록의 시작 위상은

\[
\phi[n_{b+1}]=\phi[n_b]
+2\pi f_{D,b}\frac{n_{b+1}-n_b}{f_s}
\]

로 넘겨 인위적인 위상 재설정을 만들지 않는다. 첫 블록만 선택한 기하
상태의 `doppler_phase_rad`를 초기 위상으로 사용한다.

`apply_siso_downlink_sequence`의 입력 규칙은 다음과 같다.

- `tx_signal`: `(1, N)` 복소 기저대역 파형
- `block_boundaries`: 처음이 `0`, 끝이 `N`인 엄격히 증가하는 정수 배열
- `state_indices`: 블록마다 하나의 `DownlinkStateSI` 표본을 선택하는 배열
- 선택한 상태 시각: 파형 샘플 시계로 계산한 각 블록 시작 시각과 일치

마지막 조건은 서로 멀리 떨어진 궤도 시각을 하나의 연속 파형으로 잘못
연결하지 않기 위한 검증이다. 떨어진 패스 시각의 짧은 스냅숏을 비교하려면
각 시각마다 별도의 채널 호출을 사용한다. 잡음은 전체 시퀀스에서 난수
생성기를 한 번만 진행시킨다.

`compensate_siso_channel_sequence_doppler`도 같은 경계를 사용해 보상 위상을
연속 적분한다. 블록별 추정 Doppler를 생략하면 완벽한 기준 보상이며,
외부 배열을 전달하면 각 블록의 잔류 CFO와 경계에서 누적된 잔류 위상을
함께 반환한다. 이 인터페이스는 OFDM 심벌, pilot 위치 및 QAM 변조를
해석하지 않는다.

## 16. 파형 독립 수신 FIR 필터

수신 필터는 각 복소 기저대역 스트림에 동일한 실수 계수 FIR을 독립적으로
적용한다.

\[
z_m[n]=\sum_{k=0}^{L-1}g_{\rm RX}[k]r_m[n-k]
\]

여기서 (m)은 신호 또는 안테나 스트림 인덱스다. 스트림을 서로 더하지
않으므로 이 단계에는 RX beamforming이 포함되지 않는다. 계수
\(g_{\rm RX}[k]\)는
홀수 탭 수를 갖는 대칭 저역통과 FIR이며 군지연은

\[
D=\frac{L-1}{2}, \qquad \tau_D=\frac{D}{f_s}
\]

이다. 필터는 인과적으로 적용하고 출력 길이를 입력과 동일하게 유지한다.
따라서 앞쪽에는 초기 과도구간이 있고, 군지연 제거와 OFDM 심벌 경계 정렬은
후속 파형 모듈에서 명시적으로 처리해야 한다.

`ReceiverFilterConfig`의 주파수는 양의 단측 복소 기저대역 크기로 정의한다.
전체 점유 대역폭이 (B)라면 일반적으로
`passband_edge_hz >= B / 2`로 둔다. 설계 cutoff는 통과대역 끝과 저지대역
시작의 중간에 놓인다. 실제 샘플레이트와 점유 대역폭은 송신 OFDM 모듈의
설정과 일치해야 한다.

단위 DC 이득 필터의 복소 백색잡음 등가대역폭은

\[
B_{\rm eq}=f_s
\frac{\sum_k |g_{\rm RX}[k]|^2}{|\sum_k g_{\rm RX}[k]|^2}
\]

로 기록한다. 채널과 수신 필터를 함께 쓰는 기준 경로에서는 채널의 필터 전
잡음전력을 `noise_bandwidth_hz=sample_rate_hz`로 설정한다. 그러면 필터 뒤
잡음전력은

\[
P_{n,\rm out}\simeq kT_{\rm sys}B_{\rm eq}
\]

가 된다. 채널 단계에서 이미 최종 수신 대역폭으로 (kTB)를 계산하고 같은
필터를 다시 적용하면 대역 제한을 중복 반영하게 된다.

현재 디지털 기준 처리 순서는 다음과 같다.

1. 다중 블록 위성 채널과 필터 전 AWGN
2. 궤도 예측 또는 pilot 추정값을 이용한 Doppler/CFO 보상
3. 디지털 수신 FIR 필터
4. 군지연 정렬 후 OFDM CP 제거, FFT 및 복조

큰 위성 Doppler를 먼저 보상하면 디지털 필터가 원래 수백 kHz Doppler까지
포함하도록 불필요하게 넓어지는 것을 막을 수 있다. 여러 조각으로 처리할
때는 반환된 `final_state`를 다음 호출의 `initial_state`로 전달해 필터 기억을
유지한다.

## 17. 임시 OFDM 연구 baseline

팀 통합 전 채널 grid와 수신 필터를 개발하기 위한 공통 가정을
`configs/ofdm_baseline.yaml`에 기록한다. 이 설정은 실제 Starlink 파형
규격에 대한 주장이 아니며 `scenario.status: provisional`과
`represents_actual_starlink_waveform: false`로 경계를 명시한다.

민영 님의 no-CP 송수신기에 맞춘 연구 numerology는

\[
f_{\rm carrier}=11.7\ {\rm GHz},\quad
N_{\rm FFT}=256,\quad
\Delta f=120\ {\rm kHz},\quad
K_{\rm active}=223,\quad
N_{\rm CP}=0
\]

이다. 독립 입력으로부터 계산되는 값은

\[
f_s=N_{\rm FFT}\Delta f=30.72\ {\rm MHz}
\]

\[
T_s=\frac{1}{f_s}\simeq32.552\ {\rm ns}
\]

\[
B_{\rm occupied}\simeq K_{\rm active}\Delta f=26.76\ {\rm MHz}
\]

\[
T_{\rm OFDM}
=\frac{N_{\rm FFT}+N_{\rm CP}}{f_s}
=8.333\ {\rm us}
\]

이다. 수신 필터의 임시 통과대역 끝은 13.5 MHz, 저지대역 시작은
14.7 MHz로 두어 활성 부반송파 중심 범위를 포함하고 15.36 MHz Nyquist
주파수보다 낮게 둔다.

원본 SGP4 기하 상태는 1초 간격이고 채널 갱신 간격은 1 ms로 가정한다.
두 시간축 사이는 cubic Hermite 재표본화를 사용하고, 이후 직접 SGP4를
같은 ms 시각에 전파한 결과와 위치·거리·range rate·Doppler·위상 오차를
비교한다.

`starlink-config configs/ofdm_baseline.yaml` 명령은 파생값을 출력하고 다음
불일치를 거부한다.

- 활성 부반송파 수가 사용 가능한 FFT bin 수를 초과하는 경우
- 수신 필터가 OFDM 점유대역을 자르는 경우
- 수신 필터 저지대역이 Nyquist 주파수 이상인 경우
- 채널 갱신 간격이 원본 기하 상태 간격보다 긴 경우
- 실험 spacing 후보에 baseline spacing이 없는 경우

NFFT, spacing, no-CP, 활성 부반송파 및 pilot 배치는 팀 송수신기에 맞췄다.
파형 정규화와 심벌 평가 기준은 최종 통합 전에 확인한다.

## 18. OFDM 채널 grid의 시간·주파수 축

SISO 시간-주파수 채널은 `H[m,k]` 형태로 두며 행 `m`은 OFDM 심벌,
열 `k`는 활성 부반송파를 뜻한다. 이 단계에서는 채널값을 계산하지 않고
두 좌표와 배열 차원만 확정한다.

부반송파는 중심주파수에 대한 signed FFT index를 사용한다.

\[
f_k=k\Delta f,\qquad
f_{\mathrm{RF},k}=f_{\mathrm{carrier}}+k\Delta f
\]

현재 팀 기준 DC-null 배치는

\[
k\in\{-112,\ldots,-1,1,\ldots,111\}
\]

이다. 민영 님의 `fftshift` 배열에서는 16번부터 239번까지 사용하되 중앙
128번 DC를 비운 결과다. 자연 FFT 배열 접근용 index `k mod N_FFT`와
shifted 배열 접근용 `fftshift_bin_indices`를 모두 제공한다. 예를 들어
signed index `-112`는 자연 FFT bin 144, shifted bin 16에 해당한다.

주파수 comb pilot은 활성 부반송파 순서에서 간격 16으로 두고 양쪽 활성대역
끝을 포함한다. `fftshift` bin 기준 위치는

\[
\{16,32,48,64,80,96,112,129,145,161,177,193,209,225,239\}
\]

이며 pilot 15개를 제외한 데이터 부반송파는 208개다. DC bin 128은 pilot과
데이터 모두 사용하지 않는다.

한 심벌을 대표하는 채널 시각은 기본적으로 CP가 끝난 뒤 유효 FFT 구간의
중앙으로 정의한다.

\[
t_m=t_{\mathrm{frame}}+mT_{\mathrm{OFDM}}
+T_{\mathrm{CP}}+\frac{T_{\mathrm{useful}}}{2}
\]

이는 채널이 한 심벌 동안 거의 일정하다는 근사에서 FFT 구간을 대표하는
명확한 시각이다. 필요하면 `symbol_start` 또는 `fft_window_start`로 바꿀 수
있으나 송수신기와 통합할 때 동일한 기준을 사용해야 한다.

1 ms 채널 상태 갱신 간격과 약 8.333 us OFDM 심벌 간격은 서로 다른 목적의
시간축이다. 1 ms는 전체 패스 기록 및 블록 채널 상태의 기준 간격이고,
`H[m,k]`를 만들 때는 Hermite 상태를 각 OFDM 심벌 평가 시각에 다시 표본화한다.
따라서 최종 grid의 시간 차원은 1 ms 간격으로 제한되지 않는다. 전체 패스의
모든 심벌을 한 배열에 담지 않고 실제 프레임 단위로 생성한다.

현재 코드가 확정한 인터페이스는 다음과 같다.

- `OFDMTimeAxis`: 심벌 번호, 심벌 시작 시각, 채널 평가 시각
- `OFDMFrequencyAxis`: signed index, 자연/shifted FFT bin, baseband/RF 주파수
- `OFDMChannelGridAxes.shape`: `(symbol_count, active_subcarrier_count)`

활성 부반송파 배치는 송수신기와 맞췄으며 심벌 평가 기준은 최종 통합 확인
항목으로 `team_confirmation.fields`에 남겨 둔다.

## 19. 복소 SISO OFDM 채널 grid

시간·주파수 축과 같은 시각에 재표본화한 `DownlinkStateSI`를 이용해 다음
복소 채널을 계산한다.

\[
H[m,k]
=a[m,k]\exp\left(j\phi_D[m]\right)
\exp\left(-j2\pi f_k\tau[m]\right)
\]

여기서 실제 RF 부반송파 주파수는

\[
f_{\mathrm{RF},k}=f_{\mathrm{carrier}}+f_k
\]

이고 자유공간 진폭 이득은

\[
a[m,k]
=10^{-\left(L_{\mathrm{FSPL}}[m,k]+L_{\mathrm{other}}\right)/20}
\]

\[
L_{\mathrm{FSPL}}[m,k]
=20\log_{10}\left(
\frac{4\pi d[m]f_{\mathrm{RF},k}}{c}
\right)
\]

로 계산한다. 26.76 MHz 대역은 11.7 GHz 반송파에 비해 좁으므로 주파수에
따른 진폭 차이는 작지만, 실제 RF 주파수별 값을 계산해 근사를 숨기지 않는다.

`phi_D[m]`은 SGP4/Hermite 경사거리로부터 얻은 반송파 Doppler 위상이다.
기준 이벤트 거리의 상수 반송파 위상은 0으로 두되 이후 시간 변화는 모두
유지한다. `exp(-j2 pi f_k tau[m])`는 절대 지연이 만드는 부반송파별 위상
기울기이다. 이는 시간영역에서 신호를 수 ms 이동시킨 것과 동일한 의미를
가질 수 있지만, 현재 grid 자체는 샘플 배열을 이동시키지 않는다.

따라서 이 결과를 OFDM FFT 출력에 바로 곱할 때는 다음 범위를 지켜야 한다.

- `H[m,k]`는 한 심벌당 하나의 대각 채널 계수이다.
- 심벌 내부의 미보상 Doppler와 ICI는 이 대각 행렬에 포함되지 않는다.
- 실제 수신기는 예측 지연으로 timing alignment를 한 뒤 잔류 지연 기준을
  맞춰야 한다.
- CP는 timing alignment 후 남은 채널 impulse response를 위한 것이며 수 ms
  절대 위성 전파시간 자체를 흡수하는 장치가 아니다.
- 현재 결과에는 multipath, 안테나 이득, beamforming 및 AWGN이 없다.

### 19.1 Raw 채널과 위상 동기화 후 채널

Raw 채널은 전체 carrier Doppler 위상과 절대 전파지연 위상을 포함한다.
예측값 \(\hat\phi_D[m]\), \(\hat\tau[m]\)을 제거한 채널은

\[
H_{\rm sync}[m,k]
=a[m,k]
\exp\left(j(\phi_D[m]-\hat\phi_D[m])\right)
\exp\left(-j2\pi f_k(\tau[m]-\hat\tau[m])\right)
\]

로 정의한다. FSPL과 기타 scalar loss 진폭은 제거하지 않는다. 구현은 큰
절대 delay phasor 두 개를 직접 곱해 상쇄하지 않고 residual delay와 residual
carrier phase에서 `H_sync`를 다시 구성해 수치 정밀도를 유지한다.

현재 기본 산출물의 `perfect_same_state_prediction`은 raw 채널을 만든 것과
같은 SGP4/Hermite 상태를 예측값으로 사용하는 검증용 상한선이다. 따라서
잔류 delay와 phase는 정확히 0이고 `H_sync=a`가 된다. 이 단계는 실제 receiver
estimator, pilot 추정 또는 OFDM 결합을 포함하지 않는다. 예측 carrier phase는
raw 채널과 동일한 기준 이벤트와 상수 위상 기준을 사용해야 한다.

`block_start_held_delay_constant_doppler`는 각 블록의 첫 채널 상태만 사용한다.
블록 시작 시각을 \(t_0\)라 하면

\[
\hat\tau(t)=\tau(t_0)
\]

\[
\hat\phi_D(t)=
\phi_D(t_0)+2\pi f_D(t_0)(t-t_0)
\]

로 예측한다. 첫 시각의 delay, carrier phase와 Doppler는 정확하다고 가정하지만,
이후 심벌의 실제 delay·Doppler는 보상기 갱신에 사용하지 않는다. 따라서

\[
\delta\tau(t)=\tau(t)-\tau(t_0),\qquad
\delta f_D(t)=f_D(t)-f_D(t_0)
\]

와 비선형 carrier phase 오차가 남는다. 이는 아직 pilot estimator가 아니라
블록당 한 번 완전한 상태를 얻는 채널 측 기준 모델이다.

`channel_grid.npz`에는 raw 복소 채널과 함께 시간축, signed/자연 FFT/shifted FFT
주파수축,
거리, 지연, radial velocity, Doppler, FSPL 및 위상 항을 저장한다. CSV는
두 축을 사람이 읽기 위한 파일이고 PNG는 크기·wrapped phase heatmap과
단면을 보여준다. 전체 가시 패스의 모든 OFDM 심벌을 한 번에 저장하면 매우
커지므로 이벤트 주변 프레임 단위로 생성한다.

내부 복소 배열은 `H[m,k]`, 즉 `(time, frequency)` 순서로 유지한다. Heatmap은
시간-주파수 표의 관례에 맞춰 x축을 시간, y축을 주파수로 표시하므로 시각화
단계에서만 `H.T`를 사용한다. 이 전치는 저장 형식이나 채널 계산식을 바꾸지
않는다.

`synchronized_channel_grid.npz`에는 perfect `H_sync`를,
`block_start_synchronized_channel_grid.npz`에는 블록 시작 보상 채널을 저장한다.
두 파일 모두 raw 채널, 예측 delay/phase, 잔류 delay/phase 및 예측 label을
포함한다. `synchronization_comparison.png`는 동일한 시간-주파수축에서 raw,
블록 시작 보상, perfect 보상의 wrapped phase를 비교한다.

### 19.2 패스 3개 이벤트 비교

`starlink-channel-events`는 가시 시작, 최근접, 가시 종료 UTC를 기존 SGP4
패스 summary에서 읽고 각 이벤트를 중심으로 동일한 크기의 독립 채널 grid를
생성한다. 이벤트별 raw/synchronized 산출물은 별도 하위 폴더에 보존한다.

집계 CSV에는 이벤트 기준 거리, 지연, radial velocity, carrier Doppler,
FSPL과 프레임 동안의 unwrapped carrier phase 변화량을 기록한다. 짝수 개의
OFDM 심벌은 상대시각 0을 직접 포함하지 않으므로 이벤트 기준 scalar 값은
0을 사이에 둔 두 중앙 상태를 선형 보간한다. 이는 균일한 OFDM 심벌 grid에
비균일 이벤트 행을 추가하지 않기 위한 것이다.

가시 시작과 종료에서는 raw Doppler의 절댓값이 OFDM symbol rate의 Nyquist
범위를 넘을 수 있다. 따라서 심벌 시각에서만 표시한 wrapped phase heatmap은
시간축 alias를 보일 수 있으며, 이를 심벌 내부 ICI가 계산됐다는 뜻으로
해석하면 안 된다. 집계된 carrier phase 변화량은 wrapped 그림이 아니라
경사거리에서 계산한 unwrapped physical phase를 사용한다.

### 19.3 짧은 OFDM grid와 긴 magnitude 관측축

현재 LOS 채널의 크기는

\[
|H(t,f_k)|=
10^{-L_{\rm other}/20}
\frac{c}{4\pi d(t)(f_c+f_k)}
\]

이므로 시간에 따른 경사거리 \(d(t)\)와 주파수 \(f_c+f_k\) 양쪽에 의존한다.
따라서 magnitude는 원래 모든 시간 표본에서 변한다. 다만 120 kHz SCS,
256심벌, CP 없음 설정의 채널 평가 span은

\[
(256-1)T_{\rm OFDM}=2.125\ {\rm ms}
\]

뿐이다. 가시 시작과 종료의 near-DC magnitude 변화도 이 구간에서는 각각 약
\(6.5\times10^{-5}\) dB이고, 최근접에서는 약 \(7.3\times10^{-10}\) dB이다.
반면 한 시각에서 223개 부반송파에 걸친 magnitude 차이는 약 0.0199 dB이다.
즉 짧은 프레임 그림에서 시간 변화가 보이지 않는 것은 채널이 고정됐기 때문이
아니라 관측 시간이 너무 짧기 때문이다.

`magnitude_evolution.npz`는 전체 약 506초 가시 패스를 기본 0.1초 간격으로
관측한 `(time, frequency)` magnitude 배열이다. 이때 near-DC magnitude의
시간 변화폭은 약 10.26 dB로 명확하게 나타난다. 이 배열은 긴 시간의 채널
envelope를 표시하기 위한 것으로, OFDM 복소 grid `H[m,k]`를 대신하지 않는다.
복소 위상과 실제 심벌 처리는 기존 OFDM 심벌 시간축에서 수행해야 한다.

### 19.4 OFDM 블록 길이와 채널의 국소 정지성

`starlink-channel-blocks`는 각 이벤트를 중심으로 최대 1200심벌 채널 grid를
한 번 계산하고, 그 안에서 중심이 같은 120, 256, 600, 1200심벌 구간을
선택한다. CP가 없는 120 kHz SCS에서 각 구간은 다음과 같다.

| 심벌 수 | 명목 블록 길이 \(NT_{\rm OFDM}\) | 채널 평가 span \((N-1)T_{\rm OFDM}\) |
|---:|---:|---:|
| 120 | 1.000000 ms | 0.991667 ms |
| 256 | 2.133333 ms | 2.125000 ms |
| 600 | 5.000000 ms | 4.991667 ms |
| 1200 | 10.000000 ms | 9.991667 ms |

시간 \(t\)의 전체 주파수 채널 벡터를 \(\mathbf h(t)\), 이벤트 기준 벡터를
\(\mathbf h(0)\)이라 하면 비교 상관도는

\[
\rho(t)=
\frac{\left|\mathbf h(0)^{H}\mathbf h(t)\right|}
{\|\mathbf h(0)\|_2\,\|\mathbf h(t)\|_2}
\]

로 정의한다. 절댓값을 취하므로 모든 부반송파에 공통인 carrier phase 회전은
제거되지만, delay 변화가 만드는 부반송파별 phase slope 차이는 남는다.
따라서 \(|\rho|\)가 작다는 것은 수신전력이 작아졌다는 의미가 아니라, 이벤트
중심의 한 채널 벡터를 블록 전체에 그대로 쓰기 어려워졌다는 의미이다.

현재 패스의 주요 결과는 다음과 같다.

- 가시 시작·종료의 near-DC magnitude span은 1 ms에서 약
  \(3.1\times10^{-5}\) dB, 10 ms에서도 약 \(3.1\times10^{-4}\) dB이다.
- 같은 구간의 최대 carrier-phase excursion은 약 129 cycles에서
  1304 cycles까지 증가한다.
- 가시 시작·종료의 최소 주파수 벡터 상관도는 1 ms에서 약 0.86,
  현재 256심벌에서 약 0.45이고, 5 ms 이상에서는 블록 안에 거의 0인
  시점이 포함된다.
- 최근접에서는 10 ms 동안에도 magnitude 변화가 약
  \(1.6\times10^{-8}\) dB이고 주파수 벡터 상관도는 사실상 1이다.

즉 이 LOS 모델에서 ms 단위 블록의 amplitude는 거의 고정으로 볼 수 있지만,
가시 시작·종료에서는 Doppler와 delay phase 때문에 복소 채널을 같은 값으로
고정할 수 없다. 실제 허용 블록 길이는 이후 pilot 배치와 예측 오차를 결합한
잔류 채널을 기준으로 다시 결정해야 한다.

블록 시작 보상을 적용한 현재 256심벌 블록의 최대 잔류값은 다음과 같다.

| 이벤트 | 잔류 delay | 잔류 CFO | 잔류 carrier phase | 전체 grid 잔류 phase |
|---|---:|---:|---:|---:|
| 가시 시작 | 47.378 ns | 0.161 Hz | 0.000169 cycles | 0.637 cycles |
| 최근접 | 0.000163 ns | 7.199 Hz | 0.007649 cycles | 0.007649 cycles |
| 가시 종료 | 47.409 ns | 0.169 Hz | 0.000181 cycles | 0.637 cycles |

가시 경계에서는 Doppler 자체는 크지만 2.133 ms 동안의 Doppler 변화는 작아서
carrier phase 예측 오차가 작다. 대신 큰 radial velocity 때문에 고정한 delay와
실제 delay의 차이가 빠르게 증가하여 band-edge 잔류 phase가 커진다. 최근접은
delay 변화가 거의 없지만 Doppler 변화율이 커서 잔류 CFO와 carrier phase가
상대적으로 더 크게 나타난다.

## 20. SGP4 anchor와 cubic Hermite 재표본화

SGP4는 OMM 궤도요소로 임의의 UTC에서 위성 위치와 속도를 직접 계산하는
기준 궤도 전파 모델이다. Cubic Hermite는 SGP4로 계산한 두 anchor 상태의
위치와 속도를 이용해 중간 시각을 채우는 수치 보간이며 새로운 궤도 물리를
추가하지 않는다.

두 anchor 시각을 \(t_i,t_{i+1}\), 위치와 속도를 각각
\(\mathbf p_i,\mathbf v_i\), \(\mathbf p_{i+1},\mathbf v_{i+1}\)라고 하고

\[
u=\frac{t-t_i}{t_{i+1}-t_i},\qquad
\Delta T=t_{i+1}-t_i
\]

로 두면 위치는

\[
\mathbf p(t)=
h_{00}(u)\mathbf p_i
h_{10}(u)\Delta T\mathbf v_i
h_{01}(u)\mathbf p_{i+1}
h_{11}(u)\Delta T\mathbf v_{i+1}
\]

로 계산한다. Hermite 기저는

\[
h_{00}=2u^3-3u^2+1,\quad
h_{10}=u^3-2u^2+u
\]

\[
h_{01}=-2u^3+3u^2,\quad
h_{11}=u^3-u^2
\]

이다. 속도는 위 위치 다항식을 시간으로 미분해 얻는다. 위성과 UE 벡터를
각각 보간한 후

\[
\boldsymbol\rho(t)=\mathbf p_{\rm UE}(t)-\mathbf p_{\rm sat}(t)
\]

\[
d(t)=\|\boldsymbol\rho(t)\|,qquad
\hat{\boldsymbol\rho}(t)=\frac{\boldsymbol\rho(t)}{d(t)}
\]

\[
v_r(t)=
\left(\mathbf v_{\rm UE}(t)-\mathbf v_{\rm sat}(t)\right)
\mathbin{\cdot}\hat{\boldsymbol\rho}(t)
\]

를 다시 계산한다. 이로부터

\[
\tau(t)=\frac{d(t)}{c},\qquad
f_D(t)=-\frac{v_r(t)}{c}f_{\rm carrier}
\]

를 얻는다. 큰 누적 위상을 직접 보간하지 않고 기준 거리
\(d_{\rm ref}\)를 사용해

\[
\phi_D(t)=-\frac{2\pi f_{\rm carrier}}{c}
\left[d(t)-d_{\rm ref}\right]
\]

로 재계산한다. 따라서

\[
\frac{d\phi_D}{dt}=2\pi f_D(t)
\]

관계가 유지된다.

재표본화는 anchor 범위 밖으로 외삽하지 않는다. 같은 반송파로 생성된 원본
상태만 입력할 수 있으며 Doppler와 반송파가 불일치하면 오류를 발생시킨다.
전체 패스에서는 Hermite를 사용하되 일부 ms 시각을 직접 SGP4로 계산해
위치·속도·거리·range rate·Doppler·위상 오차를 검증한다.
