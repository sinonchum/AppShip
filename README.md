# AppShip

> Agent-native app store distribution — Google Play, App Store, 国内安卓渠道.
> Built as a Hermes Agent Skill.

## Status

📋 **Spec Phase** — Architecture defined, implementation pending.

## Quick Preview (Agent Perspective)

```
Developer: "Build and upload this Android project to Google Play internal track."

Agent calls:
  → appship_analyze_android_project(project_path="/app")
    ← { package_name: "com.example", version_code: 16, ... }

  → appship_build_android_aab(project_path="/app", build_type="release")
    ← { status: "success", aab_path: "/app/build/outputs/app-release.aab" }

  → appship_upload_to_google_play(
      aab_path="/app/build/outputs/app-release.aab",
      track="internal",
      release_notes="Fix login crash"
    )
    ← [HITL: Human approves]
    ← { status: "success", edit_id: "abc123" }

Agent: "Done. Uploaded to Google Play internal track."
```

## Architecture

See [SPEC.md](docs/SPEC.md) for full architecture and skill definitions.

## Skills

| Skill | Purpose | HITL |
|-------|---------|------|
| `appship_analyze_android_project` | Read project metadata | — |
| `appship_build_android_aab` | Build Android App Bundle | — |
| `appship_upload_to_google_play` | Upload to Play Console tracks | ✅ |
| `appship_get_google_play_status` | Check track/release status | — |

## Setup

```bash
# Install
pip install -e .

# Configure
export GOOGLE_PLAY_SERVICE_ACCOUNT=/path/to/service-account.json
export APPSHIP_KEYSTORE_PASSWORD=xxx
```

## License

MIT
