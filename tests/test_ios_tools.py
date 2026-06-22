"""Tests for AppShip iOS tools."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from appship.tools.ios_tools import (
    analyze_ios_project,
    build_ios_ipa,
    upload_to_app_store,
    get_app_store_status,
)


# ---------------------------------------------------------------------------
# analyze_ios_project tests
# ---------------------------------------------------------------------------


def test_analyze_nonexistent_path():
    result = json.loads(analyze_ios_project("/nonexistent/path/to/ios/project"))
    assert result["status"] == "failed"
    assert "does not exist" in result["error_summary"].lower()


def test_analyze_empty_dir():
    with tempfile.TemporaryDirectory() as tmp:
        result = json.loads(analyze_ios_project(tmp))
        assert result["status"] == "failed"
        assert "no .xcodeproj" in result["error_summary"].lower()


def test_analyze_minimal_xcode_project():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # Create .xcodeproj bundle directory
        xcode_bundle = root / "TestApp.xcodeproj"
        xcode_bundle.mkdir()
        (xcode_bundle / "project.pbxproj").write_text("""\
// !$*UTF8*$!
{
    archiveVersion = 1;
    classes = {};
    objectVersion = 56;
    objects = {
        /* Build settings for Debug */
        AB12CD34 /* Debug */ = {
            isa = XCBuildConfiguration;
            buildSettings = {
                PRODUCT_BUNDLE_IDENTIFIER = "com.example.test";
                MARKETING_VERSION = "1.0.0";
                CURRENT_PROJECT_VERSION = "42";
                IPHONEOS_DEPLOYMENT_TARGET = "15.0";
            };
        };
    };
    rootObject = AB12CD34;
}
""")

        result = json.loads(analyze_ios_project(tmp))
        assert result["status"] == "ok"
        assert result["project_name"] == "TestApp"
        assert result["bundle_id"] == "com.example.test"
        assert result["version"] == "1.0.0"
        assert result["build_number"] == "42"
        assert result["min_ios_version"] == "15.0"
        assert result["has_export_options"] is False
        assert result["has_pods"] is False
        assert result["has_spm"] is False
        assert result["xcode_project_type"] == "xcodeproj"


def test_analyze_with_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # Create .xcodeproj for pbxproj reading
        xcode_bundle = root / "MyApp.xcodeproj"
        xcode_bundle.mkdir()
        (xcode_bundle / "project.pbxproj").write_text("""\
// !$*UTF8*$!
{
    archiveVersion = 1;
    objects = {
        DEBUG_CONFIG = {
            isa = XCBuildConfiguration;
            buildSettings = {
                PRODUCT_BUNDLE_IDENTIFIER = "com.example.workspace";
                MARKETING_VERSION = "2.0.0";
                IPHONEOS_DEPLOYMENT_TARGET = "16.0";
            };
        };
    };
    rootObject = DEBUG_CONFIG;
}
""")

        # Workspace takes precedence in _find_xcode_project
        workspace = root / "MyApp.xcworkspace"
        workspace.mkdir()

        result = json.loads(analyze_ios_project(tmp))
        assert result["status"] == "ok"
        assert result["xcode_project_type"] == "xcworkspace"
        assert result["bundle_id"] == "com.example.workspace"


def test_analyze_with_cocoapods_and_spm_and_export_options():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        xcode_bundle = root / "MixedApp.xcodeproj"
        xcode_bundle.mkdir()
        (xcode_bundle / "project.pbxproj").write_text("""\
// !$*UTF8*$!
{
    archiveVersion = 1;
    objects = {
        DEBUG_CONFIG = {
            isa = XCBuildConfiguration;
            buildSettings = {
                PRODUCT_BUNDLE_IDENTIFIER = "com.example.mixed";
            };
        };
    };
    rootObject = DEBUG_CONFIG;
}
""")

        # Add Podfile
        (root / "Podfile").write_text("pod 'Alamofire'\n")
        # Add Package.swift
        (root / "Package.swift").write_text("// swift-tools-version:5.7\n")
        # Add exportOptions.plist
        (root / "exportOptions.plist").write_text("<?xml version=\"1.0\"?>\n")

        result = json.loads(analyze_ios_project(tmp))
        assert result["status"] == "ok"
        assert result["bundle_id"] == "com.example.mixed"
        assert result["has_pods"] is True
        assert result["has_spm"] is True
        assert result["has_export_options"] is True


def test_analyze_missing_bundle_id():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        xcode_bundle = root / "NoBundle.xcodeproj"
        xcode_bundle.mkdir()
        (xcode_bundle / "project.pbxproj").write_text("{}")

        result = json.loads(analyze_ios_project(tmp))
        assert result["status"] == "ok"
        assert result["bundle_id"] is None
        assert result["version"] is None


def test_analyze_marketing_version_fallback_to_current():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        xcode_bundle = root / "FallbackApp.xcodeproj"
        xcode_bundle.mkdir()
        (xcode_bundle / "project.pbxproj").write_text("""\
