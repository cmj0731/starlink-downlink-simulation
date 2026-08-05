import fs from "node:fs/promises";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const ROOT = "C:/Users/최민준/Documents/URP_practice/starlink_proj";
const OUT_DIR = `${ROOT}/outputs/artifact_qa/project_history_pptx`;
const OUT_PPTX = `${ROOT}/docs/STARLINK-5285_프로젝트_진행과정.pptx`;

const C = {
  ink: "#111827",
  muted: "#5B6472",
  faint: "#8A94A3",
  blue: "#1666D8",
  blue2: "#3B82F6",
  blueSoft: "#EAF2FF",
  cyanSoft: "#E9F8FB",
  orange: "#F28C28",
  orangeSoft: "#FFF3E7",
  green: "#14805E",
  greenSoft: "#E8F7F1",
  red: "#C43D4E",
  redSoft: "#FDECEF",
  gray50: "#F7F8FA",
  gray100: "#EEF1F4",
  gray200: "#D9DEE6",
  gray700: "#374151",
  white: "#FFFFFF",
};

const FONT = "Malgun Gothic";

function textbox(slide, text, position, style = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    typeface: FONT,
    fontSize: 22,
    color: C.ink,
    autoFit: "shrinkText",
    verticalAlignment: "top",
    insets: { top: 0, right: 0, bottom: 0, left: 0 },
    ...style,
  };
  return shape;
}

function rect(slide, position, fill, radius = "rounded-xl", line = C.gray200) {
  return slide.shapes.add({
    geometry: radius ? "roundRect" : "rect",
    position,
    fill,
    line: { style: "solid", fill: line, width: line === "none" ? 0 : 1 },
    ...(radius ? { borderRadius: radius } : {}),
  });
}

function addBase(slide, page, section, title, subtitle = "") {
  slide.background.fill = C.white;
  textbox(slide, section.toUpperCase(), { left: 41, top: 28, width: 340, height: 22 }, {
    fontSize: 12, bold: true, color: C.blue,
  });
  textbox(slide, title, { left: 41, top: 58, width: 1160, height: 56 }, {
    fontSize: 36, bold: true, color: C.ink,
  });
  if (subtitle) {
    textbox(slide, subtitle, { left: 41, top: 115, width: 1120, height: 36 }, {
      fontSize: 16, color: C.muted,
    });
  }
  rect(slide, { left: 41, top: 686, width: 1198, height: 2 }, C.gray200, null, "none");
  rect(slide, { left: 41, top: 686, width: Math.max(62, 1198 * page / 14), height: 2 }, C.blue, null, "none");
  textbox(slide, String(page).padStart(2, "0"), { left: 1194, top: 692, width: 44, height: 18 }, {
    fontSize: 10, color: C.faint, alignment: "right",
  });
}

function addNotes(slide, lines) {
  slide.speakerNotes.textFrame.setText(`[Sources]\n${lines.map((x) => `- ${x}`).join("\n")}`);
  slide.speakerNotes.setVisible(true);
}

function addBulletList(slide, items, position, options = {}) {
  const color = options.color ?? C.gray700;
  const fontSize = options.fontSize ?? 21;
  const gap = options.gap ?? 58;
  items.forEach((item, i) => {
    rect(slide, { left: position.left, top: position.top + i * gap + 8, width: 9, height: 9 }, options.dotColor ?? C.blue, "rounded-full", "none");
    textbox(slide, item, {
      left: position.left + 24,
      top: position.top + i * gap,
      width: position.width - 24,
      height: gap - 4,
    }, { fontSize, color, lineSpacing: 1.12 });
  });
}

