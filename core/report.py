"""
=============================================================================
EduGen - Student Performance PDF Report Generator (core/report.py)
=============================================================================
Generates a comprehensive, professional student progress report in PDF format:
  - Header: Student identity, email, generation timestamp
  - Executive Summary: Accuracy %, questions answered, quizzes taken, learning stage
  - Concept Mastery Breakdown: Grouped by curriculum module
  - Weakest Concepts & Misconceptions: Plain-English diagnosis and remedy
  - Study Plan Progression: Goals, completed steps, next recommended action
  - Recent Quiz History: Table of last 10 quizzes
  - Fully formatted with ReportLab; zero technical jargon in student-facing prose.
=============================================================================
"""

import io
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.concepts import CONCEPTS, concept_title, module_of
from core.db import get_db
from core.db_repo import get_active_study_plan, get_student_journey, get_study_plan_steps
from core.misconceptions import MISCONCEPTIONS


MODULE_NAMES = {
    "classes-objects": "Module 1: Classes & Object Basics",
    "methods-encapsulation": "Module 2: Methods & Encapsulation",
    "inheritance-polymorphism": "Module 3: Inheritance & Polymorphism",
    "abstract-interfaces": "Module 4: Abstract Classes & Interfaces",
    "core-java-apis": "Module 5: Core Java Fundamentals",
    "collections": "Module 6: Collections & Data Structures",
    "exceptions": "Module 7: Exception Handling",
    "io-concurrency": "Module 8: Object Structure & Advanced OOP",
}


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and print total page count."""

    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_footer(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_footer(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        # Top footer border line
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(36, 32, self._pagesize[0] - 36, 32)
        # Footer text
        self.drawString(36, 20, "EduGen Learning System  |  Student Performance Report")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(self._pagesize[0] - 36, 20, page_str)
        self.restoreState()


def generate_student_report_pdf(student_id):
    """
    Generate a complete performance report for the given student_id.
    Returns bytes of the generated PDF file.
    """
    conn = get_db()
    cur = conn.cursor()

    # 1. Student identity
    stud_row = cur.execute(
        """SELECT s.id AS student_id, u.name, u.email
           FROM students s
           JOIN users u ON s.user_id = u.id
           WHERE s.id = ?""",
        (student_id,),
    ).fetchone()

    if not stud_row:
        conn.close()
        raise ValueError(f"Student #{student_id} not found")

    student_name = stud_row["name"]
    student_email = stud_row["email"]

    # 2. Overall Quiz Metrics
    totals = cur.execute(
        """SELECT COUNT(*), SUM(score), SUM(total_questions)
           FROM quiz_results WHERE student_id = ?""",
        (student_id,),
    ).fetchone()
    total_quizzes = totals[0] or 0
    total_correct = totals[1] or 0
    total_questions = totals[2] or 0
    accuracy_pct = round(100.0 * total_correct / total_questions, 1) if total_questions else 0.0

    # 3. Concept Mastery Records
    mastery_rows = cur.execute(
        """SELECT concept, mastery, attempts, correct, trend
           FROM concept_mastery WHERE student_id = ?
           ORDER BY mastery ASC""",
        (student_id,),
    ).fetchall()
    mastery_map = {r["concept"]: r for r in mastery_rows}

    # 4. Top Misconceptions
    misconception_rows = cur.execute(
        """SELECT qa.misconception_id, COUNT(*) as cnt
           FROM question_attempts qa
           JOIN quiz_results qr ON qa.quiz_result_id = qr.id
           WHERE qr.student_id = ? AND qa.misconception_id IS NOT NULL AND qa.misconception_id != ''
           GROUP BY qa.misconception_id
           ORDER BY cnt DESC LIMIT 5""",
        (student_id,),
    ).fetchall()

    # 5. Last 10 Quizzes
    recent_quizzes = cur.execute(
        """SELECT id, concept, difficulty, score, total_questions, timestamp, source
           FROM quiz_results WHERE student_id = ?
           ORDER BY timestamp DESC, id DESC LIMIT 10""",
        (student_id,),
    ).fetchall()

    conn.close()

    # 6. Active Study Plan & Journey
    active_plan = get_active_study_plan(student_id)
    plan_steps = get_study_plan_steps(active_plan["id"]) if active_plan else []
    journey = get_student_journey(student_id) or {}

    # Build the PDF document
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=45,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0F172A"),
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#475569"),
    )
    h2_style = ParagraphStyle(
        "SectionH2",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1E293B"),
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "DocBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#334155"),
    )
    body_bold = ParagraphStyle(
        "DocBodyBold",
        parent=body_style,
        fontName="Helvetica-Bold",
    )
    table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#1E293B"),
    )
    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        parent=table_cell,
        fontName="Helvetica-Bold",
    )
    table_head = ParagraphStyle(
        "TableHead",
        parent=table_cell,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#475569"),
    )

    story = []

    # ── Header ───────────────────────────────────────────────
    story.append(Paragraph("EduGen Student Performance Report", title_style))
    gen_time_str = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    header_info = f"<b>Student:</b> {student_name} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Email:</b> {student_email} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Generated:</b> {gen_time_str}"
    story.append(Spacer(1, 4))
    story.append(Paragraph(header_info, subtitle_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=12))

    # ── Executive Summary ────────────────────────────────────
    story.append(Paragraph("Executive Summary", h2_style))
    stage_text = "Standard Practice"
    if active_plan:
        done_cnt = sum(1 for s in plan_steps if s.get("status") == "done")
        stage_text = f"Active Study Plan ({done_cnt}/{len(plan_steps)} Steps Completed)"

    summary_data = [
        [
            Paragraph("Overall Accuracy", table_head),
            Paragraph("Questions Attempted", table_head),
            Paragraph("Quizzes Completed", table_head),
            Paragraph("Learning Stage", table_head),
        ],
        [
            Paragraph(f"<font size=14 color='#1F4FE0'><b>{accuracy_pct}%</b></font>", table_cell),
            Paragraph(f"<font size=14><b>{total_questions}</b></font> ({total_correct} correct)", table_cell),
            Paragraph(f"<font size=14><b>{total_quizzes}</b></font>", table_cell),
            Paragraph(f"<b>{stage_text}</b>", table_cell),
        ],
    ]
    summary_table = Table(summary_data, colWidths=[120, 130, 110, 180])
    summary_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#E2E8F0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    story.append(summary_table)
    story.append(Spacer(1, 12))

    # ── Active Study Plan ────────────────────────────────────
    if active_plan:
        story.append(Paragraph("Study Plan Progression", h2_style))
        next_action_desc = "Continue current syllabus progression"
        act = journey.get("next_action") or {}
        if act.get("type") == "take_quiz":
            k = act.get("quiz", {}).get("kind", "practice")
            next_action_desc = f"Take scheduled assessment ({k.capitalize()})"
        elif act.get("type") == "read_lesson":
            next_action_desc = f"Review lesson material for {concept_title(act.get('concept', ''))}"
        elif act.get("type") == "course_complete":
            next_action_desc = "Study plan requirements complete"

        plan_desc = f"<b>Objective:</b> {active_plan.get('title', 'Java OOP Foundations')} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Next Recommended Action:</b> {next_action_desc}"
        story.append(Paragraph(plan_desc, body_style))
        story.append(Spacer(1, 6))

        step_rows = [[
            Paragraph("#", table_head),
            Paragraph("Topic", table_head),
            Paragraph("Category", table_head),
            Paragraph("Status", table_head),
        ]]
        for st in plan_steps:
            st_status = st.get("status", "pending")
            status_color = "#16A34A" if st_status == "done" else ("#D97706" if st_status == "in_progress" else "#64748B")
            status_label = "Completed" if st_status == "done" else ("In Progress" if st_status == "in_progress" else "Pending")
            step_rows.append([
                Paragraph(str(st.get("position", "")), table_cell),
                Paragraph(st.get("title") or concept_title(st.get("concept", "")), table_cell_bold),
                Paragraph((st.get("kind") or "Lesson").capitalize(), table_cell),
                Paragraph(f"<font color='{status_color}'><b>{status_label}</b></font>", table_cell),
            ])

        steps_table = Table(step_rows, colWidths=[30, 260, 120, 130])
        steps_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ])
        )
        story.append(steps_table)
        story.append(Spacer(1, 12))

    # ── Weakest Concepts & Misconceptions ────────────────────
    story.append(Paragraph("Key Focus Areas & Detected Misconceptions", h2_style))
    if misconception_rows:
        misc_data = [[
            Paragraph("Concept", table_head),
            Paragraph("Observed Misconception", table_head),
            Paragraph("Targeted Clarification", table_head),
        ]]
        for mid, _ in misconception_rows:
            m_item = MISCONCEPTIONS.get(mid, {})
            c_tag = m_item.get("concept") or (mid.split("/")[0] if "/" in mid else mid)
            title = m_item.get("title") or mid
            wrong = m_item.get("wrong_belief") or "Common conceptual confusion on this topic."
            correct = m_item.get("correct_idea") or "Review official language specifications."

            misc_data.append([
                Paragraph(concept_title(c_tag), table_cell_bold),
                Paragraph(f"<b>{title}</b><br/>{wrong}", table_cell),
                Paragraph(correct, table_cell),
            ])

        misc_table = Table(misc_data, colWidths=[130, 200, 210])
        misc_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FEE2E2")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#FECACA")),
            ])
        )
        story.append(misc_table)
    else:
        story.append(Paragraph("No persistent conceptual misconceptions recorded.", body_style))
    story.append(Spacer(1, 12))

    # ── Concept Mastery by Module ────────────────────────────
    story.append(Paragraph("Curriculum Mastery Breakdown", h2_style))
    # Group attempted concepts by module
    attempted_by_mod = {}
    for c_tag, rec in mastery_map.items():
        m_slug = module_of(c_tag)
        attempted_by_mod.setdefault(m_slug, []).append(rec)

    if attempted_by_mod:
        mod_table_data = [[
            Paragraph("Module / Concept", table_head),
            Paragraph("Mastery", table_head),
            Paragraph("Attempts", table_head),
            Paragraph("Proficiency Status", table_head),
        ]]
        for m_slug, records in sorted(attempted_by_mod.items()):
            m_title = MODULE_NAMES.get(m_slug, m_slug.replace("-", " ").title())
            mod_table_data.append([
                Paragraph(f"<b>{m_title}</b>", table_cell_bold),
                Paragraph("", table_cell),
                Paragraph("", table_cell),
                Paragraph("", table_cell),
            ])
            for r in records:
                m_score = round(float(r["mastery"]), 1)
                if m_score >= 70.0:
                    status_str = "<font color='#16A34A'><b>Mastered</b></font>"
                elif m_score >= 50.0:
                    status_str = "<font color='#D97706'><b>In Progress</b></font>"
                else:
                    status_str = "<font color='#DC2626'><b>Needs Review</b></font>"

                mod_table_data.append([
                    Paragraph(f"&nbsp;&nbsp;&bull;&nbsp;{concept_title(r['concept'])}", table_cell),
                    Paragraph(f"{m_score}%", table_cell),
                    Paragraph(str(r["attempts"]), table_cell),
                    Paragraph(status_str, table_cell),
                ])

        mastery_table = Table(mod_table_data, colWidths=[240, 80, 80, 140])
        mastery_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ])
        )
        story.append(mastery_table)
    else:
        story.append(Paragraph("No concept assessments attempted yet.", body_style))
    story.append(Spacer(1, 12))

    # ── Recent Assessment History ────────────────────────────
    story.append(Paragraph("Recent Assessment History", h2_style))
    if recent_quizzes:
        history_data = [[
            Paragraph("Date", table_head),
            Paragraph("Topic", table_head),
            Paragraph("Difficulty", table_head),
            Paragraph("Score", table_head),
            Paragraph("Result", table_head),
        ]]
        for q in recent_quizzes:
            q_date = str(q["timestamp"])[:10]
            q_score = q["score"]
            q_tot = q["total_questions"]
            q_pct = round(100.0 * q_score / q_tot, 1) if q_tot else 0.0
            res_color = "#16A34A" if q_pct >= 70.0 else ("#D97706" if q_pct >= 50.0 else "#DC2626")

            history_data.append([
                Paragraph(q_date, table_cell),
                Paragraph(concept_title(q["concept"] or "Diagnostic Assessment"), table_cell),
                Paragraph((q["difficulty"] or "Medium").capitalize(), table_cell),
                Paragraph(f"{q_score}/{q_tot}", table_cell),
                Paragraph(f"<font color='{res_color}'><b>{q_pct}%</b></font>", table_cell),
            ])

        hist_table = Table(history_data, colWidths=[80, 240, 80, 70, 70])
        hist_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ])
        )
        story.append(hist_table)
    else:
        story.append(Paragraph("No assessment history recorded.", body_style))

    # Build the document with our custom NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
