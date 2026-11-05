import shutil

import docx
import pytest

from jobapplier.cv import CV, fit_to_pages


@pytest.fixture
def sample(tmp_path):
    d = docx.Document()
    d.add_paragraph("ALEX EXAMPLE")
    d.add_paragraph("alex@example.com")
    d.add_paragraph("PROFESSIONAL SUMMARY")
    d.add_paragraph("Data engineer with 5 years of experience.")
    d.add_paragraph("PROFESSIONAL EXPERIENCE")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Data Engineer | Acme - London", "2022 - Present"
    for b in ["Built ETL pipelines in Python", "Ran Snowflake models", "Wrote SQL reports"]:
        d.add_paragraph("•  " + b)
    d.add_paragraph("TECHNICAL SKILLS")
    p = d.add_paragraph()
    p.add_run("Data:").bold = True
    p.add_run(" Python, SQL, Snowflake")
    d.add_paragraph("AWARDS")
    d.add_paragraph("•  Best Intern 2019")
    path = tmp_path / "cv.docx"
    d.save(path)
    return path


def test_parse_and_edit(sample, tmp_path):
    cv = CV(sample)
    kinds = {b.id: b.kind for b in cv.blocks}
    assert kinds == {"S1": "summary", "B1": "bullet", "B2": "bullet", "B3": "bullet", "K1": "skills", "X1": "item"}
    assert cv.block("B1").role.startswith("Data Engineer | Acme")
    cv.set_block_text("B2", "Designed Snowflake data models")
    cv.set_block_text("K1", "Data: SQL, Python, Snowflake")
    cv.reorder_bullets(["B3", "B1"])
    assert cv.remove_block("X1")
    out = cv.save(tmp_path / "out.docx")
    text = CV(out).full_text()
    assert "•  Designed Snowflake data models" in text
    assert "Data: SQL, Python, Snowflake" in text
    assert text.index("Wrote SQL reports") < text.index("Built ETL pipelines")
    assert "AWARDS" not in text  # empty section heading removed too
    k = docx.Document(str(out)).paragraphs
    label = next(p for p in k if p.text.startswith("Data:"))
    assert label.runs[0].bold  # label formatting kept


def test_keeps_two_bullets_per_role(sample):
    cv = CV(sample)
    assert cv.remove_block("B1")
    assert not cv.remove_block("B2")


@pytest.mark.skipif(not (shutil.which("soffice") or shutil.which("libreoffice")), reason="LibreOffice not installed")
def test_fit_to_one_page(sample, tmp_path):
    cv = CV(sample)
    pdf, pages, dropped = fit_to_pages(cv, tmp_path / "fit.docx", 1, [])
    assert pdf.exists() and pages == 1 and dropped == []


def test_skills_label_split_across_runs(tmp_path):
    d = docx.Document()
    d.add_paragraph("TECHNICAL SKILLS")
    p = d.add_paragraph()
    for t in ["BI & ", "Visualisation", ": "]:
        p.add_run(t).bold = True
    p.add_run("Tableau, Excel")
    path = tmp_path / "cv.docx"
    d.save(path)
    cv = CV(path)
    cv.set_block_text("K1", "BI & Visualisation: Power BI, Tableau")
    runs = cv.block("K1").para.runs
    assert "".join(r.text for r in runs) == "BI & Visualisation: Power BI, Tableau"
    assert runs[-1].text == " Power BI, Tableau" and not runs[-1].bold
    assert all(r.bold for r in runs[:-1])