function addCard(slide, x, y, w, h, eyebrow, title, body, tone = "blue") {
  const palette = tone === "green"
    ? [C.greenSoft, C.green]
    : tone === "orange"
      ? [C.orangeSoft, C.orange]
      : tone === "red"
        ? [C.redSoft, C.red]
        : [C.blueSoft, C.blue];
  rect(slide, { left: x, top: y, width: w, height: h }, C.white, "rounded-2xl", C.gray200);
  rect(slide, { left: x + 20, top: y + 20, width: 54, height: 6 }, palette[1], "rounded-full", "none");
  textbox(slide, eyebrow, { left: x + 20, top: y + 39, width: w - 40, height: 22 }, {
    fontSize: 11, bold: true, color: palette[1],
  });
  textbox(slide, title, { left: x + 20, top: y + 70, width: w - 40, height: 66 }, {
    fontSize: 24, bold: true, color: C.ink,
  });
  textbox(slide, body, { left: x + 20, top: y + 143, width: w - 40, height: h - 163 }, {
    fontSize: 16, color: C.muted, lineSpacing: 1.15,
  });
}

async function addImage(slide, path, position, alt, fit = "contain") {
  const blob = await fs.readFile(path);
  rect(slide, { left: position.left - 5, top: position.top - 5, width: position.width + 10, height: position.height + 10 }, C.gray50, "rounded-2xl", C.gray200);
  return slide.images.add({
    blob,
    contentType: "image/png",
    alt,
    fit,
    position,
    geometry: "roundRect",
    borderRadius: "rounded-xl",
  });
}

function label(slide, text, x, y, w, tone = "blue") {
  const fill = tone === "green" ? C.greenSoft : tone === "orange" ? C.orangeSoft : C.blueSoft;
  const ink = tone === "green" ? C.green : tone === "orange" ? C.orange : C.blue;
  rect(slide, { left: x, top: y, width: w, height: 29 }, fill, "rounded-full", "none");
  textbox(slide, text, { left: x + 9, top: y + 6, width: w - 18, height: 18 }, {
    fontSize: 11, bold: true, color: ink, alignment: "center",
  });
}

function metric(slide, x, y, w, value, unit, caption, tone = "blue") {
  const accent = tone === "green" ? C.green : tone === "orange" ? C.orange : C.blue;
  rect(slide, { left: x, top: y, width: w, height: 224 }, C.white, "rounded-2xl", C.gray200);
  rect(slide, { left: x + 22, top: y + 22, width: 52, height: 6 }, accent, "rounded-full", "none");
  textbox(slide, value, { left: x + 22, top: y + 59, width: w - 44, height: 68 }, {
    fontSize: 47, bold: true, color: C.ink,
  });
  textbox(slide, unit, { left: x + 22, top: y + 128, width: w - 44, height: 28 }, {
    fontSize: 17, bold: true, color: accent,
  });
  textbox(slide, caption, { left: x + 22, top: y + 165, width: w - 44, height: 42 }, {
    fontSize: 15, color: C.muted,
  });
}

async function writeBlob(path, blob) {
  await fs.writeFile(path, new Uint8Array(await blob.arrayBuffer()));
}

