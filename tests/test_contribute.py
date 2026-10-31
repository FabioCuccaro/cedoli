from urllib.parse import parse_qs, urlparse

from bp import contribute


def test_only_github_without_email(monkeypatch):
    monkeypatch.setattr(contribute, "EMAIL", "")
    assert set(contribute.links()) == {"issue"}


def test_prefilled_texts(monkeypatch):
    monkeypatch.setattr(contribute, "EMAIL", "formati@example.org")
    links = contribute.links()
    mail = urlparse(links["email"])
    assert mail.scheme == "mailto" and mail.path == "formati@example.org"
    q = parse_qs(mail.query)
    assert q["subject"] == [contribute.SUBJECT] and "struttura_anonima.json" in q["body"][0]
    issue = parse_qs(urlparse(links["issue"]).query)
    assert issue["template"] == ["nuovo-formato.md"] and issue["body"] == [contribute.ISSUE_BODY] and "trascina" in contribute.ISSUE_BODY
