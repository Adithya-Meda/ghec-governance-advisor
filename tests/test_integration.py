"""End-to-end integration test simulating audit execution."""

import os
import tempfile
from unittest.mock import patch
import pytest

from src.main import main


def test_main_mock_mode_execution() -> None:
    """Run full CLI execution in mock mode with custom override configs."""
    with tempfile.TemporaryDirectory() as temp_dir:
        custom_advisory = os.path.join(temp_dir, "custom_advisory.json")
        with open(custom_advisory, "w", encoding="utf-8") as f:
            f.write('{"enabled_checks": {"org_admin": {"rulesets_adoption": true}}}')

        test_args = [
            "src.main",
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
    """Verify that ghec-advisor runs with zero configuration files (pure built-in defaults)."""
    with tempfile.TemporaryDirectory() as temp_work_dir:
        # Run inside an empty directory without any config/ or repos.csv
        old_cwd = os.getcwd()
        os.chdir(temp_work_dir)
        try:
            output_dir = os.path.join(temp_work_dir, "output")
            test_args = [
                "src.main",
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
    test_args = ["src.main", "--mock-mode"]

    with patch("sys.argv", test_args):
        with patch("src.main._run_cli", side_effect=KeyboardInterrupt):
            exit_code = main()
            assert exit_code == 130


