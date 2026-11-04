"""Unit tests for Repo360 upgrade module."""

import sys
from unittest.mock import MagicMock, patch
import pytest

from src.upgrade import (
    build_upgrade_command,
    check_remote_status,
    detect_installer,
    execute_upgrade,
    run_upgrade_cli,
    verify_local_state,
)


def test_detect_installer_pipx():
    with patch.object(sys, "prefix", "C:\\Users\\test\\AppData\\Local\\pipx\\venvs\\repo360"):
        with patch("src.upgrade.find_pipx_executable", return_value="C:\\bin\\pipx.exe"):
            installer, cmd = detect_installer()
            assert installer == "pipx"
            assert cmd == ["C:\\bin\\pipx.exe", "runpip", "repo360", "install", "--upgrade"]


def test_detect_installer_pip_fallback():
    with patch.object(sys, "prefix", "C:\\Python312"):
        installer, cmd = detect_installer()
        assert installer == "pip"
        assert cmd == [sys.executable, "-m", "pip", "install", "--upgrade"]


def test_build_upgrade_command():
    installer, cmd = build_upgrade_command(
        repo_url="https://github.com/Adithya-Meda/repo360.git",
        installer_override="pip",
    )
    assert installer == "pip"
    assert "git+https://github.com/Adithya-Meda/repo360.git" in cmd

    installer, cmd = build_upgrade_command(
        repo_url="https://github.com/Adithya-Meda/repo360.git",
        installer_override="pipx",
    )
    assert installer == "pipx"
    assert "git+https://github.com/Adithya-Meda/repo360.git" in cmd


def test_execute_upgrade_dry_run(capsys):
    ret = execute_upgrade([("pipx", ["pipx", "runpip", "repo360", "install", "--upgrade", "pkg"])], dry_run=True)
    assert ret == 0
    captured = capsys.readouterr()
    assert "[DRY-RUN]" in captured.out


def test_execute_upgrade_subprocess_success():
    mock_res = MagicMock()
    mock_res.returncode = 0
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        ret = execute_upgrade([("pip", ["pip", "install", "pkg"])], dry_run=False)
        assert ret == 0
        assert mock_run.called


def test_check_remote_status():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "sha": "abcdef123456",
        "commit": {
            "committer": {"date": "2026-11-04T12:00:00Z"},
            "message": "feat: release v1.1.0\n\nFull changelog",
        },
    }
    with patch("requests.get", return_value=mock_resp):
        ok, msg = check_remote_status("https://github.com/Adithya-Meda/repo360.git")
        assert ok is True
        assert "abcdef12" in msg
        assert "release v1.1.0" in msg


def test_run_upgrade_cli_dry_run(capsys):
    ret = run_upgrade_cli(["--dry-run"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "[DRY-RUN]" in captured.out
    assert "git+https://github.com/Adithya-Meda/repo360.git" in captured.out


def test_run_upgrade_cli_check(capsys):
    with patch("src.upgrade.check_remote_status", return_value=(True, "Latest version on main: 12345678")):
        ret = run_upgrade_cli(["--check"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "[PASS]" in captured.out
        assert "Latest version on main: 12345678" in captured.out


def test_verify_local_state(capsys, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{}", encoding="utf-8")
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "key.pem").write_text("dummy", encoding="utf-8")

    with patch("src.upgrade.get_credentials_path", return_value=str(config_file)):
        with patch("src.upgrade.get_secrets_dir", return_value=str(secrets_dir)):
            verify_local_state()
            captured = capsys.readouterr()
            assert "[VERIFY]" in captured.out
            assert "Configuration file" in captured.out
            assert "1 private key(s) detected" in captured.out
