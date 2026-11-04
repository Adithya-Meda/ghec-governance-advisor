"""Tests for flexible repository inventory parser."""

import os
import pytest
from src.common.inventory import RepoEntry, load_flexible_repo_entries


def test_load_flexible_inventory_standard(tmp_path):
    csv_file = tmp_path / "repos.csv"
    csv_file.write_text("org,repo,enabled\nmy-org,repo-a,true\nmy-org,repo-b,false\n", encoding="utf-8")

    entries = load_flexible_repo_entries(csv_file)
    assert len(entries) == 2
    assert entries[0] == RepoEntry("my-org", "repo-a", True)
    assert entries[1] == RepoEntry("my-org", "repo-b", False)


def test_load_flexible_inventory_aliases(tmp_path):
    csv_file = tmp_path / "repos.csv"
    csv_file.write_text("org_name,repo_name\nplatform-team,infra-service\n", encoding="utf-8")

    entries = load_flexible_repo_entries(csv_file)
    assert len(entries) == 1
    assert entries[0] == RepoEntry("platform-team", "infra-service", True)


def test_load_flexible_inventory_wildcard(tmp_path):
    csv_file = tmp_path / "repos.csv"
    csv_file.write_text("# Comment line\norganization,repository,active\n# Another comment\nenterprise,*,yes\n", encoding="utf-8")

    entries = load_flexible_repo_entries(csv_file)
    assert len(entries) == 1
    assert entries[0].repo == "*"
    assert entries[0].enabled is True


def test_load_flexible_inventory_missing_file():
    with pytest.raises(FileNotFoundError):
        load_flexible_repo_entries("non_existent_inventory.csv")


def test_load_flexible_inventory_invalid_org(tmp_path):
    csv_file = tmp_path / "repos.csv"
    csv_file.write_text("org,repo\n-invalid-org-,repo1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="validation failed"):
        load_flexible_repo_entries(csv_file)


def test_load_flexible_inventory_no_enabled(tmp_path):
    csv_file = tmp_path / "repos.csv"
    csv_file.write_text("org,repo,enabled\nmy-org,repo1,false\n", encoding="utf-8")

    with pytest.raises(ValueError, match="contains no enabled repositories"):
        load_flexible_repo_entries(csv_file)
