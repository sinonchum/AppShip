"""AppShip — Agent-native iOS distribution tools.

Each tool is a standalone function returning structured JSON for LLM consumption.
All outputs are designed to fit within agent context windows (no raw Xcode dumps).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _find_xcode_project(project_path: Path) -> Path | None:
    """Locate .xcworkspace or .xcodeproj inside the project root.

    Prefers .xcworkspace over .xcodeproj (CocoaPods convention).
    """
    for name in (".xcworkspace", ".xcodeproj"):
        candidates = sorted(project_path.glob(f"*{name}"))
        if candidates:
            return candidates[0]
    return None


def _read_pbxproj(project_path: Path) -> str | None:
    """Return the contents of project.pbxproj if available.

    The pbxproj lives inside the .xcodeproj bundle:
        <project>.xcodeproj/project.pbxproj
    """
    # Find a .xcodeproj (not .xcworkspace)
    for candidate in sorted(project_path.glob("*.xcodeproj")):
        xcodeproj_path = candidate
        pbx_path = xcodeproj_path / "project.pbxproj"
        if pbx_path.exists():
            return pbx_path.read_text(encoding="utf-8", errors="replace")

    return None


def _ok(data: dict[str, Any]) -> str:
    data.setdefault("status", "ok")
    return json.dumps(data, ensure_ascii=False)


def _fail(error_summary: str, suggestion: str = "", **extra: Any) -> str:
    return json.dumps({
        "status": "failed",
        "error_summary": error_summary,
        "suggestion": suggestion,
        **extra,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# analyze_ios_project
# ---------------------------------------------------------------------------

def analyze_ios_project(project_path: str) -> str:
    """Analyze an iOS project and return structured metadata."""
    root = Path(project_path).resolve()
    if not root.is_dir():
        return _fail(f"Project path does not exist: {root}",
                      "Provide an absolute path to an iOS project root.")

    # Find Xcode project/workspace
    xcode_project = _find_xcode_project(root)
    if xcode_project is None:
        return _fail(f"No .xcodeproj or .xcworkspace found in {root}",
                      "Ensure the path points to an iOS project root with an Xcode project.")

    project_name = xcode_project.stem  # filename without suffix

    # Parse pbxproj
    pbxproj_content = _read_pbxproj(root)

    # Extract bundle identifier
    bundle_id = None
    if pbxproj_content:
        m = re.search(r'PRODUCT_BUNDLE_IDENTIFIER\s*=\s*"([^"]+)"', pbxproj_content)
        if m:
            bundle_id = m.group(1)

    # Extract version (prefer MARKETING_VERSION, fallback to CURRENT_PROJECT_VERSION)
    version = None
    build_number = None
    if pbxproj_content:
        vm = re.search(r'MARKETING_VERSION\s*=\s*"([^"]+)"', pbxproj_content)
        if vm:
            version = vm.group(1)
        vc = re.search(r'CURRENT_PROJECT_VERSION\s*=\s*"([^"]+)"', pbxproj_content)
        if vc:
            build_number = vc.group(1)
            if version is None:
                version = build_number

    # Extract deployment target
    min_ios_version = None
    if pbxproj_content:
        dt = re.search(r'IPHONEOS_DEPLOYMENT_TARGET\s*=\s*"([^"]+)"', pbxproj_content)
        if dt:
            min_ios_version = dt.group(1)

    # Check for exportOptions.plist
    export_options_path = root / "exportOptions.plist"
    has_export_options = export_options_path.exists()

    # Check for CocoaPods
    podfile_path = root / "Podfile"
    has_pods = podfile_path.exists()

    # Check for Swift Package Manager
    package_swift = root / "Package.swift"
    has_spm = package_swift.exists()

    return _ok({
        "project_name": project_name,
        "bundle_id": bundle_id,
        "version": version,
        "build_number": build_number,
        "min_ios_version": min_ios_version,
        "has_export_options": has_export_options,
        "has_pods": has_pods,
        "has_spm": has_spm,
        "xcode_project_type": xcode_project.suffix.lstrip("."),
        "xcode_project_path": str(xcode_project),
    })


# ---------------------------------------------------------------------------
# build_ios_ipa
# ---------------------------------------------------------------------------

def build_ios_ipa(project_path: str, scheme: str = "", configuration: str = "Release") -> str:
    """Build an iOS .ipa archive via xcodebuild.

    Steps:
    1. Locate .xcodeproj or .xcworkspace.
    2. Archive the app with xcodebuild.
    3. Export the archive to an .ipa.
    4. Return the .ipa path and metadata.
    """
    root = Path(project_path).resolve()
    if not root.is_dir():
        return _fail(f"Project path does not exist: {root}",
                      "Provide an absolute path to an iOS project root.")

    # Find Xcode project/workspace
    xcode_project = _find_xcode_project(root)
    if xcode_project is None:
        return _fail(f"No .xcodeproj or .xcworkspace found in {root}",
                      "Ensure the path points to an iOS project root with an Xcode project.")

    # Determine scheme
    if not scheme:
        scheme = xcode_project.stem  # project name without extension

    # Check xcodebuild availability
    try:
        subprocess.run(["xcodebuild", "-version"], capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return _fail("xcodebuild not found on PATH",
                      "Ensure Xcode and command-line tools are installed. Run: xcode-select --install")
    except subprocess.TimeoutExpired:
        return _fail("xcodebuild -version timed out",
                      "Xcode tools may be in a bad state. Try restarting your terminal.")

    # Derive build paths
    derived_path = root / "build" / "AppShipDerivedData"
    archive_path = derived_path / f"{scheme}.xcarchive"
    export_path = derived_path / "export"

    # Determine project/workspace flag
    if xcode_project.suffix == ".xcworkspace":
        proj_flag = "-workspace"
    else:
        proj_flag = "-project"

    # ---------------------------------------------------------------
    # Step 1: Build archive
    # ---------------------------------------------------------------
    archive_cmd = [
        "xcodebuild",
        proj_flag, str(xcode_project),
        "-scheme", scheme,
        "-configuration", configuration,
        "-archivePath", str(archive_path),
        "archive",
    ]

    start = time.time()
    try:
        archive_result = subprocess.run(
            archive_cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return _fail("Archive build timed out after 600 seconds",
                      "The project may be too large. Try cleaning derived data first.")

    elapsed = time.time() - start

    if archive_result.returncode != 0:
        stderr = (archive_result.stderr or "") + "\n" + (archive_result.stdout or "")
        error_summary = _extract_build_error(stderr)

        suggestion = ""
        if "scheme" in stderr.lower() and "not found" in stderr.lower():
            suggestion = f"Scheme '{scheme}' not found. List schemes with: xcodebuild -list"
        elif "signing" in stderr.lower() or "provisioning" in stderr.lower():
            suggestion = "Code signing error. Check provisioning profiles and signing certificates."
        elif "no such module" in stderr.lower():
            suggestion = "Missing dependency. Try resolving Swift packages or running pod install."

        return _fail(error_summary, suggestion,
                     raw_error_line=stderr.strip()[:2000],
                     build_time_seconds=round(elapsed, 1))

    # ---------------------------------------------------------------
    # Step 2: Export archive to IPA
    # ---------------------------------------------------------------
    export_cmd = [
        "xcodebuild",
        "-exportArchive",
        "-archivePath", str(archive_path),
        "-exportPath", str(export_path),
    ]

    # Include exportOptions.plist if present
    export_options = root / "exportOptions.plist"
    if export_options.exists():
        export_cmd.extend(["-exportOptionsPlist", str(export_options)])

    try:
        export_result = subprocess.run(
            export_cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return _fail("IPA export timed out after 300 seconds",
                      "Export may have hung. Check the archive at: " + str(archive_path))

    elapsed = time.time() - start

    if export_result.returncode != 0:
        stderr = (export_result.stderr or "") + "\n" + (export_result.stdout or "")
        error_summary = _extract_build_error(stderr)

        suggestion = ""
        if "exportOptionsPlist" in stderr.lower() and "not found" in stderr.lower():
            suggestion = "Create an exportOptions.plist file with export settings."

        return _fail(error_summary, suggestion,
                     raw_error_line=stderr.strip()[:2000],
                     build_time_seconds=round(elapsed, 1))

    # ---------------------------------------------------------------
    # Step 3: Find the IPA
    # ---------------------------------------------------------------
    if not export_path.exists():
        return _fail("Export completed but export directory not found",
                      f"Expected at: {export_path}",
                      build_time_seconds=round(elapsed, 1))

    ipa_files = list(export_path.glob("*.ipa"))
    if not ipa_files:
        return _fail("Export completed but no .ipa file found",
                      f"Searched in: {export_path}",
                      build_time_seconds=round(elapsed, 1))

    latest_ipa = max(ipa_files, key=lambda p: p.stat().st_mtime)
    ipa_size = latest_ipa.stat().st_size

    return _ok({
        "ipa_path": str(latest_ipa),
        "build_time_seconds": round(elapsed, 1),
        "ipa_size_bytes": ipa_size,
        "scheme": scheme,
        "configuration": configuration,
    })


# ---------------------------------------------------------------------------
# Error extraction helper
# ---------------------------------------------------------------------------

def _extract_build_error(stderr_text: str) -> str:
    """Extract the first meaningful error line from xcodebuild output."""
    for line in stderr_text.splitlines():
        if "error:" in line.lower() or "Error" in line or "FAILURE" in line:
            if len(line) < 300:
                return line.strip()
            return line.strip()[:300] + "..."

    # Fallback: grab the last non-blank line
    for line in reversed(stderr_text.splitlines()):
        line = line.strip()
        if line:
            return line[:300]

    return "Unknown build error"


# ---------------------------------------------------------------------------
# Hermes tool registry integration
# ---------------------------------------------------------------------------

def check_requirements() -> bool:
    """Tools are always available — xcodebuild checks happen at call time."""
    return True


# ---------------------------------------------------------------------------
# JWT helper for App Store Connect API
# ---------------------------------------------------------------------------

def _generate_appstore_jwt(key_id: str, issuer_id: str, key_path: str) -> str:
    """Generate an ES256 JWT for App Store Connect API auth.

    Uses pyjwt + cryptography. Returns the JWT token string, or raises
    ImportError with install instructions if deps are missing.
    """
    try:
        import jwt
    except ImportError:
        raise ImportError(
            "pyjwt is required for App Store Connect API. "
            "Install: pip install pyjwt cryptography"
        )

    key_content = Path(key_path).read_text(encoding="utf-8")
    now = int(time.time())
    payload = {
        "iss": issuer_id,
        "iat": now,
        "exp": now + 1200,  # 20 minutes
        "aud": "appstoreconnect-v1",
    }
    headers = {
        "alg": "ES256",
        "kid": key_id,
        "typ": "JWT",
    }
    return jwt.encode(payload, key_content, algorithm="ES256", headers=headers)


# ---------------------------------------------------------------------------
# upload_to_app_store
# ---------------------------------------------------------------------------

def upload_to_app_store(
    ipa_path: str,
    bundle_id: str = "",
    api_key_id: str = "",
    api_issuer_id: str = "",
    api_key_path: str = "",
    task_id: str | None = None,
) -> str:
    """Upload an IPA to App Store Connect via xcrun altool. HITL-gated."""
    ipa = Path(ipa_path).resolve()
    if not ipa.exists():
        return _fail(
            f"IPA file not found: {ipa}",
            "Run appship_build_ios_ipa first to generate the IPA.",
        )

    # Resolve credentials: args > env vars
    key_id = api_key_id or os.environ.get("APPSTORE_API_KEY_ID", "")
    issuer_id = api_issuer_id or os.environ.get("APPSTORE_API_ISSUER_ID", "")
    key_path = api_key_path or os.environ.get("APPSTORE_API_KEY_PATH", "")

    if not key_id:
        return _fail(
            "APPSTORE_API_KEY_ID env var not set",
            "Set APPSTORE_API_KEY_ID, APPSTORE_API_ISSUER_ID, and APPSTORE_API_KEY_PATH environment variables.",
        )
    if not issuer_id:
        return _fail(
            "APPSTORE_API_ISSUER_ID env var not set",
            "Set all three App Store Connect API credentials.",
        )

    if not key_path:
        return _fail(
            "APPSTORE_API_KEY_PATH env var not set",
            "Set the path to your .p8 private key file.",
        )

    kp = Path(key_path)
    if not kp.exists():
        return _fail(
            f"API key file not found: {key_path}",
            "Check the APPSTORE_API_KEY_PATH path.",
        )

    # HITL gate
    if task_id:
        approval_token = f"appship-upload-ios-{bundle_id or 'unknown'}-{int(time.time())}"
        return json.dumps({
            "status": "pending_approval",
            "approval_token": approval_token,
            "message": f"Approve upload of {ipa.name} to App Store Connect?",
            "details": {
                "bundle_id": bundle_id,
                "ipa_path": str(ipa),
                "ipa_size_bytes": ipa.stat().st_size,
            },
        }, ensure_ascii=False)

    # Execute xcrun altool
    try:
        result = subprocess.run(
            [
                "xcrun", "altool", "--upload-app",
                "--type", "ios",
                "-f", str(ipa),
                "--apiKey", key_id,
                "--apiIssuer", issuer_id,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except FileNotFoundError:
        return _fail(
            "xcrun not found — Xcode command-line tools required",
            "Install Xcode and Xcode command-line tools: xcode-select --install",
        )
    except subprocess.TimeoutExpired:
        return _fail(
            "Upload timed out after 600 seconds",
            "The IPA may be too large or the network may be slow. Retry.",
        )

    combined = (result.stdout or "") + "\n" + (result.stderr or "")

    if result.returncode != 0:
        suggestion = ""
        if "authentication" in combined.lower() or "unauthorized" in combined.lower():
            suggestion = "Check APPSTORE_API_KEY_ID, APPSTORE_API_ISSUER_ID, and the .p8 key file."
        elif "bundle" in combined.lower() and "not found" in combined.lower():
            suggestion = "Ensure the app exists in App Store Connect with this bundle ID."
        elif "provisioning" in combined.lower() or "profile" in combined.lower():
            suggestion = "Check provisioning profiles in Xcode. The IPA may not be properly signed."

        return _fail(
            combined.strip()[:500],
            suggestion,
            raw_output=combined.strip()[:2000],
        )

    return _ok({
        "altool_output": combined.strip()[:500],
        "ipa_path": str(ipa),
        "bundle_id": bundle_id,
    })


# ---------------------------------------------------------------------------
# get_app_store_status
# ---------------------------------------------------------------------------

def get_app_store_status(
    bundle_id: str,
    api_key_id: str = "",
    api_issuer_id: str = "",
    api_key_path: str = "",
) -> str:
    """Query App Store Connect API for app status."""
    if not bundle_id:
        return _fail(
            "bundle_id is required",
            "Provide the bundle identifier of the app in App Store Connect.",
        )

    # Resolve credentials
    key_id = api_key_id or os.environ.get("APPSTORE_API_KEY_ID", "")
    issuer_id = api_issuer_id or os.environ.get("APPSTORE_API_ISSUER_ID", "")
    key_path = api_key_path or os.environ.get("APPSTORE_API_KEY_PATH", "")

    if not key_id or not issuer_id or not key_path:
        return _fail(
            "App Store Connect API credentials not configured",
            "Set APPSTORE_API_KEY_ID, APPSTORE_API_ISSUER_ID, and APPSTORE_API_KEY_PATH.",
        )

    kp = Path(key_path)
    if not kp.exists():
        return _fail(
            f"API key file not found: {key_path}",
            "Check the APPSTORE_API_KEY_PATH path.",
        )

    try:
        jwt_token = _generate_appstore_jwt(key_id, issuer_id, key_path)
    except ImportError as exc:
        return _fail(str(exc))

    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(
            f"https://api.appstoreconnect.apple.com/v1/apps?filter[bundleId]={bundle_id}",
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Content-Type": "application/json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8")[:500]
        except Exception:
            pass
        if exc.code == 401 or exc.code == 403:
            return _fail(
                f"HTTP {exc.code}: Authentication failed",
                "Check APPSTORE_API_KEY_ID, APPSTORE_API_ISSUER_ID, and the .p8 key file validity.",
                http_status=exc.code,
            )
        elif exc.code == 404:
            return _fail(
                "App not found in App Store Connect",
                f"Check that an app with bundle ID '{bundle_id}' exists in App Store Connect.",
                http_status=exc.code,
            )
        return _fail(
            f"HTTP {exc.code}: {error_body[:300]}",
            http_status=exc.code,
        )
    except Exception as exc:
        return _fail(f"API request failed: {str(exc)[:500]}")

    apps = data.get("data", [])
    if not apps:
        return _ok({
            "bundle_id": bundle_id,
            "found": False,
            "message": "No app found with this bundle ID in App Store Connect.",
        })

    app = apps[0]
    attrs = app.get("attributes", {})

    return _ok({
        "bundle_id": bundle_id,
        "found": True,
        "app_id": app.get("id"),
        "name": attrs.get("name"),
        "primary_category": attrs.get("primaryCategory"),
        "sku": attrs.get("sku"),
        "version_state": attrs.get("versionState"),
    })
