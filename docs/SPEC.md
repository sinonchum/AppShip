# AppShip — Agent-Native App Store Distribution Plugin

> **Type**: Hermes Agent Skill / MCP Plugin  
> **Target**: Google Play Store (Phase 1) → App Store Connect → 国内安卓渠道  
> **Interaction**: LLM ↔ LLM (Agent calls via Function Calling / MCP)  
> **Governance**: HITL gates for destructive actions  
> **Status**: Spec Phase

## What It Is

AppShip is **not a human-facing CLI tool**. It is a set of atomic, schema-defined tools designed for an LLM Agent (Hermes, Codex, etc.) to call via function calling. The Agent reads structured JSON output, reasons about next steps, and optionally escalates to human approval.

## Design Principles

1. **Agent-native I/O**: All inputs/outputs are JSON-serializable. No progress bars, no interactive prompts.
2. **Atomic skills**: Each tool does one thing. The Agent composes them.
3. **Context-aware**: Outputs are filtered to fit LLM context windows (no raw Gradle dumps).
4. **HITL by default**: Upload, release promotion, and production mutations require human approval.
5. **MCP-first**: Skills are exposed as MCP tools with semantic descriptions.

## Skill Catalog (Phase 1 — Google Play)

### `appship_analyze_android_project`

**Purpose**: Let the Agent understand the project before acting.

| Field | Value |
|-------|-------|
| **Input** | `project_path: string` |
| **Output** | `{ package_name, version_code, version_name, build_gradle_found, keystore_path, keystore_configured }` |
| **Side effects** | None (read-only) |

### `appship_build_android_aab`

**Purpose**: Execute Gradle build, return AAB path or filtered errors.

| Field | Value |
|-------|-------|
| **Input** | `project_path: string`, `build_type: "release" | "debug"` |
| **Output** | `{ status: "success" | "failed", aab_path?: string, error_summary?: string, suggestion?: string }` |
| **Side effects** | Writes AAB to `build/outputs/` |
| **LLM context** | Error output is summarized — only the first error line + stack root cause |

### `appship_upload_to_google_play`

**Purpose**: Upload AAB to Play Console track. **HITL-gated.**

| Field | Value |
|-------|-------|
| **Input** | `aab_path: string`, `track: "internal" | "alpha" | "beta" | "production"`, `release_notes: string` |
| **Output** | `{ status: "approved" | "denied" | "success" | "failed", edit_id?: string, error_code?: string, suggestion?: string }` |
| **Side effects** | Creates Google Play Edit, uploads AAB |
| **HITL** | Requires human approval before upload |

### `appship_get_google_play_status`

**Purpose**: Check upload/edit status.

| Field | Value |
|-------|-------|
| **Input** | `package_name: string`, `edit_id?: string` |
| **Output** | `{ tracks: [...], latest_release: {...}, pending_changes: bool }` |
| **Side effects** | None (read-only) |

## Hermes Integration

Skills are defined as Hermes tools using the standard tool registry pattern:

```python
# tools/appship.py
registry.register(
    name="appship_analyze_android_project",
    toolset="appship",
    schema={
        "name": "appship_analyze_android_project",
        "description": "Analyze an Android project and return package name, version info, and signing configuration. Call this FIRST before building or uploading.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Absolute path to the Android project root (contains build.gradle or settings.gradle)"
                }
            },
            "required": ["project_path"]
        }
    },
    handler=lambda args, **kw: analyze_android_project(args["project_path"]),
    check_fn=lambda: True,
)
```

## HITL Flow

```
Agent calls upload → tool returns { status: "pending_approval", approval_token }
→ Hermes gateway prompts human: "Upload AAB to Google Play internal track?"
→ Human approves → tool proceeds
→ Human denies → tool returns { status: "denied" }
```

## Security

- **Google Play credentials**: Service account JSON, path via `GOOGLE_PLAY_SERVICE_ACCOUNT` env var
- **Keystore credentials**: Password via `APPSHIP_KEYSTORE_PASSWORD` env var
- **No credential logging**: Output redacts key paths and passwords
- **Approval audit**: Every HITL decision is recorded in Feiyue evidence

## Phase 1 Deliverables ✅ (COMPLETE — 2026-06-22)

- [x] AppShip Hermes skill (`hermes-assets/skills/devops/appship/SKILL.md`)
- [x] Python tool implementations in `src/appship/tools/`
- [x] Google Play Service Account setup guide
- [x] `appship_analyze_android_project` — working, tested
- [x] `appship_build_android_aab` — working, tested
- [x] `appship_upload_to_google_play` — working, tested (with HITL)
- [x] `appship_get_google_play_status` — working, tested
- [x] Feiyue evidence for each development phase
- [x] CI/CD: GitHub Actions (Python 3.10/11/12, ruff, pytest, PyPI trusted publishing)

## Phase 2 — Orchestration & iOS (IN PROGRESS)

### `appship_deploy_all`

**Purpose**: Single-command full pipeline orchestration across platforms.

| Field | Value |
|-------|-------|
| **Input** | `project_path: string`, `platform: "android" | "ios"`, `track: string`, `release_notes: string`, `task_id?: string` |
| **Output** | `{ status, platform, step, current_result, full_results? }` — returns at each step, HITL pauses at upload |
| **Side effects** | Chains analyze → build → upload → status |

### iOS — `appship_analyze_ios_project`

**Purpose**: Read Xcode project metadata.

| Field | Value |
|-------|-------|
| **Input** | `project_path: string` |
| **Output** | `{ bundle_id, version, build_number, min_ios_version, xcode_project_type, has_export_options, has_pods, has_spm }` |
| **Side effects** | None (read-only) |

### iOS — `appship_build_ios_ipa`

**Purpose**: Build and export iOS IPA via xcodebuild.

| Field | Value |
|-------|-------|
| **Input** | `project_path: string`, `scheme?: string`, `configuration?: string` |
| **Output** | `{ status, ipa_path, build_time_seconds, ipa_size_bytes }` |
| **Side effects** | Writes .xcarchive and .ipa |

### iOS — `appship_upload_to_app_store`

**Purpose**: Upload IPA to App Store Connect. **HITL-gated.**

| Field | Value |
|-------|-------|
| **Input** | `ipa_path: string`, `bundle_id: string`, API credentials, `task_id?: string` |
| **Output** | `{ status, altool_output, ... }` or `{ status: "pending_approval" }` |
| **Side effects** | Uploads to App Store Connect |
| **Auth** | JWT (ES256) via App Store Connect API key (.p8) |

### iOS — `appship_get_app_store_status`

**Purpose**: Query App Store Connect for app status.

| Field | Value |
|-------|-------|
| **Input** | `bundle_id: string`, API credentials |
| **Output** | `{ bundle_id, found, app_id, name, version_state, ... }` |
| **Side effects** | None (read-only) |

### Phase 2 Deliverables

- [x] `appship_deploy_all` — working, tested (7 tests)
- [x] `appship_analyze_ios_project` — working, tested (7 tests)
- [x] `appship_build_ios_ipa` — working, tested (11 tests)
- [x] `appship_upload_to_app_store` — working, tested (4 tests, with HITL)
- [x] `appship_get_app_store_status` — working, tested (2 tests)
- [x] Feiyue evidence

## Phase 3 (future)

- 国内安卓渠道 (华为、小米…)
- `appship_deploy_all` multi-platform fan-out
- TestFlight promotion workflow
