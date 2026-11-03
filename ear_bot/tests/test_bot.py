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


# --- roster bookkeeping -------------------------------------------------------
from rev import get_EAR_reviewer  # noqa: E402


def test_roster_round_trips_byte_for_byte():
    text = open(os.path.join(ROOT, "rev/reviewers_list.csv"), encoding="utf-8").read()
    fieldnames = text.split("\n", 1)[0].split(",")
    assert get_EAR_reviewer.format_csv(get_EAR_reviewer.parse_csv(text), fieldnames) == text


def test_quoted_comma_keeps_its_columns():
    text = 'Github ID,Full Name,Institution\njdoe,"Doe, Jane",IZW\n'
    rows = get_EAR_reviewer.parse_csv(text)
    assert rows == [{"Github ID": "jdoe", "Full Name": "Doe, Jane", "Institution": "IZW"}]
    assert get_EAR_reviewer.format_csv(rows, ["Github ID", "Full Name", "Institution"]) == text


def test_posted_table_names_the_reviewer_asked(monkeypatch):
    text = open(os.path.join(ROOT, "rev/reviewers_list.csv"), encoding="utf-8").read()
    picker = object.__new__(ear_bot_reviewer.EAR_get_reviewer)
    picker.data = get_EAR_reviewer.parse_csv(text)
    for _ in range(20):  # random tie-breaks must not split the two
        reviewer, table = picker.get_reviewer("IZW", "ERGA-BGE")
        assert f"({reviewer})" in table.split("Selected reviewer:")[1].split("\n")[0]


class _Repo:
    def __init__(self, files):
        self.files = files

    def get_contents(self, path):
        return type("C", (), {"decoded_content": self.files[path].encode(), "path": path, "sha": "x"})()


def test_merge_rerun_is_not_recorded_twice(monkeypatch):
    log = "PR,Species\nhttps://github.com/x/1,Elephas maximus\n"
    committed = []
    monkeypatch.setattr(ear_bot_reviewer, "commit", lambda repo, path, msg, content: committed.append(content))
    picker = object.__new__(ear_bot_reviewer.EAR_get_reviewer)
    picker.repo = _Repo({"rev/EAR_reviews.csv": log})
    fields = dict(species="S, s", tag="T", requester_name="R", requester_affiliation="A", reviewer_name="V",
                  reviewer_affiliation="B", supervisor_name="U", supervisor_affiliation="C", interaction_count=1,
                  open_date="d", approval_date="e", other_participants="", notes="N/A")
    assert picker.add_pr(pr_url="https://github.com/x/1", **fields) is False and not committed
    assert picker.add_pr(pr_url="https://github.com/x/2", **fields) is True
    assert committed[0].endswith('https://github.com/x/2,"S, s",T,R,A,V,B,U,C,1,d,e,,N/A\n')


def test_ear_update_prs_get_activity_check_but_no_reviewer(monkeypatch):
    checked = []
    bot = object.__new__(ear_bot_reviewer.EARBotReviewer)
    bot.valid_projects = ["ERGA-BGE"]
    monkeypatch.setattr(bot, "_check_pr_activity", lambda pr, now: checked.append(pr.number), raising=False)

    def pr(number, *labels):
        return type("PR", (), {"number": number, "get_labels": lambda self: [type("L", (), {"name": n})() for n in labels]})()

    # No assignee lookups, review requests or asks happen for these: they would raise on the fake PR.
    bot.find_reviewer([pr(1, "EAR-UPDATE"), pr(2, "ERROR!"), pr(3), pr(4, "dependencies")])
    assert checked == [1, 2]
