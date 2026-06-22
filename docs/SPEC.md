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

## Phase 1 Deliverables

- [ ] AppShip Hermes skill (`hermes-assets/skills/devops/appship/SKILL.md`)
- [ ] Python tool implementations in `src/appship/tools/`
- [ ] Google Play Service Account setup guide
- [ ] `appship_analyze_android_project` — working, tested
- [ ] `appship_build_android_aab` — working, tested
- [ ] `appship_upload_to_google_play` — working, tested (with HITL)
- [ ] `appship_get_google_play_status` — working, tested
- [ ] Feiyue evidence for each development phase

## Phase 2 (future)

- iOS App Store Connect skills
- `appship_deploy_all` orchestration skill
- 国内安卓渠道 (华为、小米…)
