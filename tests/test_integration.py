"""End-to-end integration tests for Repo360 CLI execution."""

import os
import sys
import tempfile
from unittest.mock import patch

from src.main import main, run_audit_cli


def test_bare_repo360_shows_help_without_executing_audit(capsys) -> None:
    """Verify that bare 'repo360' prints available commands and does NOT execute any audit."""
    with patch("sys.argv", ["repo360"]):
        with patch("src.main._run_cli") as mock_run:
            exit_code = main()
            assert exit_code == 0
            mock_run.assert_not_called()

    captured = capsys.readouterr()
    assert "Usage:" in captured.out
    assert "audit" in captured.out
    assert "setup" in captured.out


def test_unknown_subcommand_returns_error(capsys) -> None:
    """Verify that an invalid subcommand prints an error message and exits with code 1."""
    with patch("sys.argv", ["repo360", "invalid-cmd"]):
        with patch("src.main._run_cli") as mock_run:
            exit_code = main()
            assert exit_code == 1
            mock_run.assert_not_called()

    captured = capsys.readouterr()
    assert "Error: Unknown command 'invalid-cmd'" in captured.out


def test_main_mock_mode_execution() -> None:
    """Run full CLI execution in mock mode with custom override configs."""
    with tempfile.TemporaryDirectory() as temp_dir:
        custom_advisory = os.path.join(temp_dir, "custom_advisory.json")
        with open(custom_advisory, "w", encoding="utf-8") as f:
            f.write('{"enabled_checks": {"org_admin": {"rulesets_adoption": true}}}')

        test_args = [
            "repo360",
            "audit",
            "--advisory-config",
            custom_advisory,
            "--output-dir",
            temp_dir,
            "--mock-mode",
        ]

        with patch("sys.argv", test_args):
            exit_code = main()

        assert exit_code == 0

        # Verify output files exist
        files = os.listdir(temp_dir)
        assert any(f.endswith(".xlsx") for f in files)
        assert any(f.endswith(".csv") for f in files)
        assert any(f.endswith(".html") for f in files)


def test_main_zero_config_execution() -> None:
    """Verify that repo360 audit runs with zero configuration files (pure built-in defaults)."""
    with tempfile.TemporaryDirectory() as temp_work_dir:
        old_cwd = os.getcwd()
        os.chdir(temp_work_dir)
        try:
            output_dir = os.path.join(temp_work_dir, "output")
            test_args = [
                "repo360",
                "audit",
                "--output-dir",
                output_dir,
                "--mock-mode",
            ]

            with patch("sys.argv", test_args):
                exit_code = main()

            assert exit_code == 0

            # Verify output files generated using 100% built-in defaults
            files = os.listdir(output_dir)
            assert any(f.endswith(".xlsx") for f in files)
            assert any(f.endswith(".csv") for f in files)
            assert any(f.endswith(".html") for f in files)
        finally:
            os.chdir(old_cwd)


def test_main_keyboard_interrupt_clean_exit() -> None:
    """Verify that Ctrl+C in CLI exits cleanly with code 130 without unhandled exception."""
    test_args = ["repo360", "audit", "--mock-mode"]

    with patch("sys.argv", test_args):
        with patch("src.main._run_cli", side_effect=KeyboardInterrupt):
            exit_code = main()
            assert exit_code == 130