// !$*UTF8*$!
{
    archiveVersion = 1;
    objects = {
        DEBUG_CONFIG = {
            isa = XCBuildConfiguration;
            buildSettings = {
                PRODUCT_BUNDLE_IDENTIFIER = "com.example.fallback";
                CURRENT_PROJECT_VERSION = "99";
            };
        };
    };
    rootObject = DEBUG_CONFIG;
}
""")

        result = json.loads(analyze_ios_project(tmp))
        assert result["status"] == "ok"
        # MARKETING_VERSION not present; version falls back to CURRENT_PROJECT_VERSION
        assert result["version"] == "99"
        assert result["build_number"] == "99"


# ---------------------------------------------------------------------------
# build_ios_ipa tests
# ---------------------------------------------------------------------------


def test_build_no_xcode_project():
    with tempfile.TemporaryDirectory() as tmp:
        result = json.loads(build_ios_ipa(tmp))
        assert result["status"] == "failed"
        assert "no .xcodeproj" in result["error_summary"].lower()


def test_build_no_xcodebuild():
    """If xcodebuild is not on PATH, build should fail with a helpful message."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        xcode_bundle = root / "FakeApp.xcodeproj"
        xcode_bundle.mkdir()

        # Simulate xcodebuild not found
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = json.loads(build_ios_ipa(tmp))
        assert result["status"] == "failed"
        assert "xcodebuild not found" in result["error_summary"]


def test_build_xcodebuild_version_timeout():
    """If xcodebuild -version times out, build should fail gracefully."""
    import subprocess as sp

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        xcode_bundle = root / "FakeApp.xcodeproj"
        xcode_bundle.mkdir()

        with patch("subprocess.run", side_effect=sp.TimeoutExpired(["xcodebuild", "-version"], 30)):
            result = json.loads(build_ios_ipa(tmp))
        assert result["status"] == "failed"
        assert "timed out" in result["error_summary"].lower()


def test_build_archive_failure():
    """When archive fails, return a structured error with raw_error_line."""
    import subprocess as sp

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        xcode_bundle = root / "FakeApp.xcodeproj"
        xcode_bundle.mkdir()
        (xcode_bundle / "project.pbxproj").write_text("{}")

        def mock_run(cmd, **_kw):
            if "-version" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="Xcode 15.0")
            # Simulate archive failure
            return sp.CompletedProcess(cmd, 65, stdout="", stderr="error: No such module 'Alamofire'")

        with patch("subprocess.run", side_effect=mock_run):
            result = json.loads(build_ios_ipa(tmp))
        assert result["status"] == "failed"
        assert "Alamofire" in result.get("raw_error_line", "")


def test_build_archive_signing_error():
    """Signing errors should produce a targeted suggestion."""
    import subprocess as sp

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        xcode_bundle = root / "FakeApp.xcodeproj"
        xcode_bundle.mkdir()
        (xcode_bundle / "project.pbxproj").write_text("{}")

        def mock_run(cmd, **_kw):
            if "-version" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="Xcode 15.0")
            return sp.CompletedProcess(
                cmd, 65, stdout="",
                stderr="error: Signing certificate is missing. Provisioning profile not found."
            )

        with patch("subprocess.run", side_effect=mock_run):
            result = json.loads(build_ios_ipa(tmp))
        assert result["status"] == "failed"
        assert "signing" in result.get("suggestion", "").lower()


def test_build_archive_timeout():
    """Build timeout should produce a clean error."""
    import subprocess as sp

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        xcode_bundle = root / "FakeApp.xcodeproj"
        xcode_bundle.mkdir()
        (xcode_bundle / "project.pbxproj").write_text("{}")

        def mock_run(cmd, **_kw):
            if "-version" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="Xcode 15.0")
            raise sp.TimeoutExpired(cmd, 600)

        with patch("subprocess.run", side_effect=mock_run):
            result = json.loads(build_ios_ipa(tmp))
        assert result["status"] == "failed"
        assert "timed out" in result["error_summary"].lower()


