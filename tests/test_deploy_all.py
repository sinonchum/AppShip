"""Tests for deploy_all orchestration."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from appship.tools.deploy_all import deploy_all


# ---------------------------------------------------------------------------
# invalid platform
# ---------------------------------------------------------------------------


def test_deploy_all_invalid_platform():
    """Unknown platform returns a clear error with suggestion."""
    result = json.loads(
        deploy_all("/some/project", platform="windows")
    )
    assert result["status"] == "failed"
    assert result["platform"] == "windows"
    assert result["step"] == "analyze"
    assert "unknown" in result["error_summary"].lower()
    assert "android" in result["suggestion"].lower()
    assert "ios" in result["suggestion"].lower()


# ---------------------------------------------------------------------------
# android — analyze fails
# ---------------------------------------------------------------------------


def test_deploy_all_android_analyze_fails():
    """When the project has no build files, analyze fails and deploy_all
    returns an error at the analyze step."""
    with tempfile.TemporaryDirectory() as tmp:
        result = json.loads(
            deploy_all(tmp, platform="android")
        )
    assert result["status"] == "failed"
    assert result["platform"] == "android"
    assert result["step"] == "analyze"
    assert result["current_result"]["status"] == "failed"
    assert "build.gradle" in result["current_result"]["error_summary"].lower() or \
           "settings.gradle" in result["current_result"]["error_summary"].lower()


# ---------------------------------------------------------------------------
# android — full happy path with mocks
# ---------------------------------------------------------------------------


def test_deploy_all_android_full_pipeline():
    """Mock all four tools to verify the orchestration chains correctly
    and returns full_results on success."""
    mock_analyze = {
        "status": "ok",
        "package_name": "com.example.mock",
        "version_code": 42,
    }
    mock_build = {
        "status": "ok",
        "aab_path": "/tmp/app.aab",
        "build_time_seconds": 12.3,
    }
    mock_upload = {
        "status": "ok",
        "edit_id": "edit-abc-123",
        "track": "internal",
        "package_name": "com.example.mock",
    }
    mock_status = {
        "status": "ok",
        "package_name": "com.example.mock",
        "tracks": [{"track": "internal", "version_code": 42, "status": "completed"}],
    }

    with patch(
        "appship.tools.deploy_all.analyze_android_project",
        return_value=json.dumps(mock_analyze),
    ), patch(
        "appship.tools.deploy_all.build_android_aab",
        return_value=json.dumps(mock_build),
    ), patch(
        "appship.tools.deploy_all.upload_to_google_play",
        return_value=json.dumps(mock_upload),
    ), patch(
        "appship.tools.deploy_all.get_google_play_status",
        return_value=json.dumps(mock_status),
    ):
        result = json.loads(
            deploy_all("/mock/project", platform="android")
        )

    assert result["status"] == "ok"
    assert result["platform"] == "android"
    assert result["step"] == "complete"
    assert "full_results" in result

    fr = result["full_results"]
    assert fr["analyze"]["package_name"] == "com.example.mock"
    assert fr["build"]["aab_path"] == "/tmp/app.aab"
    assert fr["upload"]["edit_id"] == "edit-abc-123"
    assert fr["status"]["tracks"][0]["track"] == "internal"


# ---------------------------------------------------------------------------
# android — HITL gate (pending_approval)
# ---------------------------------------------------------------------------


def test_deploy_all_android_hitl_gate():
    """When upload returns pending_approval, deploy_all stops and returns
    that status without proceeding to the status step."""
    mock_analyze = {
        "status": "ok",
        "package_name": "com.example.hitl",
    }
    mock_build = {
        "status": "ok",
        "aab_path": "/tmp/hitl.aab",
    }
    mock_upload = {
        "status": "pending_approval",
        "approval_token": "appship-upload-com.example.hitl-internal-12345",
        "message": "Approve upload?",
        "details": {"package_name": "com.example.hitl", "track": "internal"},
    }

    with patch(
        "appship.tools.deploy_all.analyze_android_project",
        return_value=json.dumps(mock_analyze),
    ), patch(
        "appship.tools.deploy_all.build_android_aab",
        return_value=json.dumps(mock_build),
    ), patch(
        "appship.tools.deploy_all.upload_to_google_play",
        return_value=json.dumps(mock_upload),
    ):
        result = json.loads(
            deploy_all("/mock/hitl", platform="android", task_id="task-999")
        )

    assert result["status"] == "pending_approval"
    assert result["platform"] == "android"
    assert result["step"] == "upload"
    assert result["current_result"]["approval_token"].startswith("appship-upload-")
    assert "full_results" not in result  # not complete yet


# ---------------------------------------------------------------------------
# android — build fails after analyze succeeds
# ---------------------------------------------------------------------------


def test_deploy_all_android_build_fails():
    """When analyze succeeds but build fails, the error is reported at step=build."""
    mock_analyze = {
        "status": "ok",
        "package_name": "com.example.buildfail",
    }
    mock_build = {
        "status": "failed",
        "error_summary": "Compilation error: something broke",
        "suggestion": "Fix the code.",
    }

    with patch(
        "appship.tools.deploy_all.analyze_android_project",
        return_value=json.dumps(mock_analyze),
    ), patch(
        "appship.tools.deploy_all.build_android_aab",
        return_value=json.dumps(mock_build),
    ):
        result = json.loads(
            deploy_all("/mock/project", platform="android")
        )

    assert result["status"] == "failed"
    assert result["platform"] == "android"
    assert result["step"] == "build"
    assert result["current_result"]["error_summary"] == "Compilation error: something broke"


# ---------------------------------------------------------------------------
# ios — not yet available
# ---------------------------------------------------------------------------


def test_deploy_all_ios_not_implemented():
    """When ios_tools import fails (module missing), deploy_all returns a
    clear error saying iOS tools are not yet available.

    We mock the import to simulate what happens when ios_tools doesn't exist.
    """
    import builtins
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "appship.tools.ios_tools":
            raise ImportError("No module named 'appship.tools.ios_tools'")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        result = json.loads(
            deploy_all("/some/project", platform="ios")
        )

    assert result["status"] == "failed"
    assert result["platform"] == "ios"
    assert result["step"] == "analyze"
    assert result["current_result"]["status"] == "failed"
    assert "not yet available" in result["current_result"]["error_summary"].lower()
    assert "ios" in result["current_result"]["suggestion"].lower()


def test_deploy_all_ios_import_mocked():
    """Verify that even with a mocked ImportError, the graceful fallback works.
    This double-checks the error-handling path explicitly."""
    import builtins
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "appship.tools.ios_tools":
            raise ImportError("No module named 'appship.tools.ios_tools'")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        result = json.loads(
            deploy_all("/some/project", platform="ios")
        )

    assert result["status"] == "failed"
    assert result["platform"] == "ios"
    assert "not yet available" in result["current_result"]["error_summary"].lower()
