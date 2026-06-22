"""Tests for AppShip tools."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from appship.tools.appship_tools import (
    analyze_android_project,
    build_android_aab,
    get_google_play_status,
    upload_to_google_play,
)


def test_analyze_nonexistent_path():
    result = json.loads(analyze_android_project("/nonexistent/path/to/project"))
    assert result["status"] == "failed"


def test_analyze_empty_dir():
    with tempfile.TemporaryDirectory() as tmp:
        result = json.loads(analyze_android_project(tmp))
        assert result["status"] == "failed"


def test_analyze_minimal_project():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "build.gradle").write_text("""
            android {
                defaultConfig {
                    applicationId "com.example.test"
                    versionCode 1
                    versionName "1.0.0"
                }
            }
        """)
        (root / "settings.gradle").write_text("rootProject.name = 'test'")
        (root / "gradlew").write_text("#!/bin/bash\necho stub")
        (root / "gradlew").chmod(0o755)

        result = json.loads(analyze_android_project(tmp))
        assert result["status"] == "ok"
        assert result["package_name"] == "com.example.test"
        assert result["version_code"] == 1
        assert result["version_name"] == "1.0.0"
        assert result["build_gradle_found"] is True
        assert result["gradle_wrapper_found"] is True


def test_analyze_with_namespace():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "build.gradle.kts").write_text("""
            android {
                namespace = "com.example.kts"
                defaultConfig {
                    versionCode = 10
                    versionName = "2.0.0"
                }
            }
        """)
        (root / "settings.gradle.kts").write_text("rootProject.name = 'kts-test'")

        result = json.loads(analyze_android_project(tmp))
        assert result["status"] == "ok"
        assert result["package_name"] == "com.example.kts"
        assert result["version_code"] == 10


def test_analyze_keystore_detection():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "build.gradle").write_text("""
            android {
                signingConfigs {
                    release {
                        storeFile file("release.jks")
                    }
                }
            }
        """)
        (root / "settings.gradle").write_text("rootProject.name = 'signtest'")

        result = json.loads(analyze_android_project(tmp))
        assert result["keystore_configured"] is True


def test_build_no_gradle_wrapper():
    with tempfile.TemporaryDirectory() as tmp:
        result = json.loads(build_android_aab(tmp))
        assert result["status"] == "failed"
        assert "gradlew" in result["error_summary"].lower()


def test_build_invalid_type():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "gradlew").write_text("#!/bin/bash\necho stub")
        (root / "gradlew").chmod(0o755)
        result = json.loads(build_android_aab(tmp, build_type="staging"))
        assert result["status"] == "failed"
        assert "invalid" in result["error_summary"].lower()


# ---------------------------------------------------------------------------
# upload_to_google_play integration tests
# ---------------------------------------------------------------------------


def test_upload_no_service_account():
    """Upload fails when GOOGLE_PLAY_SERVICE_ACCOUNT env var is not set."""
    with tempfile.TemporaryDirectory() as tmp:
        aab_path = Path(tmp) / "test.aab"
        aab_path.write_text("fake aab content")
        with patch.dict(os.environ, {}, clear=True):
            result = json.loads(upload_to_google_play(str(aab_path), "com.example.app"))
    assert result["status"] == "failed"
    assert "GOOGLE_PLAY_SERVICE_ACCOUNT" in result["error_summary"]


def test_upload_invalid_track():
    """Upload fails for an invalid track name before any other validation."""
    with patch.dict(os.environ, {"GOOGLE_PLAY_SERVICE_ACCOUNT": "/nonexistent/sa.json"}):
        result = json.loads(upload_to_google_play(
            "/nonexistent/path.aab", "com.example.app", track="invalid_track"
        ))
    assert result["status"] == "failed"
    assert "Invalid track" in result["error_summary"]


def test_upload_aab_not_found():
    """Upload fails when the AAB file does not exist (env and track are valid)."""
    with tempfile.TemporaryDirectory() as tmp:
        sa_path = Path(tmp) / "sa.json"
        sa_path.write_text("{}")  # dummy service account file
        with patch.dict(os.environ, {"GOOGLE_PLAY_SERVICE_ACCOUNT": str(sa_path)}):
            result = json.loads(upload_to_google_play(
                "/nonexistent/path.aab", "com.example.app", track="internal"
            ))
    assert result["status"] == "failed"
    assert "not found" in result["error_summary"].lower()


def test_upload_hitl_approval_flow():
    """When task_id is provided, upload returns pending_approval with a token."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        aab_path = root / "test.aab"
        aab_path.write_text("fake aab content")
        sa_path = root / "sa.json"
        sa_path.write_text("{}")
        with patch.dict(os.environ, {"GOOGLE_PLAY_SERVICE_ACCOUNT": str(sa_path)}):
            result = json.loads(upload_to_google_play(
                str(aab_path), "com.example.app", track="internal", task_id="task-123"
            ))
    assert result["status"] == "pending_approval"
    assert "approval_token" in result
    assert result["approval_token"].startswith("appship-upload-")
    assert result["details"]["package_name"] == "com.example.app"
    assert result["details"]["track"] == "internal"


# ---------------------------------------------------------------------------
# get_google_play_status integration tests
# ---------------------------------------------------------------------------


def test_status_no_service_account():
    """Status query fails when GOOGLE_PLAY_SERVICE_ACCOUNT env var is not set."""
    with patch.dict(os.environ, {}, clear=True):
        result = json.loads(get_google_play_status("com.example.app"))
    assert result["status"] == "failed"
    assert "GOOGLE_PLAY_SERVICE_ACCOUNT" in result["error_summary"]


def test_status_service_account_not_found():
    """Status query fails when the service account file path does not exist."""
    with patch.dict(os.environ, {"GOOGLE_PLAY_SERVICE_ACCOUNT": "/nonexistent/sa.json"}):
        result = json.loads(get_google_play_status("com.example.app"))
    assert result["status"] == "failed"
    assert "not found" in result["error_summary"].lower()