def test_build_success_with_ipa():
    """Full happy path: archive + export both succeed, .ipa found."""
    import subprocess as sp

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        xcode_bundle = root / "RealApp.xcodeproj"
        xcode_bundle.mkdir()
        (xcode_bundle / "project.pbxproj").write_text("{}")

        # Create export path and fake .ipa ahead of time for the mock to pick up
        export_path = root / "build" / "AppShipDerivedData" / "export"
        export_path.mkdir(parents=True)
        (export_path / "RealApp.ipa").write_text("fake ipa binary payload")

        def mock_run(cmd, **_kw):
            if "-version" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="Xcode 15.0")
            if "archive" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="archive complete")
            if "-exportArchive" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="export complete")
            return sp.CompletedProcess(cmd, 0)

        with patch("subprocess.run", side_effect=mock_run), \
             patch("time.time", side_effect=[0, 45.2, 45.201]):
            result = json.loads(build_ios_ipa(tmp))
        assert result["status"] == "ok"
        assert result["ipa_path"].endswith(".ipa")
        assert result["build_time_seconds"] == 45.2
        assert result["ipa_size_bytes"] == len("fake ipa binary payload")
        assert result["scheme"] == "RealApp"
        assert result["configuration"] == "Release"


def test_build_export_fails_no_ipa():
    """Export succeeds but no .ipa is found."""
    import subprocess as sp

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        xcode_bundle = root / "FakeApp.xcodeproj"
        xcode_bundle.mkdir()
        (xcode_bundle / "project.pbxproj").write_text("{}")

        # Export path exists but is empty
        export_path = root / "build" / "AppShipDerivedData" / "export"
        export_path.mkdir(parents=True)

        def mock_run(cmd, **_kw):
            if "-version" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="Xcode 15.0")
            if "archive" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="archive complete")
            if "-exportArchive" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="export complete")
            return sp.CompletedProcess(cmd, 0)

        with patch("subprocess.run", side_effect=mock_run):
            result = json.loads(build_ios_ipa(tmp))
        assert result["status"] == "failed"
        assert "no .ipa" in result["error_summary"].lower()


def test_build_export_timeout():
    """IPA export timeout returns a clean error."""
    import subprocess as sp

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        xcode_bundle = root / "FakeApp.xcodeproj"
        xcode_bundle.mkdir()
        (xcode_bundle / "project.pbxproj").write_text("{}")

        def mock_run(cmd, **_kw):
            if "-version" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="Xcode 15.0")
            if "archive" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="archive complete")
            if "-exportArchive" in cmd:
                raise sp.TimeoutExpired(cmd, 300)
            return sp.CompletedProcess(cmd, 0)

        with patch("subprocess.run", side_effect=mock_run):
            result = json.loads(build_ios_ipa(tmp))
        assert result["status"] == "failed"
        assert "timed out" in result["error_summary"].lower()


def test_build_custom_scheme_and_config():
    """Build uses provided scheme and configuration."""
    import subprocess as sp

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        xcode_bundle = root / "MyApp.xcodeproj"
        xcode_bundle.mkdir()
        (xcode_bundle / "project.pbxproj").write_text("{}")

        export_path = root / "build" / "AppShipDerivedData" / "export"
        export_path.mkdir(parents=True)
        (export_path / "MyApp.ipa").write_text("ipa")

        captured_cmds = []

        def mock_run(cmd, **_kw):
            captured_cmds.append(cmd)
            if "-version" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="Xcode 15.0")
            return sp.CompletedProcess(cmd, 0, stdout="ok")

        with patch("subprocess.run", side_effect=mock_run):
            result = json.loads(build_ios_ipa(tmp, scheme="StagingScheme", configuration="Debug"))
        assert result["status"] == "ok"
        assert result["scheme"] == "StagingScheme"
        assert result["configuration"] == "Debug"

        # Verify the archive command includes our custom scheme/config
        archive_cmd = next(c for c in captured_cmds if "archive" in c)
        assert "-scheme" in archive_cmd
        assert "StagingScheme" in archive_cmd
        assert "-configuration" in archive_cmd
        assert "Debug" in archive_cmd


