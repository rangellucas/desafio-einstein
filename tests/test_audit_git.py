import pytest

from scripts.audit_git import findings
from scripts import audit_git


@pytest.mark.parametrize("path,content,rule", [
    ("data/private.json", b"{}", "private_artifact_path"),
    ("docs/input.PDF", b"x", "private_artifact_path"),
    ("innocent.txt", b"%PDF-1.7", "pdf_content"),
    (".env", b"", "private_artifact_path"),
    ("config.py", b"-----BEGIN " + b"PRIVATE KEY-----", "private_key"),
    ("config.py", b"sk-" + b"A" * 30, "provider_token"),
    ("config.py", b"https://" + b"name:password@example.test", "credential_url"),
    (".env.example", b"LLM_API_KEY=unexpected_literal", "credential_assignment_requires_review"),
])
def test_audit_only_reports_rule_identifiers(path, content, rule):
    assert rule in findings(path, content)
    assert all(value not in content.decode(errors="replace") for value in findings(path, content))


def test_synthetic_and_environment_examples_are_not_credentials():
    assert findings(".env.example", b'LLM_API_KEY=\nAPI_ACCESS_TOKEN=$PRIVATE_TOKEN\nQDRANT_API_KEY=synthetic-token') == []


def test_url_exception_is_exact_and_limited_to_reviewed_fixture():
    url = b"https://" + b"user:password@gateway.test"
    assert findings("tests/test_gateway_config.py", url) == []
    assert findings("app/config.py", url) == ["credential_url"]
    assert findings("tests/test_gateway_config.py", url + b" https://" + b"other:value@elsewhere.test") == ["credential_url"]


def test_removed_historical_pdf_is_reported_without_content(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_git, "ROOT", tmp_path)
    replies = {
        ("rev-list", "--all", "--reflog"): b"commit1\n",
        ("ls-tree", "-r", "-z", "commit1"): b"100644 blob object1\tdeleted.pdf\0",
        ("cat-file", "blob", "object1"): b"%PDF-1.7 PRIVATE SYNTHETIC CONTENT",
        ("ls-files", "--stage", "-z"): b"",
        ("ls-files", "--cached", "--others", "--exclude-standard", "-z"): b"",
    }
    monkeypatch.setattr(audit_git, "git", lambda *args: replies[args])
    report = audit_git.audit()
    assert report["status"] == "findings"
    assert report["findings"] == [{"scope": "history", "object": "object1", "path": "deleted.pdf", "rules": ["pdf_content", "private_artifact_path"]}]
    assert "PRIVATE SYNTHETIC CONTENT" not in str(report)


def test_git_error_is_not_printed(monkeypatch, capsys):
    def fail():
        raise RuntimeError("PRIVATE DETAIL")
    monkeypatch.setattr(audit_git, "audit", fail)
    assert audit_git.main() == 1
    assert "PRIVATE" not in capsys.readouterr().out
