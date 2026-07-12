from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _install(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = dict(os.environ, HOME=str(fake_home), HERMES_HOME=str(fake_home / ".hermes"))
    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert result.returncode == 0, result.stdout
    return fake_home / ".hermes" / "scripts"


def test_install_copies_physical_executable_wrappers(tmp_path):
    dest = _install(tmp_path)
    names = sorted(p.name for p in dest.glob("hqa-*.sh"))
    assert names == [
        "hqa-aihot-alerts.sh",
        "hqa-artifacts.sh",
        "hqa-doctor-watchdog.sh",
        "hqa-market-foresight.sh",
        "hqa-notify.sh",
        "hqa-opportunities.sh",
        "hqa-options-collect.sh",
        "hqa-options-radar.sh",
        "hqa-portfolio-risk.sh",
        "hqa-prediction.sh",
        "hqa-premarket-digest.sh",
        "hqa-quant-readonly.sh",
        "hqa-signal-watchdog.sh",
        "hqa-weekly-review.sh",
    ]
    for wrapper in dest.glob("hqa-*.sh"):
        assert not wrapper.is_symlink()  # physical file (symlink would be blocked)
        assert os.access(wrapper, os.X_OK)  # executable
        body = wrapper.read_text()
        # Every wrapper launches a real program — an hqa Python module
        # (digest/watchdog), the platform quant-system CLI (collect/gate), or
        # the hermes messaging CLI (notify). No stubs.
        assert (
            "python3 -m hqa." in body or "quant-system" in body or "hermes send" in body
        )


def test_wrappers_pass_hermes_escape_check(tmp_path):
    # Replicate cron/scheduler.py: script must resolve INSIDE the scripts dir.
    dest = _install(tmp_path)
    scripts_dir_resolved = dest.resolve()
    for name in (
        "hqa-aihot-alerts.sh",
        "hqa-artifacts.sh",
        "hqa-doctor-watchdog.sh",
        "hqa-market-foresight.sh",
        "hqa-notify.sh",
        "hqa-options-collect.sh",
        "hqa-opportunities.sh",
        "hqa-options-radar.sh",
        "hqa-portfolio-risk.sh",
        "hqa-prediction.sh",
        "hqa-premarket-digest.sh",
        "hqa-quant-readonly.sh",
        "hqa-signal-watchdog.sh",
        "hqa-weekly-review.sh",
    ):
        resolved = (scripts_dir_resolved / name).resolve()
        # raises ValueError (⇒ test failure) if the path escapes the scripts dir
        resolved.relative_to(scripts_dir_resolved)


def test_symlink_would_be_blocked_by_escape_check(tmp_path):
    # Negative case: a symlink inside the scripts dir resolves OUTSIDE it,
    # so Hermes' relative_to(scripts_dir) check raises ValueError (job blocked).
    scripts_dir = tmp_path / ".hermes" / "scripts"
    scripts_dir.mkdir(parents=True)
    outside = tmp_path / "outside.sh"
    outside.write_text("#!/bin/bash\n")
    (scripts_dir / "evil.sh").symlink_to(outside)
    scripts_dir_resolved = scripts_dir.resolve()
    resolved = (scripts_dir_resolved / "evil.sh").resolve()
    with pytest.raises(ValueError):
        resolved.relative_to(scripts_dir_resolved)


def test_deployed_wrappers_have_no_unsubstituted_placeholders(tmp_path):
    # Regression guard: install.sh MUST sed-substitute the __HQA_REPO_DIR__ and
    # __HQA_PLATFORM_DIR__ placeholders. If install.sh were ever regressed to a
    # plain `cp` (exit 0, no substitution), the deployed wrappers would be dead
    # at runtime (cd to a literal "__HQA_REPO_DIR__" dir fails under
    # `set -euo pipefail`). This test locks in the sed substitution.
    dest = _install(tmp_path)
    for wrapper in dest.glob("hqa-*.sh"):
        body = wrapper.read_text()
        assert "__HQA_REPO_DIR__" not in body, (
            f"{wrapper.name}: unsubstituted __HQA_REPO_DIR__ placeholder remains"
        )
        assert "__HQA_PLATFORM_DIR__" not in body, (
            f"{wrapper.name}: unsubstituted __HQA_PLATFORM_DIR__ placeholder remains"
        )


def test_python_wrappers_use_install_time_repo_placeholder():
    for name in (
        "hqa-aihot-alerts.sh",
        "hqa-artifacts.sh",
        "hqa-doctor-watchdog.sh",
        "hqa-market-foresight.sh",
        "hqa-opportunities.sh",
        "hqa-options-radar.sh",
        "hqa-portfolio-risk.sh",
        "hqa-prediction.sh",
        "hqa-premarket-digest.sh",
        "hqa-signal-watchdog.sh",
        "hqa-weekly-review.sh",
    ):
        body = (REPO / "scripts" / "hermes" / name).read_text(encoding="utf-8")
        assert "cd __HQA_REPO_DIR__" in body


# --- D-25 read-only gate wrapper -------------------------------------------

READONLY_SRC = REPO / "scripts" / "hermes" / "hqa-quant-readonly.sh"


def _build_gate(tmp_path):
    """Materialise the gate wrapper against a stub platform CLI that echoes
    its argv, so tests can assert both the allow (argv construction) and the
    refuse (exit 2, no exec) paths without touching the real quant-system."""
    platform = tmp_path / "platform"
    bindir = platform / "ai-quant" / "bin"
    bindir.mkdir(parents=True)
    stub = bindir / "quant-system"
    stub.write_text(
        "#!/bin/bash\nprintf 'ARGV'\nfor a in \"$@\"; do printf '|%s' \"$a\"; done\n"
        "printf '\\n'\n"
    )
    stub.chmod(0o755)
    body = READONLY_SRC.read_text().replace("__HQA_PLATFORM_DIR__", str(platform))
    gate = tmp_path / "hqa-quant-readonly.sh"
    gate.write_text(body)
    gate.chmod(0o755)
    return gate


def _run_gate(tmp_path, args):
    gate = _build_gate(tmp_path)
    return subprocess.run(
        ["bash", str(gate), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@pytest.mark.parametrize(
    "args, expected_argv",
    [
        (["doctor"], "ARGV|doctor"),
        (["config", "show"], "ARGV|config|show"),
        (["factor", "list"], "ARGV|factor|list"),
        (
            [
                "data",
                "prices",
                "--symbol",
                "AAPL",
                "--start",
                "2026-01-01",
                "--end",
                "2026-07-10",
                "--provider",
                "futu",
            ],
            "ARGV|data|prices|--symbol|AAPL|--start|2026-01-01|--end|2026-07-10|--provider|futu",
        ),
        (
            ["paper", "account-show", "--account", "main", "--format", "json"],
            "ARGV|paper|account-show|--account|main|--format|json",
        ),
        (["agent", "list-candidates"], "ARGV|agent|list-candidates"),
    ],
)
def test_gate_allows_readonly_commands(tmp_path, args, expected_argv):
    result = _run_gate(tmp_path, args)
    assert result.returncode == 0, result.stderr
    # Argv is forwarded verbatim (trailing flags preserved) to the platform CLI.
    assert result.stdout.strip() == expected_argv


@pytest.mark.parametrize(
    "args",
    [
        [],  # empty → refused
        ["paper", "rebalance"],  # write: mutates account
        ["paper", "run-sample"],  # write: runs a loop
        ["agent", "review", "--approve"],  # write: approval lock
        ["agent", "propose-factor"],  # write: creates candidate file
        ["options", "daily-scan"],  # write: scan snapshot (audit F4)
        ["options", "daily-scan", "--top", "20"],
        ["options", "buyside-screen"],  # write: scan side-effect
        ["options", "daily-task"],  # refreshes inputs (side effect)
        ["options", "prune-cache", "--delete"],  # deletes cache
        ["data", "ingest-tiingo"],  # write: downloads + stores
        ["data", "ingest-sample"],  # write: generates + stores
        ["backtest", "run-sample"],  # compute/write
        ["config"],  # bare group, not the `config show` leaf
        ["options"],  # bare group
        ["doctor; rm -rf /"],  # injection as single token, no match
        ["serve"],  # starts a server
        ["totally-unknown"],
    ],
)
def test_gate_refuses_non_allowlisted(tmp_path, args):
    result = _run_gate(tmp_path, args)
    assert result.returncode == 2
    assert "REFUSED: not in read-only allowlist" in result.stderr
    # Stub CLI must never have been exec'd on the refuse path.
    assert "ARGV" not in result.stdout


def test_gate_source_declares_readonly_allowlist():
    # Lock the verified read-only set into the script source. Every entry was
    # confirmed side-effect-free via `quant-system <cmd> --help`; adding a
    # write command here should require an explicit, reviewed change.
    # Audit F4: options daily-scan / buyside-screen must NOT be allowlisted.
    body = READONLY_SRC.read_text()
    for entry in (
        '"doctor"',
        '"config show"',
        '"data prices"',
        '"factor list"',
        '"paper account-show"',
        '"agent list-candidates"',
    ):
        assert entry in body
    assert '"options daily-scan"' not in body
    assert '"options buyside-screen"' not in body


# --- D-25 HQA skill card ----------------------------------------------------

SKILL_SRC = REPO / "skills" / "hermes" / "hqa-quant" / "SKILL.md"
# The read-write CLIs the card documents; every `-m hqa.<mod>` template must
# name one of these (guards against invented modules).
_WRITE_PATH_MODULES = ("hqa.factor_repro_cli", "hqa.review_cli")
# Platform read-only subcommands baked into the gate allowlist (Task L1). Any
# gate template in the card must forward one of these — no invented commands.
_READONLY_SUBCOMMANDS = (
    "doctor",
    "config show",
    "data prices",
    "factor list",
    "paper account-show",
    "agent list-candidates",
)


def test_install_deploys_skill_card_with_substitution(tmp_path):
    # install.sh must also deploy skills/hermes/<name>/SKILL.md to
    # $HERMES_HOME/skills/<name>/SKILL.md with the repo/platform placeholders
    # replaced (same seam as the script wrappers).
    scripts_dest = _install(tmp_path)
    skill = scripts_dest.parent / "skills" / "hqa-quant" / "SKILL.md"
    assert skill.is_file(), "SKILL.md not deployed under $HERMES_HOME/skills/hqa-quant/"
    body = skill.read_text(encoding="utf-8")
    assert "__HQA_REPO_DIR__" not in body
    assert "__HQA_PLATFORM_DIR__" not in body
    # The gate wrapper is referenced by absolute deployed path, not placeholder.
    assert str(scripts_dest / "hqa-quant-readonly.sh") in body
    assert str(scripts_dest / "hqa-portfolio-risk.sh") in body
    assert str(scripts_dest / "hqa-prediction.sh") in body
    assert str(scripts_dest / "hqa-opportunities.sh") in body


def test_skill_card_frontmatter_mirrors_hermes_contract():
    body = SKILL_SRC.read_text(encoding="utf-8")
    assert body.startswith("---\n"), "SKILL.md must open with YAML frontmatter"
    front = body.split("---", 2)[1]
    assert re.search(r"^name:\s*hqa-quant\s*$", front, re.M)
    assert re.search(r"^description:\s*\S", front, re.M)
    assert re.search(r"^version:\s*1\.\d+\.\d+\s*$", front, re.M)
    # platforms must be a list containing macos.
    assert re.search(r"^platforms:\s*\[.*macos.*\]\s*$", front, re.M)
    # metadata.hermes.tags present with the quant/trading/hqa tags.
    assert re.search(r"^\s*hermes:\s*$", front, re.M)
    assert re.search(r"tags:\s*\[.*\bhqa\b.*\]", front)


def test_skill_card_uses_unified_paper_snapshot_json_contract():
    body = SKILL_SRC.read_text(encoding="utf-8")
    assert "paper account-show --account default --format json" in body


def test_skill_card_documents_strict_portfolio_risk_v2() -> None:
    body = SKILL_SRC.read_text(encoding="utf-8")
    lower = body.lower()

    assert "version: 1.7.0" in body
    assert "__HERMES_SCRIPTS_DIR__/hqa-portfolio-risk.sh" in body
    assert "logs/portfolio_risk.jsonl" in body
    assert "current snapshot" in lower
    assert "correlation" in lower and "beta" in lower
    assert "data prices" in lower
    assert "qfq" in lower
    assert "60" in lower and "inner join" in lower
    assert "no sample" in lower and "longbridge" in lower
    assert "no risk-policy threshold" in lower


def test_skill_card_documents_prediction_ledger_contract() -> None:
    body = SKILL_SRC.read_text(encoding="utf-8")
    lower = body.lower()

    assert "version: 1.7.0" in body
    assert "__HERMES_SCRIPTS_DIR__/hqa-prediction.sh" in body
    assert "create" in lower and "list" in lower and "reconcile" in lower
    assert "predictions/entries.jsonl" in body
    assert "binary brier" in lower
    assert "first" in lower and ">= horizon_date" in lower
    assert "no longbridge" in lower and "no sample" in lower
    assert "9h" in lower and "cron" in lower


def test_skill_card_documents_market_foresight_and_artifact_shelf() -> None:
    body = SKILL_SRC.read_text(encoding="utf-8")
    lower = body.lower()

    assert "version: 1.7.0" in body
    assert "__HERMES_SCRIPTS_DIR__/hqa-market-foresight.sh" in body
    assert "__HERMES_SCRIPTS_DIR__/hqa-artifacts.sh" in body
    assert "artifacts/hermes-feed/manifest.v1.json" in body
    assert "proposal_only" in lower
    assert "human-confirmed" in lower
    assert "composer" in lower and "not wired" in lower


def test_skill_card_documents_opportunity_ledger_contract() -> None:
    body = SKILL_SRC.read_text(encoding="utf-8")
    lower = body.lower()

    assert "version: 1.7.0" in body
    assert "__HERMES_SCRIPTS_DIR__/hqa-opportunities.sh" in body
    assert "opportunities/entries.jsonl" in body
    assert "sync-signals" in lower and "record-action" in lower
    assert "sync-actions" in lower and "reconcile" in lower
    assert "not_actionable" in lower and "expired_coverage_unknown" in lower
    assert "matching ticker is not causality" in lower
    assert "never invoke generate-signal" in lower


def test_skill_card_readonly_templates_use_gate_wrapper():
    # Every read-only command template must go through the single-command gate
    # wrapper (absolute path), never bare `quant-system` and never a compound
    # command (&&/|/;) that would bypass the Hermes allowlist shortcut.
    body = SKILL_SRC.read_text(encoding="utf-8")
    gate = "hqa-quant-readonly.sh"
    gate_lines = [
        ln
        for ln in body.splitlines()
        if gate in ln
        and ln.lstrip().startswith(("`", "|", "python3", "/", "bash", "$HERMES", "~/"))
    ]
    assert gate_lines, "no gate-wrapper command templates found in the card"
    for ln in gate_lines:
        # Extract the command text following the wrapper name, stripping the
        # markdown code-span backticks and any trailing table cell.
        after = ln.split(gate, 1)[1]
        cmd = after.split("|")[0].replace("`", "").strip()
        assert cmd, f"empty gate subcommand in: {ln!r}"
        first_two = " ".join(cmd.split()[:2])
        first_one = cmd.split()[0]
        assert (
            cmd in _READONLY_SUBCOMMANDS
            or first_two in _READONLY_SUBCOMMANDS
            or first_one in _READONLY_SUBCOMMANDS
        ), f"gate template forwards a non-allowlisted subcommand: {cmd!r}"


def test_skill_card_has_no_compound_operators_on_gate_lines():
    # Hermes command_allowlist glob matching is bypassed by &&/|/;/$( — the card
    # must teach single-command wrapper invocations only (plan line 20).
    body = SKILL_SRC.read_text(encoding="utf-8")
    for ln in body.splitlines():
        if "hqa-quant-readonly.sh" in ln and "```" not in ln:
            # A shell pipe inside a markdown table cell is fine ONLY as the table
            # delimiter; disallow actual shell compounding of the wrapper call.
            payload = ln.split("hqa-quant-readonly.sh", 1)[1]
            # Table cell ends at ` | `; inspect only the command up to that.
            cell = payload.split("|")[0]
            assert "&&" not in cell, f"compound && breaks allowlist: {ln!r}"
            assert ";" not in cell, f"compound ; breaks allowlist: {ln!r}"
            assert "$(" not in cell, f"cmd-subst breaks allowlist: {ln!r}"


def test_skill_card_write_templates_name_real_modules():
    # Read-write op templates must invoke real hqa modules via `python3 -m`.
    body = SKILL_SRC.read_text(encoding="utf-8")
    module_hits = re.findall(r"python3 -m (hqa\.[\w_]+)", body)
    assert module_hits, "no `python3 -m hqa.<mod>` write templates found"
    for mod in module_hits:
        assert mod in _WRITE_PATH_MODULES, f"unknown/invented module: {mod}"


def test_skill_card_covers_required_sections():
    body = SKILL_SRC.read_text(encoding="utf-8").lower()
    # (2) artifact-first — real log + scan paths.
    assert "logs/" in body
    assert "options_scans" in body
    # (3) 30s triage — background + run-id + notify push.
    assert "30" in body and "hqa-notify.sh" in body
    # (4) safety redlines — approval + kill_switch/paper_trading not bypassed.
    assert "approval" in body
    assert "kill_switch" in body or "kill switch" in body
    assert "paper_trading" in body or "paper trading" in body


def test_skill_card_documents_json_status_honestly():
    # doctor --json is supported and used by HQA's watchdog, but the skill
    # gate templates must still not invent --json on other platform leaves
    # (many still reject it). Card must also not claim doctor lacks --json.
    body = SKILL_SRC.read_text(encoding="utf-8")
    assert "doctor --json is supported" in body or "doctor --json` is supported" in body
    for ln in body.splitlines():
        if "hqa-quant-readonly.sh" in ln:
            cell = ln.split("hqa-quant-readonly.sh", 1)[1].split("|")[0]
            assert "--json" not in cell, (
                f"gate/platform template must not invent --json on unknown leaves: {ln!r}"
            )


def test_skill_card_does_not_list_scan_as_readonly():
    body = SKILL_SRC.read_text(encoding="utf-8")
    # Scan must not appear as a pre-authorized gate template.
    for ln in body.splitlines():
        if "hqa-quant-readonly.sh" in ln and "options" in ln:
            assert "daily-scan" not in ln
            assert "buyside-screen" not in ln
    assert "default" in body.lower() and "futu" in body.lower()


# --- D-25 async completion push wrapper -------------------------------------

NOTIFY_SRC = REPO / "scripts" / "hermes" / "hqa-notify.sh"


def _build_notify(tmp_path, repo_dir):
    """Materialise hqa-notify.sh with __HQA_REPO_DIR__ pointed at a scratch repo
    (so the fallback JSONL lands under tmp, never the real repo)."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    body = NOTIFY_SRC.read_text().replace("__HQA_REPO_DIR__", str(repo_dir))
    notify = tmp_path / "hqa-notify.sh"
    notify.write_text(body)
    notify.chmod(0o755)
    return notify


def _run_notify(tmp_path, args, *, path):
    """Run the notifier under a controlled PATH so we decide whether a `hermes`
    binary is reachable. Returns the completed process."""
    repo_dir = tmp_path / "repo"
    notify = _build_notify(tmp_path, repo_dir)
    env = dict(os.environ, PATH=path)
    return subprocess.run(
        ["bash", str(notify), *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_notify_fallback_writes_jsonl_when_hermes_absent(tmp_path):
    # PATH without a `hermes` binary → local fallback: append one JSON line to
    # logs/notify_fallback.jsonl under the repo dir AND echo the message.
    result = _run_notify(
        tmp_path,
        ["#backtest", "run-x done: sharpe=1.18"],
        path="/usr/bin:/bin",
    )
    assert result.returncode == 0, result.stderr
    fallback = tmp_path / "repo" / "logs" / "notify_fallback.jsonl"
    assert fallback.is_file(), "fallback JSONL not created"
    lines = [ln for ln in fallback.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected exactly one JSONL line, got {lines!r}"
    record = json.loads(lines[0])
    assert set(record) >= {"ts", "target", "message"}
    assert record["target"] == "#backtest"
    # Message carries the [HQA] prefix + a UTC timestamp before the body.
    assert record["message"].startswith("[HQA] ")
    assert "run-x done: sharpe=1.18" in record["message"]
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["message"])
    # The message is also echoed to stdout for the caller/log.
    assert "run-x done: sharpe=1.18" in result.stdout
    assert "[HQA] " in result.stdout


def test_notify_fallback_appends_second_line(tmp_path):
    # Two invocations append (never truncate) — the JSONL is a running log.
    repo_dir = tmp_path / "repo"
    notify = _build_notify(tmp_path, repo_dir)
    env = dict(os.environ, PATH="/usr/bin:/bin")
    for msg in ("first", "second"):
        r = subprocess.run(
            ["bash", str(notify), "#ch", msg],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert r.returncode == 0, r.stderr
    fallback = repo_dir / "logs" / "notify_fallback.jsonl"
    lines = [ln for ln in fallback.read_text().splitlines() if ln.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["message"].endswith("first")
    assert json.loads(lines[1])["message"].endswith("second")


def test_notify_delivers_via_hermes_when_available(tmp_path):
    # PATH with a stub `hermes` that succeeds → deliver via `hermes send`, NO
    # fallback JSONL. The stub records its argv so we assert the discord target
    # and the [HQA]-prefixed message are forwarded.
    stubdir = tmp_path / "stub"
    stubdir.mkdir()
    argv_log = tmp_path / "hermes_argv.txt"
    stub = stubdir / "hermes"
    stub.write_text(f'#!/bin/bash\nprintf "%s\\n" "$*" > "{argv_log}"\nexit 0\n')
    stub.chmod(0o755)
    result = _run_notify(
        tmp_path,
        ["#backtest", "done"],
        path=f"{stubdir}:/usr/bin:/bin",
    )
    assert result.returncode == 0, result.stderr
    fallback = tmp_path / "repo" / "logs" / "notify_fallback.jsonl"
    assert not fallback.exists(), "must not fall back when hermes delivery succeeds"
    forwarded = argv_log.read_text()
    assert "send" in forwarded
    assert "discord" in forwarded  # --to discord[:#channel]
    assert "[HQA] " in forwarded


def test_notify_falls_back_when_hermes_delivery_fails(tmp_path):
    # PATH with a `hermes` that EXITS NONZERO (delivery/backend error) → the
    # wrapper must still not lose the message: fall back to the JSONL log.
    stubdir = tmp_path / "stub"
    stubdir.mkdir()
    stub = stubdir / "hermes"
    stub.write_text("#!/bin/bash\nexit 1\n")
    stub.chmod(0o755)
    result = _run_notify(
        tmp_path,
        ["#backtest", "salvage-me"],
        path=f"{stubdir}:/usr/bin:/bin",
    )
    assert result.returncode == 0, result.stderr
    fallback = tmp_path / "repo" / "logs" / "notify_fallback.jsonl"
    assert fallback.is_file(), "delivery failure must still persist to fallback"
    assert "salvage-me" in fallback.read_text()


def test_notify_source_uses_repo_placeholder_and_discord_target():
    # Static guards: the source ships the install-time repo placeholder (so the
    # fallback log resolves per-machine) and delivers to discord via hermes send.
    body = NOTIFY_SRC.read_text(encoding="utf-8")
    assert "__HQA_REPO_DIR__" in body
    assert "logs/notify_fallback.jsonl" in body
    assert "hermes send" in body
    assert "discord" in body
