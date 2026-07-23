"""No-agent CLI for the post-update Hermes compatibility watcher.

Exit codes: 0 compatible/unchanged/busy, 2 usage, 3 contract drift, and
4 watcher/configuration unavailable.  No code path starts an agent.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Sequence

from hqa.hermes_compatibility import (
    CompatibilityConfig,
    check_compatibility,
)


@dataclass(frozen=True)
class _Arguments:
    profile: str
    platform_root: Optional[Path]
    explicit_no_agent: bool


def _parse_arguments(args: Sequence[str]) -> _Arguments:
    if list(args) == ["check"]:
        # Backward-compatible dark read-only operator check. The installed
        # Hermes cron wrapper uses the stronger explicit form below.
        return _Arguments("dark_readonly", None, False)
    if not args or args[0] != "check":
        raise ValueError("usage")
    profile: Optional[str] = None
    platform_root: Optional[Path] = None
    explicit_no_agent = False
    index = 1
    while index < len(args):
        argument = args[index]
        if argument == "--no-agent" and not explicit_no_agent:
            explicit_no_agent = True
            index += 1
            continue
        if argument == "--profile" and profile is None and index + 1 < len(args):
            profile = args[index + 1]
            index += 2
            continue
        if (
            argument == "--platform-root"
            and platform_root is None
            and index + 1 < len(args)
        ):
            candidate = Path(args[index + 1])
            if not candidate.is_absolute():
                raise ValueError("usage")
            platform_root = candidate
            index += 2
            continue
        raise ValueError("usage")
    if profile not in {"dark_readonly", "local_agent_v0_2"}:
        raise ValueError("usage")
    if profile == "local_agent_v0_2" and (
        not explicit_no_agent or platform_root is None
    ):
        raise ValueError("usage")
    return _Arguments(profile, platform_root, explicit_no_agent)


def _environment_config(arguments: _Arguments) -> CompatibilityConfig:
    hqa_repo = Path(
        os.environ.get(
            "HQA_HERMES_COMPAT_HQA_REPO",
            str(Path(__file__).resolve().parent.parent),
        )
    )
    home = Path.home()
    platform_repo = arguments.platform_root or Path(
        os.environ.get(
            "HQA_HERMES_COMPAT_PLATFORM_REPO",
            os.environ.get(
                "HQA_AIQP_DIR", "/Users/sunyibo/programs/ai-quant-platform"
            ),
        )
    )
    api_key_setting = os.environ.get("HQA_HERMES_COMPAT_HERMES_API_KEY_FILE")
    default_api_key = hqa_repo / "data" / "_runtime" / "hermes-api.key"
    api_key_file = (
        Path(api_key_setting)
        if api_key_setting
        else (default_api_key if default_api_key.is_file() else None)
    )
    return CompatibilityConfig(
        hqa_repo=hqa_repo,
        platform_repo=platform_repo,
        hermes_repo=Path(
            os.environ.get(
                "HQA_HERMES_COMPAT_HERMES_REPO",
                os.environ.get(
                    "HQA_HERMES_SOURCE_DIR",
                    str(home / ".hermes" / "hermes-agent"),
                ),
            )
        ),
        profile=arguments.profile,
        state_dir=Path(
            os.environ.get(
                "HQA_HERMES_COMPAT_STATE_DIR",
                str(hqa_repo / "data" / "_runtime" / "hermes-compatibility"),
            )
        ),
        hermes_base_url=os.environ.get(
            "HQA_HERMES_COMPAT_HERMES_URL", "http://127.0.0.1:8642"
        ),
        platform_base_url=os.environ.get(
            "HQA_HERMES_COMPAT_PLATFORM_URL", "http://127.0.0.1:8765"
        ),
        hermes_cli_path=Path(
            os.environ.get(
                "HQA_HERMES_COMPAT_HERMES_CLI",
                str(home / ".local" / "bin" / "hermes"),
            )
        ),
        hermes_api_key_file=api_key_file,
    )


def _summary(
    status: str, trigger_digest: Optional[str], report_digest: Optional[str]
) -> str:
    return json.dumps(
        {
            "trigger_digest": trigger_digest,
            "report_digest": report_digest,
            "status": status,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        parsed = _parse_arguments(args)
    except ValueError:
        print(
            "usage: hqa-hermes-compatibility check "
            "[--no-agent --profile PROFILE --platform-root ABSOLUTE_PATH]",
            file=sys.stderr,
        )
        return 2
    try:
        result = check_compatibility(_environment_config(parsed))
    except Exception:  # noqa: BLE001 - cron output must remain fail-closed and sanitized
        print(_summary("error", None, None))
        return 4
    if not result.probed:
        return 0
    print(_summary(result.status, result.trigger_digest, result.report_digest))
    return 0 if result.status == "compatible" else 3


if __name__ == "__main__":
    raise SystemExit(main())