export async function buildProjectDeck() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.mkdir(`${ROOT}/docs`, { recursive: true });

  const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });

  // 01 — Codex Grid 01: minimal title.
  {
    const s = p.slides.add();
    s.background.fill = C.white;
    textbox(s, "RESEARCH PROJECT · 2026", { left: 41, top: 32, width: 500, height: 26 }, {
      fontSize: 13, bold: true, color: C.blue,
    });
    textbox(s, "STARLINK‑5285\nDownlink Channel Project", { left: 41, top: 176, width: 1115, height: 242 }, {
      fontSize: 66, bold: true, color: C.ink, lineSpacing: 0.95,
    });
    textbox(s, "이상적 궤도 모델에서 실제 SGP4 패스와 OFDM용 H[m,k]까지", { left: 41, top: 488, width: 870, height: 65 }, {
      fontSize: 27, color: C.muted,
    });
    rect(s, { left: 41, top: 620, width: 180, height: 8 }, C.blue, "rounded-full", "none");
    textbox(s, "최민준 · 성균관대학교 자연과학캠퍼스", { left: 41, top: 647, width: 620, height: 28 }, {
      fontSize: 14, color: C.faint,
    });
    addNotes(s, ["프로젝트 저장소 README.md", "docs/model.md"]);
  }

  // 02 — Codex Grid 05: two-column purpose / boundary.
  {
    const s = p.slides.add();
    addBase(s, 2, "01 · RESEARCH FRAME", "무엇을 만들었는가", "위성 위치 정보가 OFDM 송수신기에서 사용할 수 있는 채널 상태로 이어지는 연결부");
    addCard(s, 41, 182, 568, 430, "PROJECT GOAL", "위성 운동을 통신 채널로 변환", "CelesTrak 궤도 원소 → 위치·속도 벡터 → 지상국 상대 거리·속도 → 지연·도플러·경로손실 → 복소 채널 H[m,k]", "blue");
    addCard(s, 632, 182, 568, 430, "RESPONSIBILITY BOUNDARY", "채널 파트의 결합 계약", "빔포밍과 OFDM 변복조 자체를 대신 구현하는 것이 아니라, 팀원이 바로 사용할 수 있는 시간·주파수 축과 채널 값, 메타데이터, 검증 규칙을 제공", "orange");
    addNotes(s, ["README.md", "docs/team_integration_contract.md"]);
  }

  // 03 — Codex Grid 17: chronological timeline.
  {
    const s = p.slides.add();
    addBase(s, 3, "02 · HISTORY", "개발 과정은 세 번의 현실화로 진행됐다", "수식을 먼저 검증하고, 실제 궤도와 팀 통합 요구를 차례로 연결");
    rect(s, { left: 112, top: 355, width: 1038, height: 4 }, C.gray200, "rounded-full", "none");
    const nodes = [
      [170, "1–6단계", "이상적 원궤도", "구면 지구·원궤도에서\n기하와 통신 물리 검증", C.blue],
      [499, "7단계", "실제 SGP4 패스", "CelesTrak OMM과 WGS‑84\n지상국 좌표 반영", C.orange],
      [828, "통합 준비", "OFDM 채널 인터페이스", "Hermite 보간·H[m,k]·\nCSV/NPZ 계약 확정", C.green],
    ];
    for (const [x, tag, title, body, color] of nodes) {
      rect(s, { left: x, top: 330, width: 54, height: 54 }, color, "rounded-full", "none");
      textbox(s, tag, { left: x - 44, top: 266, width: 142, height: 30 }, { fontSize: 13, bold: true, color, alignment: "center" });
      textbox(s, title, { left: x - 62, top: 414, width: 178, height: 34 }, { fontSize: 22, bold: true, color: C.ink, alignment: "center" });
      textbox(s, body, { left: x - 88, top: 464, width: 230, height: 86 }, { fontSize: 15, color: C.muted, alignment: "center" });
    }
    addNotes(s, ["Git commit history", "README.md 단계별 실행 기록"]);
  }

  // 04 — Codex Grid 13: four equal content cards.
  {
    const s = p.slides.add();
    addBase(s, 4, "03 · IDEAL MODEL", "1–6단계: 물리식을 분리해서 검증", "실제 궤도에 들어가기 전에 각 현상의 원인과 단위를 독립적으로 확인");
    const cards = [
      [41, "ORBIT", "원궤도", "고도 572 km\n주기 5,766.6 s\n경사각 70°", "blue"],
      [341, "GEOMETRY", "지상국 기하", "위도 37.2934°\n지구 자전 반영\n앙각·가시구간", "orange"],
      [641, "PROPAGATION", "지연·도플러", "경사거리/c\n거리 변화율\n누적 위상", "green"],
      [941, "LINK", "전력·잡음", "FSPL\n열잡음\nSNR·수신전력", "red"],
    ];
    for (const [x, eyebrow, title, body, tone] of cards) addCard(s, x, 196, 259, 386, eyebrow, title, body, tone);
    textbox(s, "핵심 구분", { left: 41, top: 616, width: 110, height: 24 }, { fontSize: 13, bold: true, color: C.blue });
    textbox(s, "절대 전파지연 ≠ 다중경로 지연확산 · 도플러 편이 ≠ 거리 증가에 따른 전력 감소 · CP는 절대 전파지연 보상 장치가 아님", { left: 153, top: 612, width: 1047, height: 38 }, { fontSize: 15, color: C.gray700 });
    addNotes(s, ["docs/model.md", "src/starlink_downlink/ideal.py 및 단계별 테스트"]);
  }

  // 05 — Codex Grid 08: image split.
  {
    const s = p.slides.add();
    addBase(s, 5, "04 · ACTUAL ORBIT", "7단계: CelesTrak OMM과 SGP4로 전환", "이상적 모델은 보존하고, 실제 궤도 모델을 별도 모드로 추가");
    addBulletList(s, [
      "NORAD ID 55296 · STARLINK‑5285",
      "TEME 상태벡터를 ECEF로 변환",
      "WGS‑84 geodetic 위·경도로 지상궤적 통일",
      "거리 최소와 최대 앙각 시점을 독립 최적화",
      "10° 가시 경계를 허용오차와 함께 포함",
    ], { left: 52, top: 200, width: 545 }, { fontSize: 18, gap: 65 });
    await addImage(s, `${ROOT}/outputs/sgp4_downlink/orbit_3d.png`, { left: 657, top: 164, width: 572, height: 475 }, "STARLINK-5285의 한 궤도와 선택 패스 3차원 시각화");
    textbox(s, "전체 한 궤도는 회색, 분석 패스와 가시구간은 파란색, 지상국 자전 경로는 주황색", { left: 665, top: 647, width: 555, height: 24 }, { fontSize: 11, color: C.faint, alignment: "center" });
    addNotes(s, ["CelesTrak GP/OMM data: https://celestrak.org/", "outputs/sgp4_downlink/orbit_3d.png", "src/starlink_downlink/sgp4_model.py"]);
  }

  // 06 — Codex Grid 19: metrics.
  {
    const s = p.slides.add();
    addBase(s, 6, "05 · SELECTED PASS", "선택 패스의 핵심 수치", "2026‑07‑29 07:42:36.761–07:51:02.674 UTC · 최소 앙각 10°");
    metric(s, 41, 202, 360, "505.9", "seconds", "10° 이상 전체 가시시간", "blue");
    metric(s, 460, 202, 360, "579.7", "kilometres", "최근접점 최소 경사거리", "green");
    metric(s, 879, 202, 360, "223.1", "kHz @ 10 GHz", "선택 패스 최대 절대 도플러", "orange");
    rect(s, { left: 41, top: 469, width: 1198, height: 138 }, C.gray50, "rounded-2xl", C.gray200);
    textbox(s, "최대 앙각", { left: 68, top: 493, width: 150, height: 24 }, { fontSize: 14, bold: true, color: C.blue });
    textbox(s, "85.1649° · 07:46:50.801 UTC", { left: 68, top: 528, width: 320, height: 32 }, { fontSize: 20, bold: true, color: C.ink });
    textbox(s, "최근접", { left: 472, top: 493, width: 150, height: 24 }, { fontSize: 14, bold: true, color: C.green });
    textbox(s, "07:46:50.953 UTC", { left: 472, top: 528, width: 260, height: 32 }, { fontSize: 20, bold: true, color: C.ink });
    textbox(s, "두 사건의 차이", { left: 840, top: 493, width: 180, height: 24 }, { fontSize: 14, bold: true, color: C.orange });
    textbox(s, "최대 앙각이 0.152 s 먼저", { left: 840, top: 528, width: 320, height: 32 }, { fontSize: 20, bold: true, color: C.ink });
    addNotes(s, ["outputs/sgp4_downlink/summary.json", "outputs/sgp4_downlink/passes.csv", "outputs/sgp4_downlink/results.csv"]);
  }

  // 07 — Codex Grid 05: model separation.
  {
    const s = p.slides.add();
    addBase(s, 7, "06 · SIGNAL TO CHANNEL", "연속파 분석에서 OFDM용 채널로 확장", "파형과 채널을 분리해, 다른 팀원의 OFDM 구현에도 그대로 연결되도록 설계");
    rect(s, { left: 41, top: 184, width: 570, height: 432 }, C.gray50, "rounded-2xl", C.gray200);
    label(s, "초기 신호 검증", 66, 209, 142, "blue");
    textbox(s, "QPSK + AWGN + 위성 도플러", { left: 66, top: 263, width: 500, height: 42 }, { fontSize: 26, bold: true });
    addBulletList(s, ["복소 기저대역 수신신호 구성", "성상도·BER·EVM 확인", "pilot 기반 도플러 추정 예비 실험"], { left: 72, top: 337, width: 475 }, { fontSize: 17, gap: 68 });
    rect(s, { left: 639, top: 184, width: 561, height: 432 }, C.blueSoft, "rounded-2xl", C.blue2);
    label(s, "최종 채널 인터페이스", 664, 209, 170, "green");
    textbox(s, "H[m,k] = a(tₘ) · exp{−j2πfₖτ(tₘ)}", { left: 664, top: 276, width: 492, height: 66 }, { fontSize: 28, bold: true, color: C.ink, alignment: "center" });
    textbox(s, "시간별 경로 이득 a(t)와 지연 τ(t)를 주파수축에 펼친 복소 SISO 채널", { left: 690, top: 370, width: 440, height: 74 }, { fontSize: 20, color: C.gray700, alignment: "center" });
    textbox(s, "RAW 채널과 Doppler/phase 보상 채널을 메타데이터로 명시", { left: 683, top: 493, width: 454, height: 50 }, { fontSize: 16, bold: true, color: C.blue, alignment: "center" });
    addNotes(s, ["src/starlink_downlink/qpsk.py", "src/starlink_downlink/channel_grid.py", "docs/team_integration_contract.md"]);
  }

  // 08 — Codex Grid 14: baseline table.
  {
    const s = p.slides.add();
    addBase(s, 8, "07 · OFDM BASELINE", "팀 통합에 사용할 기준 파라미터", "민영님 구현에서 가져온 값으로 채널 축과 차원을 고정");
    const values = [
      ["항목", "확정값", "채널 구현에서의 의미"],
      ["중심주파수", "11.7 GHz", "도플러 및 위상 계산"],
      ["FFT 크기", "256", "전체 부반송파 격자"],
      ["부반송파 간격", "120 kHz", "정규화 CFO와 주파수축"],
      ["활성 부반송파", "223", "H[m,k]의 frequency 차원"],
      ["샘플링률", "30.72 MHz", "Ts = 32.552 ns"],
      ["OFDM 심벌", "8.333 μs", "CP 없이 FFT 구간 기준"],
      ["Pilot 간격", "16", "15 pilots · 208 data"],
      ["변조", "QPSK", "기본 링크 성능 실험"],
    ];
    const table = s.tables.add({ rows: values.length, columns: 3, left: 41, top: 174, width: 1198, height: 459, values, columnWidths: [260, 260, 678] });
    table.borders.assign({ style: "solid", fill: C.gray200, width: 1 });
    table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 3 }).assign({
      fill: C.blueSoft,
      textStyle: { typeface: FONT, fontSize: 16, bold: true, color: C.ink },
      margins: { top: 8, right: 12, bottom: 8, left: 12 },
      anchor: "middle",
    });
    table.cells.block({ row: 1, column: 0, rowCount: 8, columnCount: 3 }).assign({
      textStyle: { typeface: FONT, fontSize: 15, color: C.gray700 },
      margins: { top: 7, right: 12, bottom: 7, left: 12 },
      anchor: "middle",
    });
    for (let r = 1; r < values.length; r += 2) {
      table.cells.block({ row: r, column: 0, rowCount: 1, columnCount: 3 }).fill = C.gray50;
    }
    addNotes(s, ["configs/ofdm_baseline.yaml", "docs/team_integration_contract.md"]);
  }

  // 09 — Codex Grid 17/18: time-resolution chain.
  {
    const s = p.slides.add();
    addBase(s, 9, "08 · TIME RESOLUTION", "1초 궤도 샘플을 μs 채널에 연결하는 방법", "위성을 1초 동안 정지시키지 않고 위치와 속도를 연속적으로 보간");
    const steps = [
      [52, "①", "SGP4 원본", "1 s", "위치 rᵢ와 속도 vᵢ"],
      [350, "②", "Cubic Hermite", "continuous", "두 상태 사이를 위치·속도로 보간"],
      [648, "③", "채널 상태", "1 ms", "거리·도플러·복소 이득 갱신"],
      [946, "④", "OFDM 평가", "8.333 μs", "FFT 창 중심에서 H[m,k] 계산"],
    ];
    for (const [x, n, title, scale, body] of steps) {
      rect(s, { left: x, top: 210, width: 246, height: 315 }, C.white, "rounded-2xl", C.gray200);
      rect(s, { left: x + 20, top: 230, width: 44, height: 44 }, C.blueSoft, "rounded-full", "none");
      textbox(s, n, { left: x + 20, top: 239, width: 44, height: 28 }, { fontSize: 17, bold: true, color: C.blue, alignment: "center" });
      textbox(s, title, { left: x + 20, top: 298, width: 206, height: 38 }, { fontSize: 22, bold: true });
      textbox(s, scale, { left: x + 20, top: 356, width: 206, height: 45 }, { fontSize: 30, bold: true, color: C.blue });
      textbox(s, body, { left: x + 20, top: 427, width: 206, height: 72 }, { fontSize: 15, color: C.muted });
    }
    for (const x of [311, 609, 907]) {
      textbox(s, "→", { left: x, top: 338, width: 32, height: 44 }, { fontSize: 30, bold: true, color: C.faint, alignment: "center" });
    }
    rect(s, { left: 204, top: 572, width: 872, height: 61 }, C.greenSoft, "rounded-xl", "none");
    textbox(s, "검증: Hermite 위치 차분 속도 ≈ 제공 속도 · 중복/역순 시각, NaN/Inf, 단위 오류는 입력 단계에서 차단", { left: 230, top: 591, width: 820, height: 28 }, { fontSize: 15, bold: true, color: C.green, alignment: "center" });
    addNotes(s, ["src/starlink_downlink/interpolation.py", "tests/test_interpolation.py", "configs/ofdm_baseline.yaml"]);
  }

  // 10 — Codex Grid 08: H grid visual.
  {
    const s = p.slides.add();
    addBase(s, 10, "09 · CHANNEL GRID", "복소 SISO 채널 H[m,k] 생성", "가로축 time, 세로축 frequency인 2차원 채널 격자");
    await addImage(s, `${ROOT}/outputs/channel_grid/channel_grid_heatmap.png`, { left: 43, top: 174, width: 702, height: 458 }, "시간과 주파수에 따른 채널 크기 히트맵");
    label(s, "GRID SHAPE", 787, 190, 132, "blue");
    textbox(s, "256 × 223", { left: 787, top: 245, width: 404, height: 58 }, { fontSize: 43, bold: true, color: C.ink });
    textbox(s, "time samples × active subcarriers", { left: 787, top: 308, width: 404, height: 28 }, { fontSize: 15, color: C.muted });
    addBulletList(s, [
      "짧은 프레임: 약 2.125 ms",
      "주파수축 변화는 작아 거의 평탄",
      "시간축 변화는 위성 운동에서 발생",
      "magnitude와 phase를 함께 보존",
    ], { left: 790, top: 380, width: 395 }, { fontSize: 17, gap: 57, dotColor: C.green });
    textbox(s, "색은 |H[m,k]| [dB]이며, 복소 위상 정보는 NPZ/CSV 값에 별도 저장", { left: 63, top: 642, width: 666, height: 24 }, { fontSize: 11, color: C.faint, alignment: "center" });
    addNotes(s, ["outputs/channel_grid/channel_grid_heatmap.png", "outputs/channel_grid/channel_grid.csv", "src/starlink_downlink/channel_grid.py"]);
  }

  // 11 — Codex Grid 08 mirrored: full pass evolution.
  {
    const s = p.slides.add();
    addBase(s, 11, "10 · TWO TIME SCALES", "짧은 프레임과 전체 패스를 구분", "ms 프레임에서는 변화가 작고, 505.9초 전체 패스에서는 거리 변화가 뚜렷");
    addBulletList(s, [
      "단일 OFDM 프레임: quasi-static 검증",
      "전체 패스: 경로손실과 위상 진화 관찰",
      "1 ms channel state를 전체 패스에 생성",
      "큰 2D CSV 대신 상태 중심 저장",
    ], { left: 54, top: 215, width: 472 }, { fontSize: 19, gap: 75 });
    rect(s, { left: 55, top: 536, width: 472, height: 84 }, C.orangeSoft, "rounded-xl", "none");
    textbox(s, "해석 포인트", { left: 75, top: 553, width: 120, height: 22 }, { fontSize: 12, bold: true, color: C.orange });
    textbox(s, "주파수 선택성보다 시간 선택성이 먼저 드러나는 단일 경로 채널", { left: 75, top: 581, width: 424, height: 30 }, { fontSize: 15, bold: true, color: C.gray700 });
    await addImage(s, `${ROOT}/outputs/channel_events/magnitude_evolution.png`, { left: 576, top: 177, width: 650, height: 452 }, "전체 패스에서 시간에 따른 채널 크기 변화");
    textbox(s, "이상적인 단일 경로 모델이므로 주파수별 magnitude 차이는 거의 없고, 시간에 따라 공통 크기가 변함", { left: 601, top: 640, width: 600, height: 25 }, { fontSize: 11, color: C.faint, alignment: "center" });
    addNotes(s, ["outputs/channel_events/magnitude_evolution.png", "src/starlink_downlink/channel_events.py", "docs/team_integration_contract.md"]);
  }

  // 12 — Codex Grid 08: compensation image split.
  {
    const s = p.slides.add();
    addBase(s, 12, "11 · RECEIVER VIEW", "도플러 보상은 ‘잔류 CFO’ 문제로 연결된다", "raw 채널과 보상 채널을 모두 보존하여 알고리즘 비교가 가능");
    await addImage(s, `${ROOT}/outputs/channel_blocks/block_start_compensation.png`, { left: 42, top: 175, width: 678, height: 452 }, "블록 시작 기준 도플러 보상 전후 비교");
    label(s, "BLOCK MODEL", 770, 191, 132, "orange");
    textbox(s, "블록 시작에서 추정한 CFO를\n블록 내부에 연속 위상으로 적용", { left: 770, top: 247, width: 422, height: 90 }, { fontSize: 24, bold: true });
    addBulletList(s, [
      "채널 위상은 블록 경계에서 끊기지 않음",
      "예측 오차를 residual CFO로 변환",
      "향후 BER–CFO 실험의 설계 기준 제공",
    ], { left: 774, top: 385, width: 404 }, { fontSize: 17, gap: 64, dotColor: C.orange });
    textbox(s, "다음 연구: 목표 BER을 만족하는 잔류 CFO 허용치를 도플러 예측 속도 오차로 환산", { left: 772, top: 579, width: 410, height: 54 }, { fontSize: 15, bold: true, color: C.blue });
    addNotes(s, ["outputs/channel_blocks/block_start_compensation.png", "src/starlink_downlink/channel_blocks.py", "Pollet et al., DOI: 10.1109/26.380034"]);
  }

  // 13 — Codex Grid 18: three delivery cards.
  {
    const s = p.slides.add();
    addBase(s, 13, "12 · DELIVERY CONTRACT", "다른 모듈에 넘기는 산출물", "가독성용 CSV와 대규모 계산용 NPZ/메모리 경로를 역할별로 분리");
    addCard(s, 41, 190, 366, 402, "STATE", "channel_state.csv", "시간별 거리·지연·range rate·Doppler·이득과 지상국 좌표, 단위, raw/compensated 정의를 기록", "blue");
    addCard(s, 457, 190, 366, 402, "SHORT FRAME", "channel_grid.csv", "필요한 짧은 OFDM 프레임의 time × frequency 복소 H를 사람이 열어 확인하고 팀원이 직접 입력", "orange");
    addCard(s, 873, 190, 366, 402, "FULL PASS", "NPZ / memory / blocks", "전체 패스는 거대한 CSV를 만들지 않고 압축 배열 또는 블록 생성기로 처리하여 저장·메모리 비용 제어", "green");
    textbox(s, "모든 인터페이스에 좌표·시간 기준·단위·보상 상태·shape 정보를 메타데이터로 고정", { left: 177, top: 620, width: 926, height: 28 }, { fontSize: 16, bold: true, color: C.green, alignment: "center" });
    addNotes(s, ["docs/team_integration_contract.md", "src/starlink_downlink/channel_grid.py", "tests/test_channel_grid.py"]);
  }

  // 14 — Codex Grid 26: closure.
  {
    const s = p.slides.add();
    s.background.fill = C.ink;
    textbox(s, "CURRENT STATUS", { left: 41, top: 42, width: 280, height: 24 }, { fontSize: 12, bold: true, color: "#7EB3FF" });
    textbox(s, "채널 파트는\n결합 준비가 완료됐다", { left: 41, top: 142, width: 815, height: 176 }, { fontSize: 57, bold: true, color: C.white, lineSpacing: 0.98 });
    textbox(s, "궤도·기하·지연·도플러·경로손실·보간·H[m,k]·파일 계약·회귀 검증까지 독립 실행 가능", { left: 44, top: 344, width: 855, height: 70 }, { fontSize: 22, color: "#CDD5E1" });
    const next = [
      [44, "01", "팀 결합", "민영님 OFDM 프레임에 H[m,k] 적용"],
      [444, "02", "성능 실험", "잔류 CFO별 BER·EVM·ICI 평가"],
      [844, "03", "연구 확장", "빔포밍·다중경로·채널 추정 추가"],
    ];
    for (const [x, n, title, body] of next) {
      rect(s, { left: x, top: 492, width: 352, height: 142 }, "#182235", "rounded-2xl", "#334155");
      textbox(s, n, { left: x + 18, top: 511, width: 42, height: 26 }, { fontSize: 13, bold: true, color: "#7EB3FF" });
      textbox(s, title, { left: x + 18, top: 548, width: 310, height: 31 }, { fontSize: 20, bold: true, color: C.white });
      textbox(s, body, { left: x + 18, top: 587, width: 316, height: 37 }, { fontSize: 13, color: "#AEB9C8" });
    }
    textbox(s, "STARLINK‑5285 · NORAD 55296 · SKKU Natural Sciences Campus", { left: 43, top: 679, width: 650, height: 18 }, { fontSize: 10, color: "#778295" });
    addNotes(s, ["README.md", "전체 테스트 스위트", "Pollet et al., DOI: 10.1109/26.380034"]);
  }

  for (const [index, slide] of p.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    const png = await p.export({ slide, format: "png", scale: 1 });
    await writeBlob(`${OUT_DIR}/${stem}.png`, png);
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(`${OUT_DIR}/${stem}.layout.json`, await layout.text(), "utf8");
  }

  const montage = await p.export({ format: "webp", montage: true, scale: 0.5 });
  await writeBlob(`${OUT_DIR}/deck-montage.webp`, montage);
  const pptx = await PresentationFile.exportPptx(p);
  await pptx.save(OUT_PPTX);
  return { presentation: p, outputPath: OUT_PPTX, qaDir: OUT_DIR, slideCount: p.slides.items.length };
}
