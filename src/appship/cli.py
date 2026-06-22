"""AppShip CLI — command-line wrapper for the agent-native tools.

Usage:
    appship analyze /path/to/android/project
    appship build /path/to/android/project [--debug]
    appship upload /path/to/app.aab com.example.app [--track internal]
    appship status com.example.app
"""

from __future__ import annotations

import argparse
import sys

from appship.tools.appship_tools import (
    analyze_android_project,
    build_android_aab,
    get_google_play_status,
    upload_to_google_play,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="appship",
        description="Agent-native app store distribution — Google Play first",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # analyze
    p_analyze = sub.add_parser("analyze", help="Analyze an Android project")
    p_analyze.add_argument("project_path", help="Path to Android project root")

    # build
    p_build = sub.add_parser("build", help="Build Android App Bundle")
    p_build.add_argument("project_path", help="Path to Android project root")
    p_build.add_argument("--debug", action="store_true", help="Build debug variant")

    # upload
    p_upload = sub.add_parser("upload", help="Upload AAB to Google Play (HITL-gated)")
    p_upload.add_argument("aab_path", help="Path to the .aab file")
    p_upload.add_argument("package_name", help="Android package name")
    p_upload.add_argument("--track", default="internal",
                           choices=["internal", "alpha", "beta", "production"])
    p_upload.add_argument("--release-notes", default="", help="Release notes")

    # status
    p_status = sub.add_parser("status", help="Check Google Play track status")
    p_status.add_argument("package_name", help="Android package name")

    args = parser.parse_args()

    if args.command == "analyze":
        print(analyze_android_project(args.project_path))
    elif args.command == "build":
        build_type = "debug" if args.debug else "release"
        print(build_android_aab(args.project_path, build_type))
    elif args.command == "upload":
        print(upload_to_google_play(args.aab_path, args.package_name, args.track, args.release_notes))
    elif args.command == "status":
        print(get_google_play_status(args.package_name))


if __name__ == "__main__":
    main()
