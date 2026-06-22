"""Tests for AppShip tools."""

import json
import tempfile
from pathlib import Path

from appship.tools.appship_tools import analyze_android_project, build_android_aab


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
