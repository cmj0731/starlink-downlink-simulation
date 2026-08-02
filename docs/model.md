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
z_m[n]=\sum_{k=0}^{L-1}h[k]r_m[n-k]
\]

여기서 (m)은 신호 또는 안테나 스트림 인덱스다. 스트림을 서로 더하지
않으므로 이 단계에는 RX beamforming이 포함되지 않는다. 계수 (h[k])는
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
B_{\rm eq}=f_s\frac{\sum_k |h[k]|^2}{|\sum_k h[k]|^2}
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
