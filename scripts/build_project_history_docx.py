"""Build the illustrated STARLINK-5285 project-history Word report."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "docs" / "STARLINK-5285_프로젝트_진행과정.docx"
FIGURES = {
    "orbit": ROOT / "outputs" / "sgp4_downlink" / "orbit_3d.png",
    "delay": ROOT / "outputs" / "sgp4_downlink" / "delay_doppler.png",
    "qpsk": ROOT / "outputs" / "qpsk_downlink" / "constellation.png",
    "grid": ROOT / "outputs" / "channel_grid" / "channel_grid_heatmap.png",
    "magnitude": (
        ROOT / "outputs" / "channel_events" / "magnitude_evolution.png"
    ),
    "compensation": (
        ROOT / "outputs" / "channel_blocks" / "block_start_compensation.png"
    ),
    "prediction": (
        ROOT
        / "outputs"
        / "channel_prediction_errors"
        / "prediction_error_residual_cfo.png"
    ),
}

BLUE = RGBColor(46, 116, 181)
DARK_BLUE = RGBColor(31, 77, 120)
INK = RGBColor(24, 39, 58)
MUTED = RGBColor(92, 103, 116)
LIGHT_BLUE = "E8EEF5"
LIGHT_GRAY = "F2F4F7"
CALLOUT = "F4F6F9"
GOLD = RGBColor(156, 113, 29)
TABLE_WIDTH_DXA = 9360
TABLE_INDENT_DXA = 120
CELL_MARGINS_DXA = {"top": 80, "bottom": 80, "start": 120, "end": 120}


def set_run_font(
    run,
    *,
    size: float | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    color: RGBColor | None = None,
) -> None:
    run.font.name = "Calibri"
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), "Calibri")
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), "Calibri")
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "맑은 고딕")
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color is not None:
        run.font.color.rgb = color


def set_cell_shading(cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = properties.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        properties.append(shading)
    shading.set(qn("w:fill"), fill)


def set_cell_margins(cell) -> None:
    properties = cell._tc.get_or_add_tcPr()
    margins = properties.find(qn("w:tcMar"))
    if margins is None:
        margins = OxmlElement("w:tcMar")
        properties.append(margins)
    for side, value in CELL_MARGINS_DXA.items():
        element = margins.find(qn(f"w:{side}"))
        if element is None:
            element = OxmlElement(f"w:{side}")
            margins.append(element)
        element.set(qn("w:w"), str(value))
        element.set(qn("w:type"), "dxa")


def set_repeat_table_header(row) -> None:
    properties = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    properties.append(header)


def set_fixed_table_geometry(table, widths_dxa: list[int]) -> None:
    if sum(widths_dxa) != TABLE_WIDTH_DXA:
        raise ValueError("table column widths must sum to 9360 DXA")
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False
    properties = table._tbl.tblPr
    width = properties.find(qn("w:tblW"))
    if width is None:
        width = OxmlElement("w:tblW")
        properties.append(width)
    width.set(qn("w:w"), str(TABLE_WIDTH_DXA))
    width.set(qn("w:type"), "dxa")
    indent = properties.find(qn("w:tblInd"))
    if indent is None:
        indent = OxmlElement("w:tblInd")
        properties.append(indent)
    indent.set(qn("w:w"), str(TABLE_INDENT_DXA))
    indent.set(qn("w:type"), "dxa")
    layout = properties.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        properties.append(layout)
    layout.set(qn("w:type"), "fixed")

    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width_dxa in widths_dxa:
        column = OxmlElement("w:gridCol")
        column.set(qn("w:w"), str(width_dxa))
        grid.append(column)

    for row in table.rows:
        for index, cell in enumerate(row.cells):
            cell.width = Inches(widths_dxa[index] / 1440)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            properties = cell._tc.get_or_add_tcPr()
            cell_width = properties.find(qn("w:tcW"))
            if cell_width is None:
                cell_width = OxmlElement("w:tcW")
                properties.append(cell_width)
            cell_width.set(qn("w:w"), str(widths_dxa[index]))
            cell_width.set(qn("w:type"), "dxa")
            set_cell_margins(cell)


def style_table(table, widths_dxa: list[int]) -> None:
    set_fixed_table_geometry(table, widths_dxa)
    set_repeat_table_header(table.rows[0])
    for row_index, row in enumerate(table.rows):
        for cell in row.cells:
            if row_index == 0:
                set_cell_shading(cell, LIGHT_BLUE)
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(2)
                paragraph.paragraph_format.line_spacing = 1.05
                for run in paragraph.runs:
                    set_run_font(
                        run,
                        size=9.2,
                        bold=(row_index == 0),
                        color=INK,
                    )


def add_table(doc, headers: list[str], rows: list[list[str]], widths: list[int]):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for index, value in enumerate(headers):
        table.rows[0].cells[index].text = value
    for values in rows:
        cells = table.add_row().cells
        for index, value in enumerate(values):
            cells[index].text = value
    style_table(table, widths)
    after = doc.add_paragraph()
    after.paragraph_format.space_after = Pt(2)
    return table


def add_body(doc, text: str, *, bold_lead: str | None = None) -> None:
    paragraph = doc.add_paragraph()
    if bold_lead and text.startswith(bold_lead):
        lead = paragraph.add_run(bold_lead)
        set_run_font(lead, bold=True, color=INK)
        run = paragraph.add_run(text[len(bold_lead) :])
        set_run_font(run, color=INK)
    else:
        run = paragraph.add_run(text)
        set_run_font(run, color=INK)


def add_bullet(doc, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.paragraph_format.left_indent = Inches(0.5)
    paragraph.paragraph_format.first_line_indent = Inches(-0.25)
    paragraph.paragraph_format.space_after = Pt(8)
    paragraph.paragraph_format.line_spacing = 1.167
    run = paragraph.add_run(text)
    set_run_font(run, color=INK)


def add_number(doc, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Number")
    paragraph.paragraph_format.left_indent = Inches(0.5)
    paragraph.paragraph_format.first_line_indent = Inches(-0.25)
    paragraph.paragraph_format.space_after = Pt(8)
    paragraph.paragraph_format.line_spacing = 1.167
    run = paragraph.add_run(text)
    set_run_font(run, color=INK)


def add_equation(doc, text: str) -> None:
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(5)
    paragraph.paragraph_format.space_after = Pt(8)
    run = paragraph.add_run(text)
    run.font.name = "Cambria Math"
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), "Cambria Math")
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), "Cambria Math")
    run.font.size = Pt(12)
    run.font.color.rgb = DARK_BLUE


def add_callout(doc, label: str, text: str) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.cell(0, 0)
    set_cell_shading(cell, CALLOUT)
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_before = Pt(2)
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.paragraph_format.line_spacing = 1.1
    label_run = paragraph.add_run(f"{label}  ")
    set_run_font(label_run, bold=True, color=DARK_BLUE)
    body_run = paragraph.add_run(text)
    set_run_font(body_run, color=INK)
    set_fixed_table_geometry(table, [TABLE_WIDTH_DXA])
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def add_figure(doc, key: str, caption: str, *, width: float = 6.1) -> None:
    path = FIGURES[key]
    if not path.is_file():
        raise FileNotFoundError(path)
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    run.add_picture(str(path), width=Inches(width))
    caption_paragraph = doc.add_paragraph(style="Caption")
    caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption_paragraph.paragraph_format.space_before = Pt(3)
    caption_paragraph.paragraph_format.space_after = Pt(8)
    caption_run = caption_paragraph.add_run(caption)
    set_run_font(caption_run, size=9, italic=True, color=MUTED)


def add_page_number(paragraph) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    value = OxmlElement("w:t")
    value.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instruction, separate, value, end])
    set_run_font(run, size=9, color=MUTED)


def configure_styles(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
    normal.font.size = Pt(11)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.10

    heading_tokens = {
        "Heading 1": (16, BLUE, 16, 8),
        "Heading 2": (13, BLUE, 12, 6),
        "Heading 3": (12, DARK_BLUE, 8, 4),
    }
    for name, (size, color, before, after) in heading_tokens.items():
        style = doc.styles[name]
        style.font.name = "Calibri"
        style._element.rPr.rFonts.set(qn("w:ascii"), "Calibri")
        style._element.rPr.rFonts.set(qn("w:hAnsi"), "Calibri")
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = color
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    caption = doc.styles["Caption"]
    caption.font.name = "Calibri"
    caption._element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
    caption.font.size = Pt(9)
    caption.font.italic = True
    caption.font.color.rgb = MUTED


def configure_page(doc: Document) -> None:
    for section in doc.sections:
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.top_margin = Inches(1)
        section.right_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.header_distance = Inches(0.492)
        section.footer_distance = Inches(0.492)

        header = section.header
        header.is_linked_to_previous = False
        paragraph = header.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_after = Pt(0)
        run = paragraph.add_run("STARLINK-5285 DOWNLINK CHANNEL RESEARCH")
        set_run_font(run, size=8.5, bold=True, color=MUTED)

        footer = section.footer
        footer.is_linked_to_previous = False
        paragraph = footer.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        paragraph.paragraph_format.space_after = Pt(0)
        prefix = paragraph.add_run("Project history  |  ")
        set_run_font(prefix, size=9, color=MUTED)
        add_page_number(paragraph)


def page_break(doc: Document) -> None:
    doc.add_page_break()


def build_document() -> Path:
    doc = Document()
    configure_styles(doc)
    configure_page(doc)
    doc.core_properties.title = "STARLINK-5285 Downlink Channel Project History"
    doc.core_properties.subject = "Development process and team integration"
    doc.core_properties.author = "최민준"
    doc.core_properties.keywords = (
        "STARLINK-5285, SGP4, OFDM, Doppler, channel grid, H[m,k]"
    )

    # Editorial cover (named header-pattern choice) on the business-brief preset.
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(118)
    kicker = doc.add_paragraph()
    kicker.alignment = WD_ALIGN_PARAGRAPH.CENTER
    kicker.paragraph_format.space_after = Pt(18)
    set_run_font(
        kicker.add_run("RESEARCH DEVELOPMENT REPORT"),
        size=11,
        bold=True,
        color=GOLD,
    )
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(10)
    set_run_font(
        title.add_run("STARLINK-5285 Downlink\n채널 프로젝트 진행 과정"),
        size=30,
        bold=True,
        color=DARK_BLUE,
    )
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_after = Pt(72)
    set_run_font(
        subtitle.add_run(
            "이상적 궤도 모델에서 실제 SGP4 기반 OFDM 채널 H[m,k]까지"
        ),
        size=14,
        color=BLUE,
    )
    author = doc.add_paragraph()
    author.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(author.add_run("최민준  |  URP 연구 프로젝트"), size=11.5, bold=True)
    issued = doc.add_paragraph()
    issued.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(issued.add_run(date.today().isoformat()), size=10.5, color=MUTED)

    page_break(doc)
    doc.add_heading("요약", level=1)
    add_callout(
        doc,
        "핵심 결과",
        "CelesTrak 궤도 정보와 지상국 좌표로부터 위치·속도·거리·지연·"
        "Doppler를 계산하고, 이를 팀 OFDM 송수신기가 사용할 수 있는 복소 "
        "SISO 채널 H[m,k]로 변환하는 채널 파이프라인을 완성했다.",
    )
    add_body(
        doc,
        "프로젝트는 이상적인 원궤도와 천정 통과 가정에서 시작했다. 이후 "
        "STARLINK-5285(NORAD 55296)의 CelesTrak OMM을 SGP4로 전파하고, "
        "TEME 상태를 ECEF로 변환해 성균관대학교 자연과학캠퍼스 지상국과의 "
        "실제 가시 패스를 계산했다. 마지막에는 1초 궤도 상태를 cubic Hermite로 "
        "재표본화하고, 120 kHz OFDM numerology에 맞춘 H[m,k]를 생성했다.",
    )
    doc.add_heading("연구 질문", level=2)
    add_number(doc, "움직이는 LEO 위성과 고정 지상국 사이의 기하와 Doppler를 어떻게 계산할 것인가?")
    add_number(doc, "서로 다른 시간 해상도의 궤도 상태와 OFDM 심벌 시간을 어떻게 연결할 것인가?")
    add_number(doc, "계산한 물리 상태를 복소 채널 H[m,k]로 어떻게 표현하고 팀 모듈에 전달할 것인가?")
    add_number(doc, "raw Doppler와 보상 후 residual CFO를 어떻게 분리해 연구할 것인가?")
    doc.add_heading("문서 구성", level=2)
    add_body(
        doc,
        "1~3장은 모델의 출발점과 실제 궤도로의 전환을, 4~7장은 신호·채널·"
        "OFDM grid 구현을, 8~10장은 실험·인터페이스·검증을 설명한다. 마지막 "
        "장에서는 현재 완성 범위와 팀 결합 이후의 연구 과제를 정리한다.",
    )

    page_break(doc)
    doc.add_heading("1. 프로젝트 범위와 초기 물리 가정", level=1)
    add_table(
        doc,
        ["항목", "초기 설정 또는 의미"],
        [
            ["연구 대상", "STARLINK-5285, NORAD 55296"],
            ["링크 방향", "위성에서 지상국으로 향하는 downlink"],
            ["지상국", "성균관대학교 자연과학캠퍼스, 37.2934° N / 126.9747° E"],
            ["초기 이상 모델", "고도 572 km, 원궤도, t=0 천정 통과"],
            ["가시 기준", "최소 앙각 10°"],
            ["개발 규칙", "Miniconda 환경, 모든 의미 있는 변경을 Git으로 기록"],
        ],
        [2700, 6660],
    )
    add_body(
        doc,
        "초기 분석에서는 고도 572 km, 궤도주기 5,766.6초, 궤도속도 약 "
        "7.57 km/s를 사용했다. 경사거리는 약 572~2,761 km, 전파 지연은 "
        "약 1.91~9.21 ms, 최대 시선방향 상대속도는 약 6.95 km/s로 예상했다.",
    )
    add_equation(doc, "τ(t) = R(t) / c     |     f_D(t) = -v_r(t) f_c / c")
    add_callout(
        doc,
        "초기 결론",
        "Doppler에 의한 주파수 이동과 거리에 따른 수신전력 감소는 별개의 "
        "현상이다. 또한 절대 전파 지연은 다중경로 지연 확산이나 cyclic prefix의 "
        "보상 대상과 구분해야 한다.",
    )

    doc.add_heading("2. 이상적 모델을 단계적으로 구현", level=1)
    add_table(
        doc,
        ["단계", "구현 내용", "확인한 결과"],
        [
            ["1", "이상적 궤도·좌표계 정의", "위성과 지상국을 각각 위치·속도벡터로 표현"],
            ["2", "Downlink 기하", "거리, 지심각, 방위각, 앙각, 가시구간"],
            ["3", "지연·range rate·Doppler", "최근접점에서 Doppler 0 및 부호 반전"],
            ["4", "링크 버짓", "FSPL, 수신전력, 열잡음, SNR"],
            ["5", "CLI·CSV·JSON·그래프", "수치 결과와 시각화의 재현 가능성"],
            ["6", "이벤트 표본 정밀화", "가시 경계·최근접점을 시간축에 정확히 포함"],
        ],
        [900, 3500, 4960],
    )
    add_body(
        doc,
        "처음에는 궤도 경사각과 지상국 위도만으로 시간별 위치를 결정할 수 "
        "있는지 검토했다. 그러나 절대 궤도 방향과 epoch가 없으므로, 이상 모델은 "
        "t=0에서 위성이 지상국 천정에 있도록 놓고 위성 공전과 지구 자전을 각각 "
        "계산하는 방식으로 정의했다.",
    )

    page_break(doc)
    doc.add_heading("3. CelesTrak OMM과 SGP4 실제 궤도로 전환", level=1)
    add_body(
        doc,
        "이상 모델의 수식과 산출물을 보존한 채 실제 궤도 전파 경로를 추가했다. "
        "CelesTrak OMM을 SGP4에 입력해 TEME 위치·속도를 얻고, Vallado GMST "
        "회전과 지구 자전 속도 보정을 적용해 ECEF 상태로 변환했다. 지상국은 "
        "WGS-84 geodetic 좌표로 구성했다.",
    )
    add_equation(doc, "OMM → SGP4(TEME) → TEME-to-ECEF → LOS geometry → delay/Doppler")
    add_figure(
        doc,
        "orbit",
        "그림 1. SGP4 한 궤도 기준선, 분석 구간, 10° 이상 가시구간과 SKKU 지상국",
        width=5.7,
    )

    page_break(doc)
    doc.add_heading("4. 실제 패스 이벤트와 핵심 물리 결과", level=1)
    add_table(
        doc,
        ["지표", "선택 패스 결과"],
        [
            ["가시 시작", "2026-07-29 07:42:36.760675 UTC"],
            ["최대 앙각", "85.164879° at 07:46:50.801258 UTC"],
            ["최근접점", "579.705 km at 07:46:50.953295 UTC"],
            ["가시 종료", "2026-07-29 07:51:02.674438 UTC"],
            ["가시시간", "505.914 s"],
            ["최대 절대 Doppler", "223.102 kHz at 10 GHz"],
            ["지연 범위", "1.934~6.298 ms"],
        ],
        [3100, 6260],
    )
    add_body(
        doc,
        "거리 최소 시각과 앙각 최대 시각은 약 0.152초 차이가 났다. 두 이벤트를 "
        "독립 최적화해 필드의 물리적 의미를 바로잡았고, 최소 앙각 경계에는 매우 "
        "작은 허용오차를 적용해 시작·종료 행을 모두 visible로 포함했다.",
    )
    add_figure(
        doc,
        "delay",
        "그림 2. 실제 패스의 전파 지연, range rate 및 10 GHz Doppler 변화",
        width=5.85,
    )

    page_break(doc)
    doc.add_heading("5. 신호 기준선에서 파형 독립 채널로", level=1)
    add_body(
        doc,
        "기하 모델 이후에는 QPSK·AWGN 기준선을 추가해 BER, EVM, 성상도, "
        "Doppler의 영향을 확인했다. 이어 파일럿 기반 주파수·위상 추정을 도입했지만, "
        "최종 책임 경계는 특정 파형에 종속되지 않는 SISO 채널로 다시 정리했다.",
    )
    add_figure(
        doc,
        "qpsk",
        "그림 3. QPSK 수신 성상도: AWGN과 시간변화 Doppler의 예비 영향 확인",
        width=6.15,
    )
    doc.add_heading("복소 채널 표현", level=2)
    add_equation(doc, "H[m,k] = a[m,k] exp(jφ_D[m]) exp(-j2π f_k τ[m])")
    add_body(
        doc,
        "a[m,k]는 FSPL과 기타 손실에 의한 전압 이득, φ_D[m]는 누적 Doppler "
        "위상, f_k는 baseband 부반송파 주파수, τ[m]는 절대 전파 지연이다. "
        "OFDM 결합부에서는 Y_active[m,k] = H[m,k]X_active[m,k]로 사용한다.",
    )
    add_callout(
        doc,
        "모델 경계",
        "현재 H[m,k]는 LOS SISO 채널이며 다중경로, MIMO·빔포밍, 위상 잡음, "
        "안테나 추적 오차와 실제 Starlink 독점 파형은 포함하지 않는다.",
    )

    page_break(doc)
    doc.add_heading("6. 팀 OFDM baseline과 시간·주파수 축 확정", level=1)
    add_table(
        doc,
        ["항목", "팀 통합 baseline v1"],
        [
            ["대표 반송파", "11.7 GHz Ku-band downlink 연구 시나리오"],
            ["FFT / 활성 부반송파", "256 / 223"],
            ["부반송파 간격", "120 kHz"],
            ["CP", "0 samples"],
            ["샘플레이트 / 샘플주기", "30.72 MHz / 약 32.552 ns"],
            ["OFDM 심벌시간", "약 8.333 μs"],
            ["파일럿", "frequency comb, 활성 열 기준 간격 16, 15개"],
            ["데이터 열", "208개"],
            ["채널 평가 시각", "유효 FFT 구간 중앙"],
            ["H 배열", "complex128, (symbol_count, 223), time × frequency"],
        ],
        [3150, 6210],
    )
    add_body(
        doc,
        "활성 signed index는 -112…-1과 1…111이고 DC와 guard는 제외한다. "
        "민영 님의 fftshift 배열에 정확히 연결할 수 있도록 자연 FFT bin과 "
        "fftshift bin mapping을 모두 제공했다.",
    )
    add_equation(doc, "f_s = N_FFT Δf = 30.72 MHz     |     B_occ ≈ 223×120 kHz = 26.76 MHz")

    doc.add_heading("서로 다른 시간 해상도를 연결", level=2)
    add_body(
        doc,
        "SGP4 원본 상태는 1초 간격이지만 채널은 1초 동안 고정되지 않는다. "
        "위치와 속도를 함께 사용하는 cubic Hermite 보간으로 필요한 1 ms 상태와 "
        "각 8.333 μs OFDM 심벌 중앙 시각의 상태를 직접 계산한다.",
    )
    add_equation(
        doc,
        "r(t)=h₀₀(s)r₀+h₁₀(s)Δt v₀+h₀₁(s)r₁+h₁₁(s)Δt v₁",
    )

    page_break(doc)
    doc.add_heading("7. 복소 SISO 채널 grid H[m,k]", level=1)
    add_body(
        doc,
        "기본 프레임은 256×223 복소 배열이며 x축은 심벌 시간, y축은 활성 "
        "부반송파 주파수다. 가장 가까운 패스 이벤트를 중심으로 약 2.125 ms를 "
        "평가한다. 짧은 구간에서는 거리 기반 magnitude가 거의 일정해 보이지만 "
        "절대 지연으로 인한 주파수축 위상 기울기와 Doppler 위상은 존재한다.",
    )
    add_figure(
        doc,
        "grid",
        "그림 4. 최근접점 주변 256×223 raw SISO 채널의 magnitude와 wrapped phase",
        width=6.2,
    )

    page_break(doc)
    doc.add_heading("8. 전체 패스와 블록 규모를 분리해 분석", level=1)
    add_body(
        doc,
        "2.125 ms 프레임에서는 FSPL 변화가 매우 작아 시간축 색상 변화가 거의 "
        "보이지 않는다. 따라서 전체 약 506초 가시 패스는 별도의 관측 축으로 "
        "분리해 거리 기반 magnitude 변화를 확인했다.",
    )
    add_figure(
        doc,
        "magnitude",
        "그림 5. 전체 가시 패스의 LOS 채널 magnitude envelope",
        width=6.2,
    )
    add_callout(
        doc,
        "해석 주의",
        "전체 패스 0.1초 축은 느린 envelope를 보여주기 위한 관측 표본이다. "
        "OFDM 심벌 간격이나 실제 H[m,k] 시간축을 0.1초로 바꾼 것이 아니다.",
    )

    page_break(doc)
    doc.add_heading("9. Doppler 보상과 예측 오차 연구", level=1)
    add_body(
        doc,
        "raw 채널, 매 심벌 truth를 제거한 perfect 보상 채널, 블록 시작 시점의 "
        "지연·Doppler만 고정해 사용하는 채널을 분리했다. 보상 후 residual CFO는 "
        "truth에서 prediction을 뺀 값으로 통일했다.",
    )
    add_equation(doc, "f_residual = f_truth - f_prediction")
    add_figure(
        doc,
        "compensation",
        "그림 6. 블록 시작 상태 고정 보상에서 남는 delay·CFO·phase 오차",
        width=6.2,
    )
    add_body(
        doc,
        "1 ms, 256심벌, 5 ms, 10 ms 블록을 비교했고, 위치·속도·시각·"
        "Doppler 예측 bias를 sweep해 residual CFO와 위상 오차로 변환했다. "
        "이 결과는 이후 OFDM BER·EVM·ICI 실험의 residual CFO 입력 기준이 된다.",
    )

    page_break(doc)
    doc.add_heading("10. 인터페이스, 파일 저장 및 입력 검증", level=1)
    add_table(
        doc,
        ["전달 대상", "권장 형식", "한 행 또는 배열의 의미"],
        [
            ["전체 패스 물리 상태", "channel_state.csv", "한 시각의 위치·속도·LOS·거리·지연·Doppler"],
            ["짧은 OFDM 프레임", "channel_grid.csv", "한 (m,k) 셀의 h_real·h_imag와 축 정보"],
            ["Python 모듈 간 정밀 교환", "channel_grid.npz", "H[m,k]와 시간·주파수 배열"],
            ["동일 프로세스", "메모리 배열", "grid.channel_response를 직접 전달"],
            ["긴 통신", "블록 처리", "필요한 짧은 H grid를 순차 생성·적용"],
        ],
        [2600, 2100, 4660],
    )
    add_body(
        doc,
        "채널 자체는 CSV가 아니라 복소 배열 H[m,k]다. CSV와 NPZ는 저장·"
        "교환 형식이다. 전체 패스를 long-format H CSV로 펼치지 않으며, "
        "channel_grid.csv는 1,000,000셀 이하의 짧은 프레임으로 제한했다.",
    )
    doc.add_heading("외부 상태 입력의 회귀 검증", level=2)
    for item in (
        "지상국 WGS-84 위도·경도·고도를 필수 입력으로 받고 결과 메타데이터에 기록",
        "raw, perfectly compensated, block-start compensated 채널을 파일 내부에서 명시",
        "위치 차분 속도와 제공 속도의 구간 평균을 비교",
        "중복·역순 UTC, NaN/Inf, 단위 선언 오류와 비현실적 규모를 거부",
        "TEME와 ECEF 입력을 구분하고 이미 ECEF인 속도를 다시 회전하지 않음",
    ):
        add_bullet(doc, item)

    page_break(doc)
    doc.add_heading("11. 팀 책임 경계와 현재 완성 범위", level=1)
    add_table(
        doc,
        ["채널 담당: 최민준", "OFDM 담당: 민영", "후속 공동 연구"],
        [
            ["궤도·좌표 변환·LOS", "비트/QPSK 매핑", "Y[m,k]=H[m,k]X[m,k] 결합"],
            ["거리·지연·range rate·Doppler", "FFT/IFFT·활성 bin 배치", "BER·EVM·ICI 측정"],
            ["FSPL·경로 이득·H[m,k]", "파일럿·등화·판정", "잔류 CFO 허용 기준"],
            ["raw/보상 채널·필터·인터페이스", "OFDM 파형 정규화", "파일럿 기반 추정 및 보상"],
        ],
        [3120, 3120, 3120],
    )
    add_callout(
        doc,
        "현재 상태",
        "움직이는 위성 정보를 위치·속도벡터로 만들고 fixed UE와의 downlink "
        "채널 H[m,k]를 제공하는 최민준 파트는 팀 결합 전 기준으로 완료됐다.",
    )
    doc.add_heading("검증과 재현성", level=2)
    add_body(
        doc,
        "고정 OMM, Git commit, 환경 버전, 설정 파일, 난수 seed와 산출물 hash를 "
        "manifest에 기록한다. 최신 구현은 main과 origin/main에 동기화됐고, "
        "전체 회귀 테스트 237개가 통과했다.",
    )
    add_table(
        doc,
        ["항목", "현재 값"],
        [
            ["Git commit", "e4fb4c4 - compact full-pass channel storage"],
            ["팀 설정", "configs/ofdm_baseline.yaml / team_integration_v1"],
            ["회귀 테스트", "237 passed"],
            ["현재 채널", "LOS SISO, raw 및 명시적 보상 변형"],
        ],
        [2800, 6560],
    )

    doc.add_heading("12. 결합 이후의 연구 계획", level=1)
    add_number(doc, "민영 님의 OFDM 송수신기에 frequency_mapping.csv 기준으로 223개 H 열을 연결한다.")
    add_number(doc, "AWGN 기준선에서 CFO=0의 QPSK-OFDM BER을 먼저 검증한다.")
    add_number(doc, "상수 normalized CFO와 실제 f_D(t), 보상 후 residual CFO를 순차 적용한다.")
    add_number(doc, "BER-SNR, BER-CFO, EVM, ICI와 성상도를 비교해 허용 residual CFO를 도출한다.")
    add_number(doc, "파일럿 기반 CFO·채널 추정의 LS 기준선을 구현하고 필요 시 보간법을 비교한다.")
    add_number(doc, "최종적으로 안테나 축을 추가해 MIMO·빔포밍 채널로 확장한다.")
    add_callout(
        doc,
        "연구의 다음 질문",
        "이 OFDM numerology에서 목표 BER을 만족하려면 위성 Doppler를 어느 "
        "정확도까지 예측·추적해야 하는가? 이 질문이 채널 모델과 통신 성능 실험을 "
        "연결하는 핵심 연구 문제다.",
    )

    doc.add_heading("참고 자료", level=1)
    add_body(doc, "CelesTrak GP data: https://celestrak.org/")
    add_body(
        doc,
        "Pollet et al., ‘BER Sensitivity of OFDM Systems to Carrier Frequency "
        "Offset and Wiener Phase Noise,’ IEEE Transactions on Communications, "
        "doi:10.1109/26.380034.",
    )
    add_body(
        doc,
        "프로젝트 내부 기준: README.md, docs/team_integration_contract.md, "
        "configs/ofdm_baseline.yaml 및 outputs 아래의 고정 OMM 재현 산출물.",
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUTPUT_PATH)
    return OUTPUT_PATH


if __name__ == "__main__":
    print(build_document())
