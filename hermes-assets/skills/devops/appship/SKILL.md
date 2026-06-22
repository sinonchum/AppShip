---
name: appship
description: "Agent-native Google Play Store distribution — analyze, build, upload AABs via Hermes function calling"
version: 0.1.0
author: AppShip
platforms: [windows, linux, macos]
tags: [android, google-play, deployment, cicd]
---

# AppShip — Google Play Store Distribution

AppShip exposes atomic, schema-defined tools for an LLM Agent to build and
upload Android App Bundles to Google Play Console. Each tool returns
structured JSON suitable for agent reasoning with no human-facing UI.

## Usage (Agent Perspective)

The Agent receives these tools in its function-calling schema and
composes them:

```
1. Call appship_analyze_android_project first — get package name, version, keystore info
2. Call appship_build_android_aab — build the App Bundle
3. Call appship_upload_to_google_play — upload to a track (HITL-gated)
4. Call appship_get_google_play_status — verify the upload
```

## Tools

### `appship_analyze_android_project`

Analyzes an Android project directory and returns metadata.

**Input:**
- `project_path` (string, required): Absolute path to Android project root

**Output:**
```json
{
  "status": "ok",
  "package_name": "com.example.app",
  "version_code": 16,
  "version_name": "1.2.3",
  "build_gradle_found": true,
  "keystore_configured": true,
  "keystore_path": "/path/to/keystore.jks",
  "has_flavor_dimensions": false,
  "build_types": ["debug", "release"],
  "min_sdk": 24,
  "target_sdk": 34
}
```

### `appship_build_android_aab`

Builds an Android App Bundle via Gradle.

**Input:**
- `project_path` (string, required): Absolute path to Android project root
- `build_type` (string, optional, default "release"): "release" | "debug"

**Output:**
```json
{
  "status": "success",
  "aab_path": "/project/build/outputs/bundle/release/app-release.aab",
  "build_time_seconds": 42,
  "version_code": 16
}
```

On failure:
```json
{
  "status": "failed",
  "error_summary": "Execution failed for task ':app:signReleaseBundle'",
  "suggestion": "Keystore password may be incorrect. Check APPSHIP_KEYSTORE_PASSWORD env var.",
  "raw_error_line": "..."
}
```

### `appship_upload_to_google_play`

Uploads an AAB to Google Play Console. **Requires human approval (HITL).**

**Input:**
- `aab_path` (string, required): Absolute path to the AAB file
- `package_name` (string, required): Android package name
- `track` (string, required): "internal" | "alpha" | "beta" | "production"
- `release_notes` (string, optional): Release notes for the track

**Output:**
```json
{
  "status": "success",
  "edit_id": "1234567890",
  "track": "internal",
  "version_code": 16
}
```

On HITL denied:
```json
{
  "status": "denied",
  "reason": "operator_denied_upload"
}
```

### `appship_get_google_play_status`

Checks the status of tracks and releases for a package.

**Input:**
- `package_name` (string, required): Android package name

**Output:**
```json
{
  "package_name": "com.example.app",
  "tracks": [
    {"track": "internal", "version_code": 16, "status": "available"}
  ]
}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_PLAY_SERVICE_ACCOUNT` | Yes (upload) | Path to service account JSON key file |
| `APPSHIP_KEYSTORE_PASSWORD` | No | Keystore password for signing (can also read from project config) |
| `APPSHIP_KEY_ALIAS` | No | Key alias for signing |
| `APPSHIP_KEY_PASSWORD` | No | Key password for signing |

## Security

- All credentials are read from environment variables — never hardcoded
- Upload operations require HITL approval via Hermes gateway
- Output redacts credential values and key paths
- No telemetry or data collection

## Installation

```bash
pip install -e /path/to/AppShip
```

Then register as a Hermes toolset — the tools are auto-discovered.
