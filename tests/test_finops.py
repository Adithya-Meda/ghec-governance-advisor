"""Unit and integration tests for Repo360 FinOps storage & artifact profiling."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from openpyxl import load_workbook

from src.finops.models import (
    ArtifactRecord,
    CacheRecord,
    FinOpsConfig,
    PackageRecord,
    RepoStorageProfile,
    format_bytes_to_gb,
    format_bytes_to_mb,
)
from src.finops.collector import (
    build_finops_rows,
    collect_org_packages,
    collect_repo_artifacts,
    collect_repo_caches,
    profile_single_repo,
)
from src.finops.reporter import write_finops_workbook


def test_byte_formatters():
    assert format_bytes_to_mb(1024 * 1024 * 50) == 50.0
    assert format_bytes_to_gb(1024 * 1024 * 1024 * 2) == 2.0


def test_artifact_record_properties():
    now = datetime.now(timezone.utc)
    art_default = ArtifactRecord(
        id=1,
        name="build-artifacts",
        size_in_bytes=104857600,  # 100 MB
        created_at=now,
        expires_at=now + timedelta(days=90),
        expired=False,
        workflow_run_id=555,
    )
    assert art_default.size_mb == 100.0
    assert art_default.retention_days == 90
    assert art_default.is_default_90_day is True

    art_custom = ArtifactRecord(
        id=2,
        name="test-reports",
        size_in_bytes=10485760,  # 10 MB
        created_at=now,
        expires_at=now + timedelta(days=7),
        expired=False,
    )
    assert art_custom.size_mb == 10.0
    assert art_custom.retention_days == 7
    assert art_custom.is_default_90_day is False


def test_cache_record_stale():
    now = datetime.now(timezone.utc)
    fresh_cache = CacheRecord(
        id=10,
        key="npm-cache-v1",
        size_in_bytes=52428800,  # 50 MB
        created_at=now - timedelta(days=5),
        last_accessed_at=now - timedelta(days=2),
    )
    assert fresh_cache.size_mb == 50.0
    assert fresh_cache.is_stale is False

    stale_cache = CacheRecord(
        id=11,
        key="pip-cache-old",
        size_in_bytes=104857600,  # 100 MB
        created_at=now - timedelta(days=60),
        last_accessed_at=now - timedelta(days=40),
    )
    assert stale_cache.is_stale is True


def test_repo_storage_profile_optimizations():
    now = datetime.now(timezone.utc)
    profile = RepoStorageProfile(
        org="fintech-org",
        repo="payments-api",
        visibility="private",
        disk_size_kb=512000,  # 500 MB
    )
    # Add 12 90-day retention artifacts (exceeds threshold)
    for i in range(12):
        profile.artifacts.append(
            ArtifactRecord(
                id=i,
                name=f"artifact-{i}",
                size_in_bytes=52428800,  # 50 MB
                created_at=now,
                expires_at=now + timedelta(days=90),
                expired=False,
            )
        )
    profile.caches.append(
        CacheRecord(
            id=101,
            key="maven-cache",
            size_in_bytes=104857600,  # 100 MB
            last_accessed_at=now - timedelta(days=45),
        )
    )

    assert profile.disk_size_mb == 500.0
    assert profile.active_artifact_mb == 600.0
    assert profile.default_90_day_count == 12
    assert profile.cache_mb == 100.0
    assert profile.total_storage_mb == 1200.0
    assert profile.optimization_status == "High Waste"
    assert "Reduce retention-days" in profile.recommendation
    assert "Purge 1 stale Actions caches" in profile.recommendation


def test_build_finops_rows():
    now = datetime.now(timezone.utc)
    profile = RepoStorageProfile(
        org="fintech-org",
        repo="core-service",
        visibility="internal",
        disk_size_kb=204800,  # 200 MB
    )
    profile.artifacts.append(
        ArtifactRecord(
            id=1,
            name="app-binaries",
            size_in_bytes=52428800,
            created_at=now,
            expires_at=now + timedelta(days=90),
            expired=False,
            workflow_run_id=999,
        )
    )
    package = PackageRecord(
        id=77,
        name="docker-core",
        package_type="container",
        version_count=3,
        updated_at=now,
        repo_name="core-service",
    )

    repo_rows, org_rows, artifact_rows, cache_package_rows = build_finops_rows(
        profiles=[profile],
        org_packages={"fintech-org": [package]},
        orgs=["fintech-org"],
    )

    assert len(repo_rows) == 1
    assert repo_rows[0][0] == "fintech-org"
    assert repo_rows[0][1] == "core-service"
    assert repo_rows[0][2] == "Internal"
    assert repo_rows[0][3] == 200.0  # Disk MB
    assert repo_rows[0][4] == 1  # Active Artifacts
    assert repo_rows[0][5] == 50.0  # Artifact MB

    assert len(org_rows) == 1
    assert org_rows[0][0] == "fintech-org"
    assert org_rows[0][1] == 1  # Scanned repos
    assert org_rows[0][2] == 200.0  # Disk MB
    assert org_rows[0][4] == 50.0  # Artifact MB

    assert len(artifact_rows) == 1
    assert artifact_rows[0][0] == "fintech-org"
    assert artifact_rows[0][3] == "app-binaries"
    assert artifact_rows[0][10] == "999"

    assert len(cache_package_rows) == 1
    assert cache_package_rows[0][2] == "Package (container)"
    assert cache_package_rows[0][3] == "docker-core"


def test_write_finops_workbook(tmp_path: Path):
    now = datetime.now(timezone.utc)
    profile = RepoStorageProfile(
        org="demo-org",
        repo="demo-repo",
        visibility="public",
        disk_size_kb=10240,
    )
    repo_rows, org_rows, artifact_rows, cache_package_rows = build_finops_rows(
        profiles=[profile],
        org_packages={"demo-org": []},
        orgs=["demo-org"],
    )

    out_file = tmp_path / "finops_test.xlsx"
    cfg = FinOpsConfig(output_dir=str(tmp_path))

    write_finops_workbook(
        path=out_file,
        cfg=cfg,
        now=now,
        repo_rows=repo_rows,
        org_rows=org_rows,
        artifact_rows=artifact_rows,
        cache_package_rows=cache_package_rows,
        failures=[],
        execution_duration=1.5,
    )

    assert out_file.exists()
    wb = load_workbook(out_file)
    sheet_names = wb.sheetnames
    assert "Executive Summary" in sheet_names
    assert "Storage by Repository" in sheet_names
    assert "Artifact Inventory" in sheet_names
    assert "Cache & Package Inventory" in sheet_names

    summary_ws = wb["Executive Summary"]
    assert "Repo360 FinOps" in summary_ws["A1"].value
