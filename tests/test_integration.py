"""End-to-end integration test simulating audit execution."""

import os
import tempfile
from unittest.mock import patch
import pytest

from src.main import main


def test_main_mock_mode_execution() -> None:
    """Run full CLI execution in mock mode and verify report artifacts."""
    with tempfile.TemporaryDirectory() as temp_dir:
        test_args = [
            "src.main",
            "--app-config",
            "config/config.json",
            "--advisory-config",
            "config/advisory.json",
            "--inventory",
            "config/repos.csv",
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