def test_build_with_export_options_plist():
    """When exportOptions.plist exists, it is included in the export command."""
    import subprocess as sp

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        xcode_bundle = root / "OptApp.xcodeproj"
        xcode_bundle.mkdir()
        (xcode_bundle / "project.pbxproj").write_text("{}")

        # Create exportOptions.plist
        (root / "exportOptions.plist").write_text("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>method</key>
    <string>app-store</string>
</dict>
</plist>""")

        export_path = root / "build" / "AppShipDerivedData" / "export"
        export_path.mkdir(parents=True)
        (export_path / "OptApp.ipa").write_text("ipa")

        captured_cmds = []

        def mock_run(cmd, **_kw):
            captured_cmds.append(cmd)
            if "-version" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="Xcode 15.0")
            return sp.CompletedProcess(cmd, 0, stdout="ok")

        with patch("subprocess.run", side_effect=mock_run):
            result = json.loads(build_ios_ipa(tmp))
        assert result["status"] == "ok"

        # Verify exportOptionsPlist flag is present
        export_cmd = next(c for c in captured_cmds if "-exportArchive" in c)
        assert "-exportOptionsPlist" in export_cmd


# ---------------------------------------------------------------------------
# upload_to_app_store tests
# ---------------------------------------------------------------------------

import os


def test_upload_no_api_key():
    """Upload fails when App Store API key env vars are not set."""
    with tempfile.TemporaryDirectory() as tmp:
        ipa_path = Path(tmp) / "test.ipa"
        ipa_path.write_text("fake ipa")
        with patch.dict(os.environ, {}, clear=True):
            result = json.loads(upload_to_app_store(str(ipa_path)))
        assert result["status"] == "failed"
        assert "APPSTORE_API_KEY_ID" in result["error_summary"]


def test_upload_hitl_approval():
    """HITL gate returns pending_approval when task_id is provided."""
    with tempfile.TemporaryDirectory() as tmp:
        ipa_path = Path(tmp) / "test.ipa"
        ipa_path.write_text("fake ipa")
        key_file = Path(tmp) / "key.p8"
        key_file.write_text("fake key content")

        with patch.dict(os.environ, {
            "APPSTORE_API_KEY_ID": "TESTKEY123",
            "APPSTORE_API_ISSUER_ID": "abc-def-ghi",
            "APPSTORE_API_KEY_PATH": str(key_file),
        }):
            result = json.loads(upload_to_app_store(
                str(ipa_path),
                bundle_id="com.example.test",
                task_id="test-task-1",
            ))
        assert result["status"] == "pending_approval"
        assert result["approval_token"].startswith("appship-upload-ios-")
        assert result["details"]["bundle_id"] == "com.example.test"


def test_upload_ipa_not_found():
    """Upload fails when IPA file doesn't exist."""
    with patch.dict(os.environ, {
        "APPSTORE_API_KEY_ID": "K123",
        "APPSTORE_API_ISSUER_ID": "issuer",
        "APPSTORE_API_KEY_PATH": "/fake/key.p8",
    }):
        result = json.loads(upload_to_app_store("/nonexistent/app.ipa"))
    assert result["status"] == "failed"
    assert "not found" in result["error_summary"].lower()


def test_upload_key_file_not_found():
    """Upload fails when the .p8 key file path is invalid."""
    with tempfile.TemporaryDirectory() as tmp:
        ipa_path = Path(tmp) / "test.ipa"
        ipa_path.write_text("fake")

        with patch.dict(os.environ, {
            "APPSTORE_API_KEY_ID": "K123",
            "APPSTORE_API_ISSUER_ID": "issuer",
            "APPSTORE_API_KEY_PATH": "/nonexistent/key.p8",
        }):
            result = json.loads(upload_to_app_store(str(ipa_path)))
        assert result["status"] == "failed"
        assert "not found" in result["error_summary"].lower()


# ---------------------------------------------------------------------------
# get_app_store_status tests
# ---------------------------------------------------------------------------


def test_status_no_api_key():
    """Status query fails when API credentials are not set."""
    with patch.dict(os.environ, {}, clear=True):
        result = json.loads(get_app_store_status("com.example.test"))
    assert result["status"] == "failed"
    assert "credentials" in result["error_summary"].lower()


def test_status_key_file_not_found():
    """Status query fails when .p8 key path is invalid."""
    with patch.dict(os.environ, {
        "APPSTORE_API_KEY_ID": "K123",
        "APPSTORE_API_ISSUER_ID": "issuer",
        "APPSTORE_API_KEY_PATH": "/nonexistent/key.p8",
    }):
        result = json.loads(get_app_store_status("com.example.test"))
    assert result["status"] == "failed"
    assert "not found" in result["error_summary"].lower()
