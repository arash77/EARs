"""Run with: python -m pytest ear_bot/tests (needs pyyaml, requests, PyGithub, pytz)."""

import json
import os
import sys
from xml.sax.saxutils import escape

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ear_bot_reviewer  # noqa: E402
import pre_review as pr_mod  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OLD_PDF = os.path.join(
    ROOT, "Assembly_Reports/Absolonia_gigantea/qlAbsGiga1/qlAbsGiga1_EAR.pdf"
)

REPORT = {
    "version": "v26.10.21",
    "tags": "ERGA-BGE",
    "species": {"TxID": "9785", "ToLID": "mEleMax1", "Species": "Elephas maximus"},
    "flags": [],
    "curation_notes": "Removed 3 contaminants",
    "hic_temp_links": {"hap1": "https://example.org/a.pretext", "hap2": "NA"},
    "kmer_spectra": [{"plot": "k.png", "caption": "x"}],
    "fcs_gx": {"hap1": "0", "hap2": "NA"},
    "blobplots": {"hap1": "blob.png", "hap2": "blob2.png"},
    "data_profile": ["HiFi: 30x", "Hi-C: NA"],
    "pipeline": "Hifiasm",
}
PR = {"Species": "elephas  Maximus", "Project": "ERGA-BGE", "ToLID": "mEleMax2"}


def rows_by_name(report, pr):
    return {
        name: (level, detail)
        for level, name, detail in pr_mod.pre_review(
            report, pr, link_check=lambda url: (pr_mod.OK, "file found")
        )
    }


def test_checks():
    rows = rows_by_name(REPORT, PR)
    assert rows["Species"][0] == pr_mod.OK  # capitals and spaces ignored
    assert rows["ToLID"] == (pr_mod.WARNING, "PR: `mEleMax2`, PDF: `mEleMax1`")
    assert rows["Project"][0] == pr_mod.OK
    assert rows["PretextView link hap1"] == (pr_mod.OK, "file found")
    assert rows["PretextView link hap2"] == (pr_mod.WARNING, "NA")
    assert (
        rows["FCS-GX hap2"][0] == pr_mod.WARNING and rows["FCS-GX hap1"][0] == pr_mod.OK
    )
    assert rows["Coverage"] == (pr_mod.WARNING, "NA for `Hi-C`")
    assert (
        rows["K-mer spectra"][0]
        == rows["Pipelines"][0]
        == rows["Curation notes"][0]
        == pr_mod.OK
    )
    assert rows["make_EAR flags"] == (pr_mod.OK, "0")


def test_fail_and_missing():
    report = dict(
        REPORT,
        species={"ToLID": "mEleMax1", "Species": "Loxodonta africana"},
        tags="ERGA-Community",
        curation_notes="NA",
        kmer_spectra="NA",
        data_profile="NA",
        hic_temp_links={},
        flags=["Observed Haploid Number is different from Expected"],
    )
    rows = rows_by_name(report, PR)
    assert rows["Species"][0] == pr_mod.FAIL
    assert rows["Project"][0] == pr_mod.WARNING
    for name in (
        "Curation notes",
        "K-mer spectra",
        "Coverage",
        "PretextView link",
        "make_EAR flags",
    ):
        assert rows[name][0] == pr_mod.WARNING, name
    comment = pr_mod.format_comment(
        pr_mod.pre_review(report, PR, lambda u: (pr_mod.OK, "")), "v26.10.21"
    )
    assert "**8 warnings, 1 fails.**" in comment and "Please fix" in comment


def test_pdf_text_cannot_mention_people():
    rows = rows_by_name(
        dict(REPORT, species={"Species": "@someone `x`", "ToLID": "a|b"}), PR
    )
    assert rows["Species"][1].endswith("PDF: `@someone 'x'`")


def fake_pdf(tmp_path, report, report_id=None):
    data = {
        "format": pr_mod.ear_data.EAR_DATA_FORMAT,
        "date": "2026-11-03 10:00:00 CET",
        "report_id": report_id or pr_mod.ear_data.report_id_of(report),
        "report": report,
    }
    xmp = (
        f'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        f'<rdf:Description xmlns:ear="{pr_mod.ear_data.EAR_XMP_NS}"><ear:data>{escape(json.dumps(data))}</ear:data>'
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    path = tmp_path / "mEleMax1_EAR.pdf"
    path.write_bytes(b"%PDF-1.4\n" + xmp.encode() + b"\n%%EOF\n")
    return path


def test_reading_the_pdf(tmp_path):
    assert pr_mod.ear_data.load(fake_pdf(tmp_path, REPORT))["report"] == REPORT
    with pytest.raises(pr_mod.ear_data.ConvertError):
        pr_mod.ear_data.load(fake_pdf(tmp_path, REPORT, report_id="00000000"))
    with pytest.raises(pr_mod.ear_data.ConvertError, match="no EAR data"):
        pr_mod.ear_data.load(OLD_PDF)


def test_yaml_new_script_with_review_info(tmp_path, monkeypatch):
    committed = {}
    monkeypatch.setattr(
        ear_bot_reviewer,
        "commit",
        lambda repo, path, msg, content: committed.update({path: content}),
    )
    bot = object.__new__(ear_bot_reviewer.EARBotReviewer)
    bot.repo = None
    bot._add_yaml_file(
        str(fake_pdf(tmp_path, REPORT)), review_info={"Reviewer": "Jane Doe"}
    )
    (content,) = committed.values()
    assert "ERGA Assembly Report: v26.10.21" in content
    assert content.endswith("EAR review:\n  Reviewer: Jane Doe\n")


def test_yaml_old_pdf_falls_back_to_old_script(tmp_path, monkeypatch):
    committed = {}
    monkeypatch.setattr(
        ear_bot_reviewer,
        "commit",
        lambda repo, path, msg, content: committed.update({path: content}),
    )
    bot = object.__new__(ear_bot_reviewer.EARBotReviewer)
    bot.repo = None
    pdf = tmp_path / "qlAbsGiga1_EAR.pdf"
    pdf.write_bytes(open(OLD_PDF, "rb").read())
    bot._add_yaml_file(str(pdf))
    (content,) = committed.values()
    assert "Absolonia gigantea" in content and "EAR review" not in content


def test_broken_link_fails():
    rows = {
        n: lv
        for lv, n, _ in pr_mod.pre_review(
            REPORT, PR, link_check=lambda url: pr_mod.check_link("link")
        )
    }
    assert rows["PretextView link hap1"] == pr_mod.FAIL


def test_old_prs_keep_the_old_system(monkeypatch):
    from datetime import datetime, timezone

    old = type("PR", (), {"created_at": datetime(2026, 11, 1, tzinfo=timezone.utc)})()
    new = type("PR", (), {"created_at": datetime(2026, 12, 2, tzinfo=timezone.utc)})()
    assert not ear_bot_reviewer.is_new_system(new)  # not released yet
    monkeypatch.setattr(
        ear_bot_reviewer, "NEW_SYSTEM_FROM", datetime(2026, 12, 1, tzinfo=timezone.utc)
    )
    assert not ear_bot_reviewer.is_new_system(old) and ear_bot_reviewer.is_new_system(
        new
    )
    bot = object.__new__(ear_bot_reviewer.EARBotReviewer)
    monday = datetime(2026, 12, 7, 9, tzinfo=timezone.utc)
    assert bot._deadline(monday, new) == datetime(
        2026, 12, 10, 9, tzinfo=timezone.utc
    )  # 3 working days
    assert bot._deadline(monday, old) == datetime(
        2026, 12, 11, 13, tzinfo=timezone.utc
    )  # 100 working hours
