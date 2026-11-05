"""Tests for main CLI subcommand routing."""

import sys
from unittest.mock import MagicMock, patch
import pytest
from src.main import _print_root_help, main


def test_print_root_help(capsys):
    ret = _print_root_help()
    assert ret == 0
    captured = capsys.readouterr()
    assert "audit" in captured.out
    assert "setup" in captured.out
    assert "activity" in captured.out
    assert "runners" in captured.out
    assert "upgrade" in captured.out


def test_main_bare_invocation(capsys):
    with patch.object(sys, "argv", ["repo360"]):
        ret = main()
        assert ret == 0
        captured = capsys.readouterr()
        assert "repo360 <command>" in captured.out


def test_main_help_flag(capsys):
    with patch.object(sys, "argv", ["repo360", "--help"]):
        ret = main()
        assert ret == 0
        captured = capsys.readouterr()
        assert "repo360 <command>" in captured.out


def test_main_route_activity():
    with patch.object(sys, "argv", ["repo360", "activity", "--help"]):
        with patch("src.activity.cli.run_activity_cli", return_value=0) as mock_act:
            ret = main()
            assert ret == 0
            assert mock_act.called


def test_main_route_runners():
    with patch.object(sys, "argv", ["repo360", "runners", "--help"]):
        with patch("src.runners.cli.run_runners_cli", return_value=0) as mock_run:
            ret = main()
            assert ret == 0
            assert mock_run.called


def test_main_route_finops():
    with patch.object(sys, "argv", ["repo360", "finops", "--help"]):
        with patch("src.finops.cli.run_finops_cli", return_value=0) as mock_fin:
            ret = main()
            assert ret == 0
            assert mock_fin.called


def test_main_route_dora():
    with patch.object(sys, "argv", ["repo360", "dora", "--help"]):
        with patch("src.dora.cli.run_dora_cli", return_value=0) as mock_dor:
            ret = main()
            assert ret == 0
            assert mock_dor.called


def test_main_route_bypass():
    with patch.object(sys, "argv", ["repo360", "bypass", "--help"]):
        with patch("src.bypass.cli.run_bypass_cli", return_value=0) as mock_byp:
            ret = main()
            assert ret == 0
            assert mock_byp.called


def test_main_route_upgrade():
    with patch.object(sys, "argv", ["repo360", "upgrade", "--dry-run"]):
        with patch("src.upgrade.run_upgrade_cli", return_value=0) as mock_up:
            ret = main()
            assert ret == 0
            assert mock_up.called

    with patch.object(sys, "argv", ["repo360", "update", "--dry-run"]):
        with patch("src.upgrade.run_upgrade_cli", return_value=0) as mock_up:
            ret = main()
            assert ret == 0
            assert mock_up.called


def test_main_unknown_command(capsys):
    with patch.object(sys, "argv", ["repo360", "nonexistent"]):
        ret = main()
        assert ret == 1
        captured = capsys.readouterr()
        assert "Unknown command" in captured.out
