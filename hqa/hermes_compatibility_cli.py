"""Fixed no-agent CLI for the post-update Hermes compatibility watcher."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from hqa.hermes_compatibility import (
    CompatibilityConfig,
    check_compatibility,
)


def _environment_config() -> CompatibilityConfig:
    hqa_repo = Path(
        os.environ.get(
            "HQA_HERMES_COMPAT_HQA_REPO",
            str(Path(__file__).resolve().parent.parent),
        )
    )
    home = Path.home()
    return CompatibilityConfig(
        hqa_repo=hqa_repo,
        platform_repo=Path(
            os.environ.get(
                "HQA_HERMES_COMPAT_PLATFORM_REPO",
                os.environ.get(
                    "HQA_AIQP_DIR", "/Users/sunyibo/programs/ai-quant-platform"
                ),
            )
        ),
        hermes_repo=Path(
            os.environ.get(
                "HQA_HERMES_COMPAT_HERMES_REPO",
                os.environ.get(
                    "HQA_HERMES_SOURCE_DIR",
                    str(home / ".hermes" / "hermes-agent"),
                ),
            )
        ),
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
    if args != ["check"]:
        print("usage: hqa-hermes-compatibility check", file=sys.stderr)
        return 2
    try:
        result = check_compatibility(_environment_config())
    except Exception:  # noqa: BLE001 - cron output must remain fail-closed and sanitized
        print(_summary("incompatible", None, None))
        return 2
    if not result.probed:
        return 0
    print(_summary(result.status, result.trigger_digest, result.report_digest))
    return 0 if result.status == "compatible" else 2


if __name__ == "__main__":
    raise SystemExit(main())
