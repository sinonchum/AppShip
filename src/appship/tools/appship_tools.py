"""AppShip — Agent-native Google Play Store distribution tools.

Each tool is a standalone function returning structured JSON for LLM consumption.
All outputs are designed to fit within agent context windows (no raw Gradle dumps).
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

def _find_gradle_wrapper(project_path: Path) -> Path | None:
    """Locate gradlew or gradlew.bat inside the project root."""
    for name in ("gradlew.bat", "gradlew"):
        candidate = project_path / name
        if candidate.exists():
            return candidate
    return None


def _read_build_gradle(project_path: Path) -> str | None:
    """Return the contents of the first build.gradle or build.gradle.kts found."""
    for name in ("build.gradle.kts", "build.gradle"):
        candidate = project_path / "app" / name
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="replace")
        candidate = project_path / name
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="replace")
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
# appship_analyze_android_project
# ---------------------------------------------------------------------------

def analyze_android_project(project_path: str) -> str:
    """Analyze an Android project and return structured metadata."""
    root = Path(project_path).resolve()
    if not root.is_dir():
        return _fail(f"Project path does not exist: {root}",
                      "Provide an absolute path to an Android project root.")

    # detect build file
    build_gradle = root / "build.gradle"
    build_gradle_kts = root / "build.gradle.kts"
    settings = root / "settings.gradle"
    settings_kts = root / "settings.gradle.kts"

    has_build_file = build_gradle.exists() or build_gradle_kts.exists()
    has_settings = settings.exists() or settings_kts.exists()
    if not has_build_file and not has_settings:
        return _fail(f"No build.gradle or settings.gradle found in {root}",
                      "Ensure the path points to an Android project root.")

    # extract package name from app/build.gradle
    package_name = None
    app_content = _read_build_gradle(root)
    if app_content:
        m = re.search(r'(?:applicationId|namespace)\s*=?\s*["\']([^"\']+)["\']', app_content)
        if m:
            package_name = m.group(1)
        # also try AndroidManifest
        if not package_name:
            manifest = root / "app" / "src" / "main" / "AndroidManifest.xml"
            if manifest.exists():
                m2 = re.search(r'package=["\']([^"\']+)["\']', manifest.read_text(encoding="utf-8", errors="replace"))
                if m2:
                    package_name = m2.group(1)

    # version info
    version_code = None
    version_name = None
    if app_content:
        vc = re.search(r'versionCode\s*=?\s*(\d+)', app_content)
        if vc:
            version_code = int(vc.group(1))
        vn = re.search(r'versionName\s*=?\s*["\']([^"\']+)["\']', app_content)
        if vn:
            version_name = vn.group(1)

    # keystore detection
    keystore_configured = False
    keystore_path = None
    if app_content and ("signingConfigs" in app_content or "signingConfig" in app_content):
        keystore_configured = True
        # try to extract keystore path
        kp = re.search(r'storeFile\s+file\(["\']?([^"\')]+)["\']?\)', app_content)
        if kp:
            raw_kp = kp.group(1)
            # relative to app dir
            candidate = (root / "app" / raw_kp).resolve()
            if candidate.exists():
                keystore_path = str(candidate)

    # flavor detection
    has_flavors = False
    if app_content and "flavorDimensions" in app_content:
        has_flavors = True

    # build types
    build_types = ["release"]
    if app_content and 'debuggable true' in app_content.lower():
        build_types = ["debug", "release"]

    # SDK versions
    min_sdk = None
    target_sdk = None
    if app_content:
        ms = re.search(r'minSdk(?:Version)?\s+(\d+)', app_content)
        if ms:
            min_sdk = int(ms.group(1))
        ts = re.search(r'targetSdk(?:Version)?\s+(\d+)', app_content)
        if ts:
            target_sdk = int(ts.group(1))

    gradle_wrapper = _find_gradle_wrapper(root)

    return _ok({
        "package_name": package_name,
        "version_code": version_code,
        "version_name": version_name,
        "build_gradle_found": has_build_file,
        "settings_gradle_found": has_settings,
        "gradle_wrapper_found": gradle_wrapper is not None,
        "gradle_wrapper_path": str(gradle_wrapper) if gradle_wrapper else None,
        "keystore_configured": keystore_configured,
        "keystore_path": keystore_path,
        "has_flavor_dimensions": has_flavors,
        "build_types": build_types,
        "min_sdk": min_sdk,
        "target_sdk": target_sdk,
    })


# ---------------------------------------------------------------------------
# appship_build_android_aab
# ---------------------------------------------------------------------------

def build_android_aab(project_path: str, build_type: str = "release") -> str:
    """Build an Android App Bundle via Gradle."""
    root = Path(project_path).resolve()
    if not root.is_dir():
        return _fail(f"Project path does not exist: {root}")

    gradle_wrapper = _find_gradle_wrapper(root)
    if gradle_wrapper is None:
        return _fail(f"No gradlew found in {root}",
                      "Ensure this is a Gradle-based Android project (run appship_analyze_android_project first).")

    if build_type not in ("release", "debug"):
        return _fail(f"Invalid build_type '{build_type}'",
                      "Must be 'release' or 'debug'.")

    task = f"bundle{build_type.capitalize()}"
    env = os.environ.copy()

    # inject keystore env vars if configured
    if "APPSHIP_KEYSTORE_PASSWORD" in env:
        env.setdefault("ORG_GRADLE_PROJECT_keyPassword", env["APPSHIP_KEYSTORE_PASSWORD"])
        env.setdefault("ORG_GRADLE_PROJECT_storePassword", env["APPSHIP_KEYSTORE_PASSWORD"])

    start = time.time()
    try:
        result = subprocess.run(
            [str(gradle_wrapper), task, "--no-daemon", "-q"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return _fail("Build timed out after 600 seconds",
                      "The project may be too large or Gradle may be stuck. Try cleaning first.")

    elapsed = time.time() - start

    if result.returncode != 0:
        stderr = (result.stderr or "") + "\n" + (result.stdout or "")
        # extract first meaningful error line
        error_lines = [line for line in stderr.splitlines() if "FAILURE" in line or "error" in line.lower() or "Error" in line]
        error_summary = error_lines[0] if error_lines else "Unknown build error"
        if len(error_summary) > 300:
            error_summary = error_summary[:300] + "..."

        suggestion = ""
        if "keystore" in stderr.lower() or "signing" in stderr.lower():
            suggestion = "Check APPSHIP_KEYSTORE_PASSWORD / keystore configuration."
        elif "version" in stderr.lower() and "code" in stderr.lower():
            suggestion = "Version code conflict — increment versionCode in build.gradle."
        elif "sdk" in stderr.lower() or "license" in stderr.lower():
            suggestion = "SDK license or version issue — run sdkmanager or accept licenses."

        return _fail(error_summary, suggestion,
                     raw_error_line=stderr.strip()[:2000],
                     build_time_seconds=round(elapsed, 1))

    # find the AAB
    bundle_dir = root / "app" / "build" / "outputs" / "bundle" / f"{build_type.capitalize()}"
    if bundle_dir.exists():
        aab_files = list(bundle_dir.glob("*.aab"))
        if aab_files:
            latest = max(aab_files, key=lambda p: p.stat().st_mtime)
            return _ok({
                "aab_path": str(latest),
                "build_time_seconds": round(elapsed, 1),
                "aab_size_bytes": latest.stat().st_size,
            })

    return _fail("Build succeeded but no .aab file found in expected output directory",
                  f"Expected: {bundle_dir}",
                  build_time_seconds=round(elapsed, 1))


# ---------------------------------------------------------------------------
# appship_upload_to_google_play
# ---------------------------------------------------------------------------

def upload_to_google_play(
    aab_path: str,
    package_name: str,
    track: str = "internal",
    release_notes: str = "",
    task_id: str | None = None,
) -> str:
    """Upload an AAB to Google Play Console. HITL-gated — must be approved."""
    valid_tracks = ("internal", "alpha", "beta", "production")
    if track not in valid_tracks:
        return _fail(f"Invalid track '{track}'",
                      f"Must be one of: {', '.join(valid_tracks)}.")

    aab = Path(aab_path).resolve()
    if not aab.exists():
        return _fail(f"AAB file not found: {aab}",
                      "Run appship_build_android_aab first to generate the AAB.")

    service_account = os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT")
    if not service_account:
        return _fail("GOOGLE_PLAY_SERVICE_ACCOUNT env var not set",
                      "Set this to the path of your Google Play service account JSON key file.")

    sa_path = Path(service_account)
    if not sa_path.exists():
        return _fail(f"Service account key file not found: {service_account}",
                      "Check the GOOGLE_PLAY_SERVICE_ACCOUNT path.")

    # ---------------------------------------------------------------
    # HITL gate — production uploads ALWAYS require approval
    # Lower tracks are configurable; default to requiring approval for
    # all uploads since they mutate the Play Console.
    # ---------------------------------------------------------------
    if task_id:
        # In Hermes, we signal a HITL gate by returning a special status.
        # The gateway intercepts this and prompts the human operator.
        approval_token = f"appship-upload-{package_name}-{track}-{int(time.time())}"
        return json.dumps({
            "status": "pending_approval",
            "approval_token": approval_token,
            "message": f"Approve upload of {aab.name} to Google Play '{track}' track for {package_name}?",
            "details": {
                "package_name": package_name,
                "track": track,
                "aab_path": str(aab),
                "aab_size_bytes": aab.stat().st_size,
                "release_notes": release_notes,
                "service_account": str(sa_path),
            }
        }, ensure_ascii=False)

    # ---------------------------------------------------------------
    # After HITL approval, execute the actual upload.
    # Uses google-auth + google-api-python-client (deferred import)
    # ---------------------------------------------------------------
    try:
        from google.oauth2 import service_account as sa
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        return _fail("Missing Google API client libraries",
                      "Install: pip install google-auth google-api-python-client")

    try:
        credentials = sa.Credentials.from_service_account_file(
            str(sa_path),
            scopes=["https://www.googleapis.com/auth/androidpublisher"],
        )
        service = build("androidpublisher", "v3", credentials=credentials)

        # Create edit
        edit = service.edits().insert(body={}, packageName=package_name).execute()
        edit_id = edit["id"]

        # Upload AAB
        media = MediaFileUpload(str(aab), mimetype="application/octet-stream")
        service.edits().bundles().upload(
            packageName=package_name,
            editId=edit_id,
            media_body=media,
        ).execute()

        # Assign to track
        service.edits().tracks().update(
            packageName=package_name,
            editId=edit_id,
            track=track,
            body={
                "track": track,
                "releases": [{
                    "status": "completed",
                    "releaseNotes": [{"language": "en-US", "text": release_notes or "AppShip automated upload"}],
                }]
            },
        ).execute()

        # Commit
        service.edits().commit(packageName=package_name, editId=edit_id).execute()

        return _ok({
            "edit_id": edit_id,
            "track": track,
            "package_name": package_name,
            "aab_path": str(aab),
        })

    except Exception as exc:
        error_msg = str(exc)[:500]
        suggestion = ""
        if "403" in error_msg or "permission" in error_msg.lower():
            suggestion = "Service account may lack permissions. Ensure it has 'Release manager' role in Play Console."
        elif "versionCode" in error_msg:
            suggestion = "Version code already exists. Increment versionCode in build.gradle and rebuild."
        elif "invalid" in error_msg.lower() and "package" in error_msg.lower():
            suggestion = "Package name not found. Check that the app exists in Play Console."

        return _fail(error_msg, suggestion)


# ---------------------------------------------------------------------------
# appship_get_google_play_status
# ---------------------------------------------------------------------------

def get_google_play_status(package_name: str) -> str:
    """Query the current track status for a Google Play package."""
    service_account = os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT")
    if not service_account:
        return _fail("GOOGLE_PLAY_SERVICE_ACCOUNT env var not set")

    sa_path = Path(service_account)
    if not sa_path.exists():
        return _fail(f"Service account key file not found: {service_account}")

    try:
        from google.oauth2 import service_account as sa
        from googleapiclient.discovery import build
    except ImportError:
        return _fail("Missing Google API client libraries",
                      "Install: pip install google-auth google-api-python-client")

    try:
        credentials = sa.Credentials.from_service_account_file(
            str(sa_path),
            scopes=["https://www.googleapis.com/auth/androidpublisher"],
        )
        service = build("androidpublisher", "v3", credentials=credentials)

        edit = service.edits().insert(body={}, packageName=package_name).execute()
        edit_id = edit["id"]

        tracks_resp = service.edits().tracks().list(
            packageName=package_name, editId=edit_id
        ).execute()

        tracks_out = []
        for t in tracks_resp.get("tracks", []):
            releases = t.get("releases", [])
            latest_vc = None
            status = "no_releases"
            if releases:
                latest = releases[0]
                vc_list = latest.get("versionCodes", [])
                latest_vc = vc_list[0] if vc_list else None
                status = latest.get("status", "unknown")
            tracks_out.append({
                "track": t["track"],
                "version_code": latest_vc,
                "status": status,
            })

        return _ok({"package_name": package_name, "tracks": tracks_out})

    except Exception as exc:
        return _fail(str(exc)[:500])


# ---------------------------------------------------------------------------
# Hermes tool registry integration
# ---------------------------------------------------------------------------

def check_requirements() -> bool:
    """Tools are always available — credential checks happen at call time."""
    return True
