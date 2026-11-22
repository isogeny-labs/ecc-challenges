from __future__ import annotations

import io
import json
import stat
import sys

import pytest

from ecc_challenges import cli


def write_key(tmp_path, value="ecc1_test_key"):
    path = tmp_path / "api-key"
    path.write_text(value + "\n")
    return str(path)


def test_missing_key_fails_with_a_login_hint(tmp_path, capsys):
    code = cli.main(["--key-file", str(tmp_path / "missing"), "whoami"])
    assert code == 1
    assert "ecc login" in capsys.readouterr().err


def test_login_stores_a_private_key_and_checks_it(monkeypatch, tmp_path, capsys):
    path = tmp_path / "nested" / "api-key"
    calls = {}

    def fake_request(args, method, request_path, payload=None, *, key=None):
        calls["request"] = (method, request_path, key)
        return {"account": {"login": "alice"}}

    monkeypatch.setattr(cli, "request", fake_request)
    monkeypatch.setattr(sys, "stdin", io.StringIO(" ecc1_abc123 \n"))
    code = cli.main(["--key-file", str(path), "login"])

    assert code == 0
    assert path.read_text().strip() == "ecc1_abc123"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert calls["request"] == ("GET", "/v1/account", "ecc1_abc123")
    assert "Signed in as alice" in capsys.readouterr().out


def test_whoami_summarises_the_account(monkeypatch, tmp_path, capsys):
    key_file = write_key(tmp_path)

    def fake_request(args, method, path, payload=None, *, key=None):
        assert (method, path, key) == ("GET", "/v1/account", "ecc1_test_key")
        return {"account": {"login": "alice", "leaderboard_visible": False},
                "keys": [{"revoked_at": None}, {"revoked_at": None}, {"revoked_at": "x"}],
                "runs": {"active_runs": 1, "total_runs": 3, "points": 1200}}

    monkeypatch.setattr(cli, "request", fake_request)
    assert cli.main(["--key-file", key_file, "whoami"]) == 0
    out = capsys.readouterr().out
    assert "login: alice" in out
    assert "leaderboard: not listed" in out
    assert "keys: 3 (2 not revoked)" in out
    assert "runs: 1 active, 3 total; 1,200 points" in out


def test_json_flag_prints_the_server_response(monkeypatch, tmp_path, capsys):
    key_file = write_key(tmp_path)
    response = {"account": {"login": "alice", "leaderboard_visible": True},
                "keys": [], "runs": {"active_runs": 0, "total_runs": 0, "points": 0}}
    monkeypatch.setattr(cli, "request",
                        lambda *args, **kwargs: response)
    assert cli.main(["--key-file", key_file, "--json", "whoami"]) == 0
    assert json.loads(capsys.readouterr().out) == response


def test_keys_create_prints_the_secret_once(monkeypatch, tmp_path, capsys):
    key_file = write_key(tmp_path)
    calls = {}

    def fake_request(args, method, path, payload=None, *, key=None):
        calls["call"] = (method, path, payload)
        return {"key": "ecc1_new_secret"}

    monkeypatch.setattr(cli, "request", fake_request)
    assert cli.main(["--key-file", key_file, "keys", "create", "--label", "rig"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "ecc1_new_secret"
    assert "shown once" in captured.err
    assert calls["call"] == ("POST", "/v1/account/keys", {"label": "rig"})


def test_leaderboard_show_and_hide(monkeypatch, tmp_path, capsys):
    key_file = write_key(tmp_path)
    calls = []

    def fake_request(args, method, path, payload=None, *, key=None):
        calls.append((method, path, payload))
        return {"leaderboard_visible": True}

    monkeypatch.setattr(cli, "request", fake_request)
    assert cli.main(["--key-file", key_file, "leaderboard", "show"]) == 0
    assert calls[-1] == ("POST", "/v1/account/leaderboard", {"visible": True})
    assert "now listed" in capsys.readouterr().out

    assert cli.main(["--key-file", key_file, "leaderboard", "hide"]) == 0
    assert calls[-1] == ("POST", "/v1/account/leaderboard", {"visible": False})
    assert "no longer listed" in capsys.readouterr().out


def test_close_uses_the_protocol_two_route(monkeypatch, tmp_path, capsys):
    key_file = write_key(tmp_path)
    calls = []

    def fake_request(args, method, path, payload=None, *, key=None):
        calls.append((method, path))
        return {"closed_at": "2026-11-01T12:00:00+00:00"}

    monkeypatch.setattr(cli, "request", fake_request)
    assert cli.main(["--key-file", key_file, "close", "abc"]) == 0
    assert calls[-1] == ("POST", "/v2/runs/abc/close")
    assert "2026-11-01 12:00 UTC" in capsys.readouterr().out


def test_server_errors_are_reported_without_a_traceback(monkeypatch, tmp_path, capsys):
    key_file = write_key(tmp_path)

    def fake_request(*args, **kwargs):
        raise cli.CliError("API key rejected; run 'ecc login' with a current key")

    monkeypatch.setattr(cli, "request", fake_request)
    assert cli.main(["--key-file", key_file, "whoami"]) == 1
    assert "ecc: API key rejected" in capsys.readouterr().err


def test_error_messages_name_the_next_step():
    assert "ecc login" in cli._error_message(401, b'{"error":"invalid API key"}', {})
    assert "retry in 15s" in cli._error_message(
        429, b'{"error":"rate limit"}', {"Retry-After": "15"})
    assert cli._error_message(500, b"not json", {}) == "HTTP 500"


def test_a_command_is_required():
    with pytest.raises(SystemExit):
        cli.main([])
