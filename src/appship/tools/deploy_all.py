"""AppShip deploy_all orchestration — full pipeline from analysis to store status.

Runs the complete deploy chain: analyze → build → upload (HITL-gated) → status.
Supports Android (Google Play) and iOS (App Store, deferred import).
"""

from __future__ import annotations

import json
from typing import Any

from appship.tools.appship_tools import (
    analyze_android_project,
    build_android_aab,
    get_google_play_status,
    upload_to_google_play,
)


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def deploy_all(
    project_path: str,
    platform: str = "android",
    track: str = "internal",
    release_notes: str = "",
    task_id: str | None = None,
) -> str:
    """Orchestrate the full deploy pipeline: analyze → build → upload → status.

    Args:
        project_path: Path to the project root directory.
        platform: Target platform — 'android' or 'ios'.
        track: Release track (internal, alpha, beta, production).
        release_notes: Release notes text.
        task_id: Optional Hermes task ID — triggers HITL approval gate on upload.

    Returns:
        JSON string with status, platform, step, current_result, and
        full_results (on final success only).
    """
    if platform == "android":
        return _deploy_android(project_path, track, release_notes, task_id)
    elif platform == "ios":
        return _deploy_ios(project_path, track, release_notes, task_id)
    else:
        return _fail(
            f"Unknown platform: '{platform}'",
            "Use 'android' or 'ios'.",
            platform=platform,
            step="analyze",
        )


# ---------------------------------------------------------------------------
# android pipeline
# ---------------------------------------------------------------------------


def _deploy_android(
    project_path: str,
    track: str,
    release_notes: str,
    task_id: str | None,
) -> str:
    full_results: dict[str, Any] = {}

    # --- Step 1: Analyze ---
    analyze_result = json.loads(analyze_android_project(project_path))
    if analyze_result.get("status") != "ok":
        return _step_error("analyze", platform="android", current_result=analyze_result)
    full_results["analyze"] = analyze_result

    package_name = analyze_result.get("package_name", "")

    # --- Step 2: Build ---
    build_result = json.loads(build_android_aab(project_path))
    if build_result.get("status") != "ok":
        return _step_error("build", platform="android", current_result=build_result)
    full_results["build"] = build_result

    aab_path = build_result.get("aab_path", "")

    # --- Step 3: Upload (HITL-gated) ---
    upload_result = json.loads(
        upload_to_google_play(aab_path, package_name, track, release_notes, task_id)
    )
    if upload_result.get("status") == "pending_approval":
        full_results["upload"] = upload_result
        return _pending_approval("upload", platform="android", current_result=upload_result)
    if upload_result.get("status") != "ok":
        return _step_error("upload", platform="android", current_result=upload_result)
    full_results["upload"] = upload_result

    # --- Step 4: Status ---
    status_result = json.loads(get_google_play_status(package_name))
    full_results["status"] = status_result

    return json.dumps({
        "status": status_result.get("status", "ok"),
        "platform": "android",
        "step": "complete",
        "current_result": status_result,
        "full_results": full_results,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# ios pipeline (deferred import — not yet available)
# ---------------------------------------------------------------------------


def _deploy_ios(
    project_path: str,
    track: str,
    release_notes: str,
    task_id: str | None,
) -> str:
    try:
        from appship.tools.ios_tools import (  # type: ignore[import-not-found]  # noqa: F811
            analyze_ios_project,
            build_ios_ipa,
            get_app_store_status,
            upload_to_app_store,
        )
    except ImportError as exc:
        return json.dumps({
            "status": "failed",
            "platform": "ios",
            "step": "analyze",
            "current_result": {
                "status": "failed",
                "error_summary": f"iOS tools are not yet available: {exc}",
                "suggestion": "iOS App Store distribution is not yet implemented. "
                              "Android (Google Play) is fully supported.",
            },
        }, ensure_ascii=False)

    full_results: dict[str, Any] = {}

    # --- Step 1: Analyze ---
    analyze_result = json.loads(analyze_ios_project(project_path))
    if analyze_result.get("status") != "ok":
        return _step_error("analyze", platform="ios", current_result=analyze_result)
    full_results["analyze"] = analyze_result

    # --- Step 2: Build ---
    build_result = json.loads(build_ios_ipa(project_path))
    if build_result.get("status") != "ok":
        return _step_error("build", platform="ios", current_result=build_result)
    full_results["build"] = build_result

    ipa_path = build_result.get("ipa_path", "")
    bundle_id = analyze_result.get("bundle_id", "")

    # --- Step 3: Upload (HITL-gated) ---
    upload_result = json.loads(
        upload_to_app_store(ipa_path, bundle_id, track, release_notes, task_id)
    )
    if upload_result.get("status") == "pending_approval":
        full_results["upload"] = upload_result
        return _pending_approval("upload", platform="ios", current_result=upload_result)
    if upload_result.get("status") != "ok":
        return _step_error("upload", platform="ios", current_result=upload_result)
    full_results["upload"] = upload_result

    # --- Step 4: Status ---
    status_result = json.loads(get_app_store_status(bundle_id))
    full_results["status"] = status_result

    return json.dumps({
        "status": status_result.get("status", "ok"),
        "platform": "ios",
        "step": "complete",
        "current_result": status_result,
        "full_results": full_results,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# result formatters
# ---------------------------------------------------------------------------


def _step_error(step: str, platform: str, current_result: dict[str, Any]) -> str:
    """Return a failed-at-step error JSON string."""
    return json.dumps({
        "status": "failed",
        "platform": platform,
        "step": step,
        "current_result": current_result,
    }, ensure_ascii=False)


def _pending_approval(step: str, platform: str, current_result: dict[str, Any]) -> str:
    """Return a pending_approval (HITL gate) JSON string."""
    return json.dumps({
        "status": "pending_approval",
        "platform": platform,
        "step": step,
        "current_result": current_result,
    }, ensure_ascii=False)


def _fail(error_summary: str, suggestion: str, **extra: Any) -> str:
    """Return a generic failure JSON string with extra fields."""
    return json.dumps({
        "status": "failed",
        "error_summary": error_summary,
        "suggestion": suggestion,
        **extra,
    }, ensure_ascii=False)
