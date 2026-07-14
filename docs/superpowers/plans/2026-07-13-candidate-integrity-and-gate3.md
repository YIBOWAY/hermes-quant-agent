# Candidate Integrity and Scoped Gate 3 Implementation Plan

> **Delivery status (2026-07-14): DELIVERED AND POST-REVIEW HARDENED.** The
> repo-anchored candidate repository, immutable manifest, exact Gate 2 CAS,
> dry-run migration, exact-ID/digest one-shot loader, and isolated Gate 3
> lifecycle are delivered. Follow-up adversarial review also made unsafe or
> dangling roots fail closed, detects root drift even for an empty migration
> report, makes cleanup/abandon crash-recoverable, preserves abandoned audit
> history while allowing a new prepare ID, rejects all bulk candidate loading,
> and adds HQA Scene-B Gate 1 exact-source confirmation/binding plus a Gate-1-
> revalidated `factor_repro_cli promote` wrapper. HQA list output is explicitly
> non-authoritative; only exact JSON propose/detail receipts may advertise the
> HQA Gate 2 command. The final workflow review then closed three parallel/state
> gaps: external source bytes now round-trip without newline normalization and
> HQA requires the platform's verified `source_sha256`; raw candidate listing no
> longer emits approval authority and old Agent Studio is read-only; and the HQA
> Gate 3 entry now requires a content-addressed successful `--final` one-shot
> backtest receipt for the exact candidate/digest, revalidated before and after
> prepare. A final 2026-07-14 adversarial pass additionally rejects synthetic
> provider defaults, binds the exact persisted config/summary/generated report
> to a unique non-overwriting experiment namespace, verifies the actual Gate 3
> three-file bytes/modes/dirty set/Git patch, re-attests that workspace through
> digest-linked platform status, supports retry IDs beyond `-r9`, treats
> subprocess timeouts as recoverable unknown outcomes, and prevents symlinked
> audit ancestors or macOS `/var` aliases from weakening no-follow traversal.
> Fresh HQA evidence is `659 passed, 2 skipped`; platform canonical verification
> is green with `1,377 passed, 15 skipped` plus frontend `35 files / 133 tests`.
> Real migration
> `--apply`, a real promotion, and Hermes approval mutations were not executed.
> The unchecked boxes below are the original execution checklist, not current
> progress; use this block, `docs/README.md`, tests, and runtime evidence.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the platform candidate pool one immutable, digest-bound source of truth and make Gate 3 produce a reviewable scoped diff in an isolated worktree without touching or inheriting approval from changed candidate bytes.

**Architecture:** The platform gains one repo-anchored agent-output resolver, a dirfd-only candidate filesystem boundary, and a focused manifest/repository layer that serializes creation/review with OS locks, publishes directories atomically without replacement, and applies expected-digest plus expected-status compare-and-set. Every candidate consumer receives the same resolved agent root and re-verifies the same immutable snapshot before displaying, executing, or promoting it. The existing no-git materializer becomes internal-only; the public Gate 3 CLI can only delegate to a separate isolated-worktree orchestrator that owns git operations, a deterministic scoped patch manifest, and a persistent human review workspace.

**Tech Stack:** Platform Python 3.12.13, HQA Python 3.9.6-compatible call sites, Pydantic v2, pathlib, fcntl on the supported macOS/Linux local runtime, FastAPI, Typer, pytest, Git CLI with argument arrays, generated OpenAPI TypeScript, React/TypeScript compatibility client.

## Global Constraints

- Canonical candidate root is <code>resolve_candidates_dir(resolve_agent_output_dir())</code>. With no explicit override and no <code>QS_AGENT_OUTPUT_DIR</code>, this is the repo-anchored absolute path <code>/Users/sunyibo/programs/ai-quant-platform/data/agent_run/agent/candidates</code>; it never depends on process CWD or <code>QS_DATA_DIR</code>.
- Every production candidate read/write/list/detail/review/load/migrate/promote call receives an agent-output root and derives <code>agent/candidates</code> exactly once. No active source keeps <code>Path("data/agent_run")</code>, a string default of <code>"data/agent_run"</code>, a module-level candidate-root constant, or a direct public <code>--candidates-dir</code> bypass.
- <code>metadata.json</code> and candidate artifact bytes become immutable after atomic publication.
- Same candidate ID plus the same manifest digest is an idempotent read of the existing object; same ID plus a different digest is a conflict and writes nothing.
- Manifest inputs reject absolute paths, <code>..</code>, symlinks, non-regular files, directory escape, duplicate normalized paths, and reserved metadata overrides.
- Gate 2 approval binds the exact manifest digest and uses expected-digest CAS; legacy locks without a digest are <code>legacy_unbound</code> and never authorize execution or promotion.
- HQA Gate 2 is an explicit human command requiring <code>--candidate-id</code>, <code>--expected-digest</code>, literal <code>--expected-status pending</code>, and non-empty <code>--note</code>. HQA never lists, refetches, or substitutes an observed digest/status while handling approval.
- One-shot approved-candidate research re-verifies the manifest immediately before candidate code is compiled; resident paper/live registries remain promoted-only.
- The supported HQA Scene-B Gate 3 entry additionally requires the exact content-addressed receipt from a successful <code>backtest --final</code> for the same candidate/digest; non-final trials never authorize Gate 3. The platform's three-argument public prepare remains a generic primitive and is not the supported HQA provenance chain.
- Gate 3 still ends with human <code>git diff</code> review and a human commit. The system never commits, merges, pushes, or touches the user's dirty main worktree.
- Public Gate 3 prepare requires <code>--candidate-id</code>, <code>--expected-digest</code>, and <code>--base-commit</code>; a missing option is Typer usage error/exit 2 with zero candidate, git, promotion-state, or worktree writes. Status and cleanup locate state by <code>--promotion-id</code> only; destructive cleanup additionally requires either durable reviewed-commit evidence or the operator's explicit <code>--abandon</code> flag.
- Tests use temporary directories and temporary git repositories. They do not touch real candidate data, call a provider, run a real research job, mutate paper accounts, contact a broker, or use live trading.
- Preserve platform worktree changes <code>data/options_universe/earnings_calendar.csv</code> and <code>.understand-anything/diff-overlay.json</code>.
- Preserve HQA generated/runtime files and the untracked <code>.superpowers/</code> visual workspace.
- Do not expose candidate approval in the new Hermes UI until every task in this plan passes.

---

## Current facts

- CLI proposal/list/review and one-shot experiment loading use <code>data/agent_run/agent/candidates</code>.
- FastAPI currently injects <code>data</code> as <code>OutputDirDep</code>, so <code>/api/agent/candidates</code> reads the wrong <code>data/agent/candidates</code>.
- The real canonical root contains one pending candidate, <code>factor-momentum_20d_reversal-323b045e4b</code>, with no approval/rejection lock.
- <code>CandidatePool.write_candidate()</code> currently overwrites an existing deterministic ID and allows <code>metadata_extra</code> to replace protected fields.
- review locks bind only ID/decision/note and review mutates metadata, so approval is not bound to stable bytes.
- <code>load_approved_factor_candidates()</code> and <code>promote_candidate()</code> check lock existence, then read current source.
- the existing <code>promote.py</code> has strong AST, collision, exclusive-create, rollback, and library serialization tests; keep those properties and keep git/subprocess out of that module.
- <code>experiment run-config --include-approved-candidates</code> still constructs <code>Path("data/agent_run")</code> relative to CWD, and <code>/api/factors?include_candidates=true</code> still uses a module-level candidate path. Both are candidate execution/read consumers and must use the same resolved/injected agent root.
- HQA's installed skill card still documents Gate 2 with only candidate ID plus note. The implementation slice must update and install-test the four-value human CAS command before runtime smoke.

## File map

### Platform candidate core

- Create <code>src/quant_system/agent/paths.py</code>: canonical agent/candidate path resolution.
- Create <code>tests/test_agent_paths.py</code>: default-data-root and explicit override contracts.
- Create <code>src/quant_system/agent/candidate_fs.py</code>: safe absolute directory walk, held dirfd identity checks, no-follow regular-file I/O, pool locking, exclusive atomic control writes, and no-replace directory publication.
- Create <code>src/quant_system/agent/candidate_manifest.py</code>: exact-byte manifest schema, safe reads, canonical digest, verified snapshot.
- Modify <code>src/quant_system/agent/models.py</code>: <code>legacy_unbound</code>, manifest-aware artifacts and review records.
- Modify <code>src/quant_system/agent/candidate_pool.py</code>: atomic repository, lock, idempotent create, review CAS.
- Modify <code>src/quant_system/agent/safety.py</code>: approval binding verification, not lock-existence authorization.
- Modify <code>src/quant_system/agent/promotion.py</code>: verify digest again before one-shot candidate compile.
- Modify <code>src/quant_system/agent/promote.py</code>: accept a verified snapshot/digest while remaining a pure materializer.

### Platform API and CLI

- Modify <code>src/quant_system/api/bootstrap.py</code>, <code>server.py</code>, and <code>dependencies.py</code>: injectable <code>agent_output_dir</code>.
- Modify <code>src/frontend/playwright.config.ts</code>: explicit test-only <code>QS_AGENT_OUTPUT_DIR</code>; <code>QS_DATA_DIR</code> never implicitly relocates candidates.
- Modify <code>src/quant_system/api/routes/agent.py</code> and <code>factors.py</code>: same repository and safe detail reads.
- Modify <code>src/quant_system/api/schemas/agent.py</code>: digest, binding state, expected digest.
- Modify <code>src/quant_system/cli.py</code>: resolver-only agent commands and approved-candidate experiment loading, digest-aware list/review, and scoped promotion commands.
- Modify <code>src/frontend/components/forms/AgentTaskForm.tsx</code> and generated API contracts so the legacy UI cannot bypass CAS during the migration window.
- Modify <code>tests/test_cli_experiment_provider.py</code>, <code>tests/test_factor_registry_factory.py</code>, and <code>tests/test_frontend_e2e_config.py</code>: CWD-independent/env/injected candidate-root contracts.

### Migration and Gate 3

- Create <code>src/quant_system/agent/candidate_migration.py</code>: dry-run-first audit and conflict-safe migration.
- Create <code>src/quant_system/agent/promotion_workspace.py</code>: detached worktree, scoped paths, binary patch and manifest.
- Create <code>tests/test_candidate_manifest.py</code>, <code>test_candidate_repository.py</code>, <code>test_candidate_migration.py</code>, and <code>test_promotion_workspace.py</code>.
- Extend existing agent, API, CLI, promotion, registry, OpenAPI, and frontend tests.

### HQA callers

- Modify <code>hqa/quant_cli.py</code> and <code>hqa/factor_repro_cli.py</code>: surface and pass the exact digest.
- Modify <code>tests/test_quant_cli.py</code>, <code>test_factor_repro.py</code>, and <code>test_factor_repro_cli.py</code>.
- Modify <code>skills/hermes/hqa-quant/SKILL.md</code>: document the four required human Gate 2 inputs and the promotion workspace flow without any auto-refetch shortcut.
- Modify <code>tests/test_install.py</code>: lock the source and installed skill card to the exact Gate 2 command contract.

### Live documentation after delivery

- Modify platform <code>AGENTS.md</code>, <code>README.md</code>, and <code>docs/INDEX.md</code> only where their live contracts/pointers need the delivered root, Gate 2, and Gate 3 facts.
- Modify HQA <code>AGENTS.md</code>, <code>README.md</code>, <code>docs/README.md</code>, <code>skills/hermes/hqa-quant/SKILL.md</code>, <code>docs/design/vision-daily-life.md</code>, <code>docs/design/hermes_quant_agent_plan.md</code>, <code>docs/design/2026-07-01-roadmap-phases-0b-4.md</code>, and D-31 <code>docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md</code> against fresh code/test evidence. Historical plans and completed delivery records remain historical and are not rewritten.

## Locked interfaces

~~~python
class CandidateConflictError(RuntimeError):
    pass

class CandidateStaleError(RuntimeError):
    pass

class CandidateReviewStateStaleError(CandidateStaleError):
    pass

class CandidateIntegrityError(RuntimeError):
    pass

class CandidateMigrationRequiredError(CandidateIntegrityError):
    pass

def _validate_candidate_id(value: str) -> str:
    """Return one canonical safe directory component or raise CandidateIntegrityError."""
    raise NotImplementedError

class CandidateFileDigest(BaseModel):
    path: str
    size_bytes: int
    sha256: str

class CandidateManifestV1(BaseModel):
    schema_version: Literal["1.0"]
    candidate_id: str
    artifact_type: str
    goal: str
    universe: list[str]
    metadata_sha256: str
    files: list[CandidateFileDigest]

class VerifiedCandidateSnapshot(BaseModel):
    candidate_id: str
    candidate_dir: Path
    metadata: dict[str, Any]
    manifest: CandidateManifestV1
    manifest_digest: str
    approval_binding: Literal["pending", "approved", "rejected", "legacy_unbound"]
    artifact_bytes: dict[str, bytes]
    review_record: ReviewRecord | None

class CandidateReadItem(BaseModel):
    candidate_id: str
    artifact_type: str | None
    goal: str | None
    universe: list[str] | None
    status: Literal["pending", "approved", "rejected"] | None
    integrity_state: Literal["verified", "migration_required", "corrupt"]
    manifest_digest: str | None
    observed_manifest_digest: str | None
    approval_binding: Literal["pending", "approved", "rejected", "legacy_unbound"] | None
    approval_enabled: bool
    integrity_error_code: str | None

def load_verified_candidate_snapshot(
    *, agent_output_dir: str | Path, candidate_id: str
) -> VerifiedCandidateSnapshot:
    raise NotImplementedError

class CandidatePool:
    def write_candidate(
        self,
        *,
        task_id: str,
        goal: str,
        artifact_type: str,
        filename: str,
        content: str,
        universe: list[str] | None = None,
        metadata_extra: dict[str, Any] | None = None,
    ) -> CandidateArtifact:
        raise NotImplementedError

    def get(self, candidate_id: str) -> VerifiedCandidateSnapshot:
        raise NotImplementedError

    def list_for_read(self) -> list[CandidateReadItem]:
        raise NotImplementedError

    def review(
        self,
        *,
        candidate_id: str,
        decision: Literal["approve", "reject"],
        note: str,
        expected_manifest_digest: str,
        expected_status: Literal["pending"],
    ) -> ReviewRecord:
        raise NotImplementedError
~~~

---

### Task 1: Canonical agent path dependency

**Files:**

- Create: <code>src/quant_system/agent/paths.py</code>
- Create: <code>tests/test_agent_paths.py</code>
- Modify: <code>src/quant_system/api/bootstrap.py</code>
- Modify: <code>src/quant_system/api/server.py</code>
- Modify: <code>src/quant_system/api/dependencies.py</code>
- Modify: <code>src/quant_system/api/routes/agent.py</code>
- Modify: <code>src/quant_system/api/routes/factors.py</code>
- Modify: <code>src/quant_system/agent/runner.py</code>
- Modify: <code>src/quant_system/cli.py</code>
- Modify: <code>src/frontend/playwright.config.ts</code>
- Test: <code>tests/test_api_agent.py</code>
- Test: <code>tests/test_cli_experiment_provider.py</code>
- Test: <code>tests/test_factor_registry_factory.py</code>
- Test: <code>tests/test_frontend_e2e_config.py</code>

**Interfaces:**

- Produces: <code>resolve_agent_output_dir(explicit: str | Path | None = None) -> Path</code>, <code>resolve_candidates_dir(agent_output_dir: str | Path) -> Path</code>, <code>AgentOutputDirDep</code>, and an additive <code>agent_output_dir: str | Path | None = None</code> keyword on the existing <code>create_app</code> interface. Every API/CLI/migration caller uses this resolver; <code>QS_DATA_DIR</code> is unrelated.
- The dependency value is the agent output root; <code>CandidatePool</code> appends <code>agent/candidates</code> exactly once.
- <code>AgentRunner</code> receives <code>agent_output_dir</code> explicitly for candidate/audit state. If a workflow also reads general experiment output, that is a separately named <code>result_output_dir</code>; it never becomes a candidate-root fallback.
- <code>experiment run-config --include-approved-candidates</code> resolves its candidate root through <code>resolve_candidates_dir(resolve_agent_output_dir(agent_output_dir))</code>. Its legacy direct <code>--candidates-dir</code> option is removed; an explicit root uses <code>--agent-output-dir</code> or <code>QS_AGENT_OUTPUT_DIR</code> and is still normalized by the resolver.
- <code>/api/factors?include_candidates=true</code> injects <code>AgentOutputDirDep</code>; it must not call a process-global resolver or retain <code>AGENT_CANDIDATES_DIR</code>, because <code>create_app(agent_output_dir=...)</code> is the API isolation boundary.

- [ ] **Step 1: Add a failing dependency-injection test**

Add the API test plus this pure default-path test:

~~~python
def test_agent_api_uses_injected_agent_output_dir_not_general_data_dir(tmp_path) -> None:
    general = tmp_path / "general"
    agent = tmp_path / "agent-output"
    artifact = CandidatePool(agent).write_candidate(
        task_id="task-root-contract",
        goal="root contract",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# candidate\n",
    )

    client = TestClient(create_app(output_dir=general, agent_output_dir=agent))
    payload = client.get("/api/agent/candidates").json()

    assert [item["candidate_id"] for item in payload["candidates"]] == [
        artifact.candidate_id
    ]
    assert not (general / "agent" / "candidates").exists()


def test_agent_task_writes_candidate_and_audit_only_to_injected_agent_root(
    tmp_path, monkeypatch
) -> None:
    general = tmp_path / "general"
    agent = tmp_path / "agent-output"
    monkeypatch.setattr(agent_routes, "build_llm_client", lambda _settings: StubLLMClient())
    client = TestClient(create_app(output_dir=general, agent_output_dir=agent))

    response = client.post(
        "/api/agent/tasks",
        json={
            "task_type": "propose-factor",
            "goal": "root contract",
            "universe": ["SPY"],
        },
    )

    assert response.status_code == 200
    assert list((agent / "agent" / "candidates").glob("*/metadata.json"))
    assert list((agent / "agent" / "audit").glob("*.jsonl"))
    assert not (general / "agent").exists()


def test_agent_root_has_one_repo_default_and_explicit_env_override(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("QS_AGENT_OUTPUT_DIR", raising=False)
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "must-not-move-agent-root"))
    monkeypatch.chdir(tmp_path)
    assert resolve_agent_output_dir() == (
        PLATFORM_REPO_ROOT / "data" / "agent_run"
    )
    monkeypatch.setenv("QS_AGENT_OUTPUT_DIR", str(tmp_path / "agent-output"))
    assert resolve_agent_output_dir() == tmp_path / "agent-output"
    assert resolve_legacy_candidates_dir() == (
        PLATFORM_REPO_ROOT / "data" / "agent" / "candidates"
    )


def test_factors_candidate_catalog_uses_create_app_agent_root(tmp_path) -> None:
    general = tmp_path / "general"
    agent = tmp_path / "agent-output"
    candidates_dir = agent / "agent" / "candidates"
    candidates_dir.mkdir(parents=True)
    _write_candidate(
        candidates_dir,
        "cand-approved",
        _CANDIDATE_SRC,
        approved=True,
    )

    client = TestClient(create_app(output_dir=general, agent_output_dir=agent))
    payload = client.get("/api/factors?include_candidates=true").json()

    assert "wiring_test_factor" in {
        item["factor_id"] for item in payload["factors"]
    }
    assert not (general / "agent").exists()


def test_run_config_candidate_loader_is_cwd_independent_and_uses_env(
    monkeypatch, tmp_path
) -> None:
    agent = tmp_path / "agent-output"
    outside = tmp_path / "outside-platform-repo"
    outside.mkdir()
    monkeypatch.setenv("QS_AGENT_OUTPUT_DIR", str(agent))
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "general-data"))
    monkeypatch.chdir(outside)

    captured = {}

    def fake_load(registry, *, agent_output_dir):
        captured["agent_output_dir"] = Path(agent_output_dir)
        return []

    monkeypatch.setattr(cli_module, "load_approved_factor_candidates", fake_load)
    _invoke_stubbed_run_config_with_approved_candidates(monkeypatch, tmp_path)

    assert captured["agent_output_dir"] == resolve_agent_output_dir()
    assert resolve_candidates_dir(captured["agent_output_dir"]) == (
        agent / "agent" / "candidates"
    )
~~~

<code>_invoke_stubbed_run_config_with_approved_candidates</code> is the existing test's <code>CliRunner</code> invocation plus its already-defined fake provider/result; extract that repeated setup as a local helper in <code>tests/test_cli_experiment_provider.py</code>. Delete the old direct <code>--candidates-dir</code> override test and replace it with an explicit <code>--agent-output-dir</code> normalization test.

Add a source regression test over active Python/TypeScript candidate consumers. It must fail if <code>src/quant_system/cli.py</code>, <code>src/quant_system/api/routes</code>, <code>src/quant_system/agent</code>, or <code>src/frontend/playwright.config.ts</code> contains <code>Path("data/agent_run")</code>, a <code>"data/agent_run"</code> candidate default, <code>AGENT_CANDIDATES_DIR</code>, or code deriving candidates from <code>QS_DATA_DIR</code>. Historical docs are outside this source assertion.

- [ ] **Step 2: Run the test and confirm RED**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q \
  tests/test_agent_paths.py \
  tests/test_api_agent.py::test_agent_api_uses_injected_agent_output_dir_not_general_data_dir \
  tests/test_factor_registry_factory.py::test_factors_candidate_catalog_uses_create_app_agent_root \
  tests/test_cli_experiment_provider.py::test_run_config_candidate_loader_is_cwd_independent_and_uses_env \
  tests/test_frontend_e2e_config.py
~~~

Expected: <code>create_app()</code> rejects the unknown <code>agent_output_dir</code> argument; the run-config assertion still observes a CWD-relative path; the factors route does not use injected state.

- [ ] **Step 3: Implement path resolution and DI**

Create:

~~~python
# src/quant_system/agent/paths.py
from __future__ import annotations

import os
from pathlib import Path

PLATFORM_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AGENT_OUTPUT_DIR = PLATFORM_REPO_ROOT / "data" / "agent_run"
DEFAULT_LEGACY_CANDIDATES_DIR = PLATFORM_REPO_ROOT / "data" / "agent" / "candidates"


def _repo_anchored_absolute(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    anchored = path if path.is_absolute() else PLATFORM_REPO_ROOT / path
    # abspath/normpath is lexical; unlike Path.resolve(), it does not follow a
    # symlink that the dirfd filesystem boundary must detect and reject.
    return Path(os.path.abspath(os.fspath(anchored)))


def resolve_agent_output_dir(explicit: str | Path | None = None) -> Path:
    raw = explicit if explicit is not None else os.environ.get("QS_AGENT_OUTPUT_DIR")
    if raw is None:
        return DEFAULT_AGENT_OUTPUT_DIR
    return _repo_anchored_absolute(raw)


def resolve_legacy_candidates_dir(explicit: str | Path | None = None) -> Path:
    if explicit is None:
        return DEFAULT_LEGACY_CANDIDATES_DIR
    return _repo_anchored_absolute(explicit)


def resolve_candidates_dir(agent_output_dir: str | Path) -> Path:
    return Path(agent_output_dir) / "agent" / "candidates"
~~~

In <code>build_services</code>, add <code>agent_output_dir</code> and return:

~~~python
"agent_output_dir": resolve_agent_output_dir(
    agent_output_dir,
),
~~~

In <code>create_app</code>, add and forward the same keyword. In dependencies add:

~~~python
def get_agent_output_dir(request: Request) -> Path:
    return request.app.state.services["agent_output_dir"]


AgentOutputDirDep = Annotated[Path, Depends(get_agent_output_dir)]
~~~

Split <code>AgentRunner</code> construction into explicitly named <code>result_output_dir</code> for existing experiment/result reads and required <code>agent_output_dir</code> for <code>CandidatePool</code> plus <code>AgentAuditLog</code>; do not default the latter from general output data. Change every agent route—list, detail, task creation, and review—to inject <code>AgentOutputDirDep</code>; task creation passes both roots, while list/detail/review and audit lookup use the agent root. Do not repurpose general <code>OutputDirDep</code>.

Change every <code>agent</code> CLI command's candidate/audit option to <code>agent_output_dir: str | Path | None = None</code> and pass it through <code>resolve_agent_output_dir</code>. Remove every active <code>="data/agent_run"</code> default. Change <code>experiment run-config</code> as specified above. In <code>routes/factors.py</code>, delete <code>_REPO_ROOT</code>/<code>AGENT_CANDIDATES_DIR</code>, inject <code>AgentOutputDirDep</code>, and derive the candidates directory from that dependency only. In Playwright config, add <code>QS_AGENT_OUTPUT_DIR: path.join(e2eDataRoot, "agent-output")</code> beside <code>QS_DATA_DIR</code>; update its source test. Python API tests that construct <code>create_app</code> must pass <code>agent_output_dir=tmp_path / "agent-output"</code> explicitly. This prevents test reads of the real pool without creating a second implicit root rule.

- [ ] **Step 4: Run agent API tests**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q tests/test_agent_paths.py tests/test_api_agent.py \
  tests/test_cli_experiment_provider.py tests/test_factor_registry_factory.py \
  tests/test_frontend_e2e_config.py
~~~

Expected: all tests pass and every test-owned candidate lives under a temp agent root.

- [ ] **Step 5: Commit**

~~~bash
git add src/quant_system/agent/paths.py src/quant_system/api/bootstrap.py \
  src/quant_system/api/server.py src/quant_system/api/dependencies.py \
  src/quant_system/api/routes/agent.py src/quant_system/api/routes/factors.py \
  src/quant_system/agent/runner.py src/quant_system/cli.py \
  tests/test_agent_paths.py tests/test_api_agent.py \
  tests/test_cli_experiment_provider.py tests/test_factor_registry_factory.py \
  tests/test_frontend_e2e_config.py src/frontend/playwright.config.ts
git commit -m "fix(agent): unify API candidate root with CLI source of truth"
~~~

---

### Task 2: Dirfd filesystem boundary, candidate identity, and exact-byte manifest

**Files:**

- Create: <code>src/quant_system/agent/candidate_fs.py</code>
- Create: <code>src/quant_system/agent/candidate_manifest.py</code>
- Create: <code>tests/test_candidate_manifest.py</code>

**Interfaces:**

- Produces the manifest/snapshot interfaces defined above plus shared dirfd primitives used unchanged by repository write/review and migration.
- All filesystem trust starts by lexically splitting an absolute path and opening every component from <code>/</code> with <code>O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC</code>. After that first split, candidate filesystem code uses names plus held <code>dir_fd</code>s only—never <code>Path.open()</code>, <code>Path.mkdir()</code>, <code>tempfile</code> with a path-string directory, path-based <code>os.replace()</code>, or a re-resolved pathname.
- <code>_validate_candidate_id</code> is the only candidate-ID validator. Creation, <code>get</code>, review, API detail, <code>SafetyGate</code>, CLI, migration, and promotion all call it before filesystem access.
- V1 candidate IDs are lowercase canonical ASCII single components. Artifact/control names are canonical ASCII single components and are compared by <code>casefold()</code> for duplicate/reserved collisions so the contract is identical on case-sensitive Linux and the supported default case-insensitive macOS filesystem. Nested IDs/artifacts are deliberately rejected so every metadata/artifact/control operation is relative to one held directory FD; a later schema version is required before nesting.
- A verified snapshot proves <code>candidate directory basename == metadata.candidate_id == manifest.candidate_id</code> and carries the exact verified artifact bytes. Later code never reopens the source via <code>snapshot.candidate_dir / name</code>.
- Manifest JSON is canonical UTF-8 with sorted keys and separators <code>(",", ":")</code>; file list order is explicit POSIX basename order.

- [ ] **Step 1: Write failing identity, exact-byte, and hostile-filesystem tests**

~~~python
from __future__ import annotations

import json
import os

import pytest

from quant_system.agent.candidate_manifest import (
    CandidateIntegrityError,
    _validate_candidate_id,
    build_candidate_manifest,
    canonical_json_bytes,
)


def _candidate(root):
    root.mkdir()
    metadata = {
        "candidate_id": root.name,
        "artifact_type": "factor",
        "goal": "safe",
        "universe": ["SPY"],
        "files": ["z.py.candidate", "a.json"],
    }
    (root / "metadata.json").write_text(
        json.dumps(metadata, sort_keys=True, indent=2), encoding="utf-8"
    )
    (root / "z.py.candidate").write_bytes(b"Z\r\n")
    (root / "a.json").write_bytes(b"{\"a\":1}\n")
    return metadata


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        ".",
        "..",
        "../escape",
        "../../escape",
        "/tmp/escape",
        "nested/id",
        r"nested\id",
        " leading",
        "trailing ",
        "metadata.json",
        "manifest.v1.json",
        "UPPERCASE-ID",
        "approved.lock",
        "rejected.lock",
        "legacy-approved.lock",
        "legacy-rejected.lock",
        "reviews.jsonl",
        ".candidate-pool.lock",
    ],
)
def test_candidate_id_is_one_canonical_nonreserved_component(bad_id) -> None:
    with pytest.raises(CandidateIntegrityError):
        _validate_candidate_id(bad_id)


def test_manifest_binds_exact_bytes_and_sorts_posix_paths(tmp_path) -> None:
    candidate = tmp_path / "factor-safe-1"
    _candidate(candidate)

    manifest, digest, artifact_bytes = build_candidate_manifest(candidate)

    assert manifest.candidate_id == candidate.name
    assert [item.path for item in manifest.files] == ["a.json", "z.py.candidate"]
    assert manifest.files[1].size_bytes == 3
    assert artifact_bytes["z.py.candidate"] == b"Z\r\n"
    assert digest == __import__("hashlib").sha256(
        canonical_json_bytes(manifest.model_dump(mode="json"))
    ).hexdigest()


def test_directory_metadata_and_stored_manifest_ids_must_match(tmp_path) -> None:
    candidate = tmp_path / "factor-safe-1"
    metadata = _candidate(candidate)
    metadata["candidate_id"] = "factor-other-2"
    (candidate / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(CandidateIntegrityError, match="candidate_id"):
        build_candidate_manifest(candidate)
~~~

Retain the existing unsafe metadata-file-path cases and add separate tests for duplicate basenames, absolute/<code>..</code>/slash/backslash paths, every reserved control basename, a symlinked agent-output root, symlinked <code>agent</code> or <code>candidates</code> root, symlinked candidate directory, symlinked <code>metadata.json</code>/<code>manifest.v1.json</code>/artifact, and FIFO/device/socket/non-regular files. Add a stored-manifest test where directory and metadata agree but <code>manifest.candidate_id</code> differs.

Add case-insensitive collision tests: <code>Approved.lock</code> is reserved, <code>Metadata.json</code>/<code>MANIFEST.V1.JSON</code> are reserved, and metadata listing both <code>A.py</code> and <code>a.py</code> is corrupt even on a case-sensitive test filesystem. Add hardlink-to-outside tests for <code>metadata.json</code>, <code>manifest.v1.json</code>, every artifact, and approval/rejection/legacy control; safe reads require <code>st_nlink == 1</code>, so legacy hardlinks are <code>corrupt</code> and outside bytes are never accepted.

Use barrier-synchronized rename tests for both the candidates-root entry and candidate-directory entry after their FDs are opened. Each test must prove the read either returns bytes from the held original inode or raises <code>CandidateIntegrityError</code>; it must never read replacement/outside bytes. Assert held/opened directory <code>st_dev/st_ino</code> still matches its parent's current no-follow entry before a snapshot is returned.

- [ ] **Step 2: Run and confirm RED**

Run: <code>./ai-quant/bin/python -m pytest -q tests/test_candidate_manifest.py</code>

Expected: both new modules fail to import.

- [ ] **Step 3: Implement the shared dirfd boundary and strict manifest construction**

Define the shared identity rules exactly:

~~~python
_SAFE_CANDIDATE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_RESERVED_CANDIDATE_COMPONENTS = frozenset(
    {
        "metadata.json",
        "manifest.v1.json",
        "approved.lock",
        "rejected.lock",
        "legacy-approved.lock",
        "legacy-rejected.lock",
        "reviews.jsonl",
        ".candidate-pool.lock",
    }
)


def _validate_candidate_id(value: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or PurePosixPath(value).is_absolute()
        or _SAFE_CANDIDATE_ID.fullmatch(value) is None
        or value in _RESERVED_CANDIDATE_COMPONENTS
    ):
        raise CandidateIntegrityError("candidate_id is not a canonical component")
    return value


def _normalized_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or "." in path.parts
        or ".." in path.parts
        or len(path.parts) != 1
        or str(path) != value
        or not value.isascii()
        or path.name.casefold()
        in {name.casefold() for name in _RESERVED_CANDIDATE_COMPONENTS}
    ):
        raise CandidateIntegrityError("candidate file path is not canonical")
    return path


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")
~~~

In <code>candidate_fs.py</code>, require <code>os.O_NOFOLLOW</code>, <code>os.O_DIRECTORY</code>, <code>dir_fd</code>, and <code>follow_symlinks=False</code> support at import/first use; fail closed on any unsupported runtime. Implement these primitives and use no path-string mutation behind them:

~~~python
@dataclass
class OpenedDirectory:
    fd: int
    parent_fd: int
    name: str
    st_dev: int
    st_ino: int


@contextmanager
def open_absolute_directory(path: Path, *, create: bool) -> Iterator[OpenedDirectory]: ...

def open_directory_at(parent_fd: int, name: str) -> int: ...
def read_regular_bytes_at(parent_fd: int, name: str) -> bytes: ...
def assert_entry_is_open_fd(parent_fd: int, name: str, opened_fd: int) -> None: ...
def write_regular_exclusive_at(parent_fd: int, name: str, payload: bytes) -> None: ...
def atomic_write_noreplace_at(parent_fd: int, name: str, payload: bytes) -> None: ...
def rename_directory_noreplace_at(
    source_parent_fd: int, source_name: str, destination_parent_fd: int, destination_name: str
) -> None: ...
~~~

<code>open_absolute_directory</code> starts with an FD for <code>/</code>, then opens or creates one lexical component at a time relative to the held parent. Creation uses <code>os.mkdir(component, dir_fd=parent_fd)</code>, handles an <code>EEXIST</code> race by no-follow opening the entry, and verifies <code>fstat</code> is a directory. <code>read_regular_bytes_at</code> uses <code>O_RDONLY | O_NOFOLLOW | O_CLOEXEC</code>, then requires regular-file <code>fstat</code> and <code>st_nlink == 1</code> before reading. Every temporary/control file uses a random single-component name, <code>O_CREAT | O_EXCL | O_NOFOLLOW</code>, <code>fsync(file)</code>, no-replace rename relative to the same held parent FD, and <code>fsync(parent_fd)</code>.

Implement no-replace rename explicitly with Linux <code>renameat2(..., RENAME_NOREPLACE)</code> and macOS <code>renameatx_np(..., RENAME_EXCL)</code> via a small <code>ctypes</code> adapter; map <code>EEXIST</code> to the domain conflict and fail closed on other platforms. Do not silently fall back to overwrite-capable <code>os.rename</code>/<code>os.replace</code>.

Build a candidate manifest only from exact <code>metadata.json</code> bytes and the ordered single-component files named by metadata, all read relative to a held candidate FD. Validate the directory entry through <code>_validate_candidate_id</code>; require directory/metadata ID equality before building. Reject any artifact whose casefolded name is duplicated or collides with a casefolded reserved control name. For verified reads, parse stored <code>manifest.v1.json</code>, require its ID equality, rebuild from current exact bytes, and require canonical manifest bytes and digest equality. Read approval/legacy controls through the same no-follow, single-link regular-file primitive. Return the already-read artifact bytes in <code>VerifiedCandidateSnapshot</code>; preview, compile, and materialization consumers use those bytes only.

The same builder may compute non-authoritative observed evidence for a safely read unversioned candidate; missing <code>manifest.v1.json</code> alone means <code>migration_required</code>, while any identity/path/type/byte mismatch means <code>corrupt</code>.

- [ ] **Step 4: Run manifest tests and static checks**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q tests/test_candidate_manifest.py
./ai-quant/bin/python -m ruff check src/quant_system/agent/candidate_fs.py \
  src/quant_system/agent/candidate_manifest.py tests/test_candidate_manifest.py
~~~

Expected: all pass, including root/candidate swap and identity-mismatch cases.

- [ ] **Step 5: Commit**

~~~bash
git add src/quant_system/agent/candidate_fs.py \
  src/quant_system/agent/candidate_manifest.py tests/test_candidate_manifest.py
git commit -m "feat(agent): bind candidates through a safe exact-byte filesystem boundary"
~~~

---

### Task 3: Atomic candidate repository and digest-bound review CAS

**Files:**

- Modify: <code>src/quant_system/agent/candidate_fs.py</code>
- Modify: <code>src/quant_system/agent/models.py</code>
- Modify: <code>src/quant_system/agent/candidate_pool.py</code>
- Modify: <code>src/quant_system/agent/safety.py</code>
- Modify: <code>src/quant_system/agent/promotion.py</code>
- Modify: <code>src/quant_system/agent/promote.py</code>
- Modify: <code>src/quant_system/agent/runner.py</code>
- Modify: <code>src/quant_system/api/routes/agent.py</code>
- Modify: <code>src/quant_system/api/schemas/agent.py</code>
- Modify: <code>src/quant_system/cli.py</code>
- Create: <code>tests/test_candidate_repository.py</code>
- Modify: <code>tests/test_agent_phase7.py</code>
- Modify: <code>tests/test_agent_promotion.py</code>
- Modify: <code>tests/test_agent_promote.py</code>
- Modify: <code>tests/test_api_agent.py</code>
- Modify: <code>tests/test_cli_json_output.py</code>

**Interfaces:**

- <code>write_candidate</code> publishes a complete staged <code>&lt;candidate_id&gt;</code> directory with no-replace rename while holding a verified regular <code>.candidate-pool.lock</code> opened through the held candidates-root FD.
- Review takes <code>expected_manifest_digest</code> and <code>expected_status="pending"</code>; either mismatch raises a stale error without creating a review or changing locks.
- A structured <code>approved.lock</code>/<code>rejected.lock</code> contains schema version, candidate ID, decision, manifest digest, note, reviewer, and timestamp.
- Read listing isolates each directory: <code>verified</code> items expose an authoritative digest; safe legacy items expose only a non-authoritative <code>observed_manifest_digest</code> with <code>migration_required</code>; corrupt items expose only candidate ID, <code>integrity_state</code>, and a stable error code while untrusted display metadata/status/binding remain null. Neither exceptional state can approve, compile, execute, or promote, and one bad item never hides healthy items.
- <code>get</code>, review, API detail, <code>SafetyGate</code>, and CLI validate the ID before opening the candidates root. No caller has a separate regex/path resolver, and all require directory/metadata/manifest ID equality from Task 2.
- New public contract is <code>SafetyGate(agent_output_dir)</code>; it delegates to the safe repository and never accepts an already-derived candidates directory. Update every production/test call site in this task and add a static regression assertion against <code>SafetyGate(...candidates_dir...)</code> or direct <code>/ "agent" / "candidates"</code> construction in candidate consumers.
- Create/review never write through a pathname after the safe root is open. Before publication/decision return, they re-check that the held candidates root and held candidate directory are still the entries named by their parents.

- [ ] **Step 1: Write repository RED tests**

~~~python
def test_same_id_same_manifest_is_noop_but_different_bytes_conflict(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    first = pool.write_candidate(
        task_id="stable-task",
        goal="stable goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# exact\n",
    )
    before = first.path.stat().st_mtime_ns
    second = pool.write_candidate(
        task_id="stable-task",
        goal="stable goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# exact\n",
    )
    assert second.manifest_digest == first.manifest_digest
    assert second.path.stat().st_mtime_ns == before

    with pytest.raises(CandidateConflictError):
        pool.write_candidate(
            task_id="stable-task",
            goal="stable goal",
            artifact_type="factor",
            filename="factor.py.candidate",
            content="# changed\n",
        )
    assert first.path.read_text(encoding="utf-8") == "# exact\n"


def test_review_requires_current_digest_and_legacy_lock_never_allows(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id="review-task",
        goal="review goal",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# review\n",
    )
    with pytest.raises(CandidateStaleError):
        pool.review(
            candidate_id=artifact.candidate_id,
            decision="approve",
            note="wrong revision",
            expected_manifest_digest="0" * 64,
            expected_status="pending",
        )
    assert not (artifact.path.parent / "approved.lock").exists()

    (artifact.path.parent / "approved.lock").write_text("{}", encoding="utf-8")
    assert pool.get(artifact.candidate_id).approval_binding == "legacy_unbound"
    assert SafetyGate(tmp_path).allow_promotion(artifact.candidate_id) is False


@pytest.mark.parametrize(
    "case",
    [
        "parent",
        "absolute",
        "metadata.json",
        "manifest.v1.json",
        "approved.lock",
        "rejected.lock",
        "reviews.jsonl",
        "nested/metadata.json",
    ],
)
def test_write_rejects_unsafe_or_reserved_filename_before_any_side_effect(
    tmp_path, case
) -> None:
    filename = {
        "parent": "../escaped.py",
        "absolute": str(tmp_path / "absolute-escaped.py"),
    }.get(case, case)
    pool = CandidatePool(tmp_path / "output")

    with pytest.raises(CandidateIntegrityError):
        pool.write_candidate(
            task_id="unsafe-path",
            goal="must not write",
            artifact_type="factor",
            filename=filename,
            content="# escaped\n",
        )

    assert not any(tmp_path.iterdir())
    assert not pool.candidates_dir.exists()


def test_unversioned_and_corrupt_items_remain_visible_but_never_authorize(
    tmp_path,
) -> None:
    pool = CandidatePool(tmp_path / "output")
    _write_unversioned_candidate(pool.candidates_dir, "legacy-pending")
    _write_corrupt_candidate(pool.candidates_dir, "broken")

    items = {item.candidate_id: item for item in pool.list_for_read()}

    legacy = items["legacy-pending"]
    assert legacy.integrity_state == "migration_required"
    assert legacy.manifest_digest is None
    assert len(legacy.observed_manifest_digest or "") == 64
    assert legacy.approval_enabled is False
    assert items["broken"].integrity_state == "corrupt"
    assert items["broken"].artifact_type is None
    assert items["broken"].status is None
    assert items["broken"].approval_binding is None
    with pytest.raises(CandidateMigrationRequiredError):
        pool.review(
            candidate_id="legacy-pending",
            decision="approve",
            note="observed digest is not authority",
            expected_manifest_digest=legacy.observed_manifest_digest or "",
            expected_status="pending",
        )
~~~

Add these explicit adversarial tests before implementation:

~~~python
@pytest.mark.parametrize(
    "bad_id",
    ["", ".", "..", "../outside", "../../outside", "/tmp/outside", "a/b", r"a\b", "approved.lock"],
)
def test_get_review_safety_api_and_cli_share_candidate_id_rejection_with_zero_writes(
    tmp_path, bad_id
) -> None:
    agent_output = tmp_path / "agent-output"
    outside = tmp_path / "outside"
    before = _tree_fingerprint(tmp_path)

    with pytest.raises(CandidateIntegrityError):
        CandidatePool(agent_output).get(bad_id)
    with pytest.raises(CandidateIntegrityError):
        CandidatePool(agent_output).review(
            candidate_id=bad_id,
            decision="approve",
            note="must fail before IO",
            expected_manifest_digest="0" * 64,
            expected_status="pending",
        )
    assert SafetyGate(agent_output).allow_promotion(bad_id) is False
    assert _invoke_review_cli(agent_output, bad_id).exit_code != 0
    assert _tree_fingerprint(tmp_path) == before
    assert not outside.exists()
~~~

Use a barrier-synchronized two-thread test where approve and reject both submit the same digest and <code>expected_status="pending"</code>. Assert exactly one returns <code>ReviewRecord</code>, exactly one raises <code>CandidateReviewStateStaleError</code>, exactly one decision lock exists, its bytes remain unchanged after every retry, and no opposite lock is created or deleted. Repeat approve→reject, reject→approve, approve→approve, and reject→reject retries to prove a final decision is never overwritten, deleted, or flipped.

Add root/lock/candidate swap tests: (a) <code>.candidate-pool.lock</code> is a symlink, hardlink-to-outside, FIFO, or other non-regular/non-single-link file; (b) the candidates-root entry is renamed and replaced after its FD opens; (c) the candidate entry is renamed/replaced after verified read but before review-lock publication. Every case must fail closed, leave the replacement and outside target byte-identical, and create no decision/control in the replacement tree. Also interrupt candidate creation before publish and prove no partial final candidate is visible.

- [ ] **Step 2: Run and confirm failures**

Run: <code>./ai-quant/bin/python -m pytest -q tests/test_candidate_repository.py tests/test_agent_phase7.py tests/test_api_agent.py tests/test_cli_json_output.py</code>

Expected: failures show missing digest fields/errors and the legacy lock is currently accepted.

- [ ] **Step 3: Implement dirfd-locked publication and review**

Extend <code>candidate_fs.py</code> with one reusable candidates-root lock. It must use the already-open root FD and verify the lock is a regular file:

~~~python
@contextmanager
def locked_candidates_root(agent_output_dir: Path, *, create: bool) -> Iterator[OpenedDirectory]:
    candidates_path = resolve_candidates_dir(agent_output_dir)
    with open_absolute_directory(candidates_path, create=create) as opened:
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
        lock_fd = os.open(".candidate-pool.lock", flags, 0o600, dir_fd=opened.fd)
        try:
            lock_stat = os.fstat(lock_fd)
            if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1:
                raise CandidateIntegrityError("candidate pool lock must be regular")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)
            assert_entry_is_open_fd(opened.fd, ".candidate-pool.lock", lock_fd)
            yield opened
            assert_entry_is_open_fd(opened.fd, ".candidate-pool.lock", lock_fd)
            assert_entry_is_open_fd(opened.parent_fd, opened.name, opened.fd)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
~~~

Do not add a <code>Path.open</code>/<code>tempfile</code>/<code>os.replace</code> fallback. All content/control writes call Task 2's exclusive dirfd primitives.

Creation rules:

1. Before creating the candidate root, lock, staging directory, or any file, derive then call <code>_validate_candidate_id(candidate_id)</code> and validate <code>filename</code> through the manifest module's shared V1 validator. Reject absolute, nested, <code>.</code>/<code>..</code>, backslash/non-canonical paths and every shared reserved control basename.
2. Before any write, reject <code>metadata_extra</code> keys colliding with <code>candidate_id</code>, <code>task_id</code>, <code>artifact_type</code>, <code>goal</code>, <code>universe</code>, <code>status</code>, <code>created_at</code>, <code>updated_at</code>, <code>files</code>, or <code>safety</code>.
3. Under the root lock, if final exists, compare stable input fields and exact artifact bytes through its verified manifest. Return it unchanged only if equal.
4. Otherwise create a random single-component staging directory relative to the candidates-root FD, then create <code>staging/&lt;candidate_id&gt;</code> so the verified directory basename already equals metadata/manifest identity. Write metadata/artifact/manifest exclusively through FDs, fsync every file and both directories, verify from the staged candidate FD, re-check root identity, and publish <code>&lt;candidate_id&gt;</code> with <code>rename_directory_noreplace_at</code> while still locked. Remove only the private staging entry by dirfd on failure.
5. Never update immutable metadata during review; derive list status from the structured lock.

<code>list_for_read</code> safely audits candidates independently. A missing stored manifest may be built in memory only to produce <code>observed_manifest_digest</code>; never write it, never place it in <code>manifest_digest</code>, and never accept it in review. A corrupt candidate returns no preview/digest and a stable <code>integrity_error_code</code>, while iteration continues. <code>get</code>, review, loader, execution, and promotion remain verified-only.

Mechanically update current loader/materializer callers in <code>promotion.py</code>, <code>promote.py</code>, their tests, and the temporary pre-Task-7 CLI call to pass an agent-output root rather than an already-derived candidates directory. They may delegate to <code>CandidatePool(agent_output_dir)</code>/<code>SafetyGate(agent_output_dir)</code>; no compatibility overload guesses whether a path is an agent root or candidates root. Task 4 then removes their remaining reopen-after-verification behavior by passing snapshots/bytes.

Update <code>AgentRunner.list_candidates</code> to delegate to <code>list_for_read</code>. Update <code>AgentRunner.review</code> to require and forward both <code>expected_manifest_digest</code> and <code>expected_status</code>; record those values in the audit task before mutation and never derive them from a new list call.

In this same security commit, adapt the platform API schema/route and CLI to require both CAS fields, map digest/status/migration/integrity failures to stable 409 errors, and expose per-item integrity state. Task 5 regenerates frontend contracts and updates HQA/legacy UI, but no backend caller may be left invoking the new Runner signature incorrectly between commits. Add API/CLI RED tests for missing status, stale second decision, migration-required review, and corrupt-item isolation before implementation.

Review validates candidate ID, lowercase digest shape, literal <code>expected_status="pending"</code>, and <code>note</code> length 1..2000 before opening/creating the root. It then holds the same root lock, opens the candidate directory by <code>O_DIRECTORY | O_NOFOLLOW</code>, verifies directory/metadata/manifest identity and current bytes, derives current status from decision controls, and compares both CAS values. Any existing decision is final and returns stale; it is never deleted, flipped, or replaced. For a pending candidate, re-check both held root and candidate entry identities, then atomically publish exactly one selected structured lock with exclusive/no-replace dirfd semantics; that immutable lock is the canonical review audit record. Do not append new decisions to <code>reviews.jsonl</code>; the API may merge historical legacy log entries with the canonical decision lock for display. <code>SafetyGate</code> validates the ID and parses the structured approval through the same safe repository, comparing its digest with the freshly verified snapshot.

- [ ] **Step 4: Run all candidate repository tests**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q \
  tests/test_agent_paths.py \
  tests/test_candidate_manifest.py \
  tests/test_candidate_repository.py \
  tests/test_agent_phase7.py \
  tests/test_agent_promotion.py tests/test_agent_promote.py \
  tests/test_agent_propose_source_file.py \
  tests/test_api_agent.py tests/test_cli_json_output.py
~~~

Expected: all pass, including invalid-ID zero-write, lock/root/candidate swap, concurrent approve/reject, immutable-final-decision, and partial-publication tests.

- [ ] **Step 5: Commit**

~~~bash
git add src/quant_system/agent/candidate_fs.py src/quant_system/agent/models.py \
  src/quant_system/agent/candidate_pool.py \
  src/quant_system/agent/safety.py src/quant_system/agent/promotion.py \
  src/quant_system/agent/promote.py src/quant_system/agent/runner.py \
  src/quant_system/api/routes/agent.py src/quant_system/api/schemas/agent.py \
  src/quant_system/cli.py tests/test_candidate_repository.py \
  tests/test_agent_phase7.py tests/test_agent_promotion.py \
  tests/test_agent_promote.py tests/test_agent_propose_source_file.py \
  tests/test_api_agent.py tests/test_cli_json_output.py
git commit -m "fix(agent): make candidate writes immutable and approvals revision-bound"
~~~

---

### Task 4: Re-verify before one-shot load and promotion

**Files:**

- Modify: <code>src/quant_system/agent/promotion.py</code>
- Modify: <code>src/quant_system/agent/promote.py</code>
- Modify: <code>src/quant_system/factors/registry.py</code>
- Modify: <code>tests/test_agent_promotion.py</code>
- Modify: <code>tests/test_agent_promote.py</code>
- Modify: <code>tests/test_factor_registry_factory.py</code>

**Interfaces:**

- Loader and materializer consume <code>VerifiedCandidateSnapshot</code> and its already-verified <code>artifact_bytes</code>; neither reopens a candidate path.
- One-shot loader entry points receive <code>agent_output_dir</code>, never a direct/default candidates directory. Resident registry construction remains promoted-only.
- Authorization requires <code>approval_binding == "approved"</code> and an approval lock digest equal to the freshly computed manifest digest.
- Generated provenance contains only stable candidate ID, manifest schema/digest, and the UTC approval date parsed from the structured approval record. It contains no absolute candidate/lock/worktree path and never reads today's clock.

- [ ] **Step 1: Add tamper and legacy-lock RED tests**

~~~python
def test_loader_refuses_source_changed_after_digest_bound_approval(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id="tamper-task",
        goal="tamper",
        artifact_type="factor",
        filename="factor.py.candidate",
        content=_VALID_FACTOR_SOURCE,
    )
    pool.review(
        candidate_id=artifact.candidate_id,
        decision="approve",
        note="approved exact bytes",
        expected_manifest_digest=artifact.manifest_digest,
        expected_status="pending",
    )
    artifact.path.write_text(_VALID_FACTOR_SOURCE.replace("safe_factor", "changed_factor"))

    registry = build_default_factor_registry()
    with pytest.raises(CandidateIntegrityError):
        load_approved_factor_candidates(registry, agent_output_dir=tmp_path)
    assert "changed_factor" not in registry.factor_ids()
~~~

Add the equivalent materializer test: mutate candidate bytes after approval and assert no module, init, test, or lock file is written.

- [ ] **Step 2: Run and confirm RED**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q \
  tests/test_agent_promotion.py \
  tests/test_agent_promote.py \
  tests/test_factor_registry_factory.py
~~~

Expected: the new tests fail because current consumers authorize by lock existence.

- [ ] **Step 3: Use verified snapshots at the last responsible moment**

In the loader, enumerate through <code>CandidatePool(agent_output_dir)</code>, and for each valid ID:

~~~python
snapshot = load_verified_candidate_snapshot(
    agent_output_dir=agent_output_dir,
    candidate_id=candidate_id,
)
if snapshot.approval_binding != "approved":
    continue
source = snapshot.artifact_bytes["factor.py.candidate"].decode(
    "utf-8", errors="strict"
)
_check_source(source, snapshot.candidate_id)
~~~

Make internal <code>promote_candidate</code> accept a <code>VerifiedCandidateSnapshot</code> plus <code>expected_candidate_digest</code>; compare the expected digest before AST checks and use only <code>snapshot.artifact_bytes</code>. Candidate filesystem verification belongs to the caller immediately before it invokes this internal materializer. Replace current absolute <code>approved.lock</code> provenance and <code>date.today()</code> output with stable candidate ID/digest and the UTC approval date from <code>snapshot.review_record</code>. Keep every existing no-process/no-git/static-safety/exclusive-create test. Add a test that copies the same approved candidate to two different absolute roots, verifies snapshots, runs with two different mocked current dates, and gets byte-identical module/init/test output.

- [ ] **Step 4: Run promotion and registry suites**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q \
  tests/test_agent_promotion.py \
  tests/test_agent_promote.py \
  tests/test_factor_registry_factory.py \
  tests/test_cli_experiment_provider.py
~~~

Expected: all pass; legacy/unbound or changed candidates never compile.

- [ ] **Step 5: Commit**

~~~bash
git add src/quant_system/agent/promotion.py src/quant_system/agent/promote.py \
  src/quant_system/factors/registry.py \
  tests/test_agent_promotion.py tests/test_agent_promote.py \
  tests/test_factor_registry_factory.py tests/test_cli_experiment_provider.py
git commit -m "fix(agent): recheck candidate digest before research or promotion"
~~~

---

### Task 5: Digest-aware API, CLI, frontend compatibility, and HQA callers

**Files:**

- Modify: platform <code>src/quant_system/api/routes/agent.py</code>, <code>routes/factors.py</code>, <code>schemas/agent.py</code>, <code>cli.py</code>.
- Modify: platform <code>tests/test_api_agent.py</code>, <code>test_api_response_models.py</code>, <code>test_cli_json_output.py</code>, <code>test_frontend_openapi_generation.py</code>.
- Modify: platform <code>src/frontend/components/forms/AgentTaskForm.tsx</code>, <code>lib/api.ts</code>, and generated <code>lib/api.generated.ts</code>.
- Modify: HQA <code>hqa/quant_cli.py</code>, <code>hqa/factor_repro_cli.py</code>.
- Modify: HQA <code>tests/test_quant_cli.py</code>, <code>test_factor_repro.py</code>, <code>test_factor_repro_cli.py</code>.
- Modify: HQA <code>skills/hermes/hqa-quant/SKILL.md</code> and <code>tests/test_install.py</code>.

**Interfaces:**

- Candidate list/detail returns <code>approval_binding</code>, <code>integrity_state</code>, nullable authoritative <code>manifest_digest</code>, nullable non-authoritative <code>observed_manifest_digest</code>, <code>approval_enabled</code>, and stable nullable <code>integrity_error_code</code> per item.
- Review input requires <code>expected_manifest_digest</code>; stale target maps to HTTP 409 with code <code>candidate_revision_stale</code>.
- Review input also requires <code>expected_status: "pending"</code>; an already decided target maps to HTTP 409 <code>candidate_review_state_stale</code> and the first decision remains unchanged.
- Review of <code>migration_required</code> maps to HTTP 409 <code>candidate_migration_required</code>; corrupt maps to HTTP 409 <code>candidate_integrity_failed</code>. List stays 200 when another candidate is bad.
- Platform CLI review requires both <code>--expected-digest</code> and <code>--expected-status pending</code>.
- <code>hqa.quant_cli.run_agent_review(*, candidate_id, decision, note, expected_manifest_digest, expected_status, ...)</code> requires caller-supplied values as keyword arguments; it never lists/refetches a candidate to fill either value.
- <code>python3 -m hqa.factor_repro_cli approve</code> requires <code>--candidate-id</code>, <code>--expected-digest</code>, <code>--expected-status pending</code>, and <code>--note</code>. Propose/detail print the authoritative digest and exact approval syntax for the human to copy; list is informational-only and redacts any platform approval command. Observed migration evidence is never substituted.
- <code>skills/hermes/hqa-quant/SKILL.md</code> is part of the executable Gate 2 surface, not deferred documentation. Bump its version to <code>1.9.0</code>, replace the old two-value approve example, state that all four values come from one human-inspected verified item, and prohibit an approval handler from refetching them. <code>tests/test_install.py</code> proves both source and installed cards preserve that exact command.

- [ ] **Step 1: Write API/CLI RED contracts**

~~~python
def test_candidate_review_returns_409_for_stale_digest(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id="api-stale",
        goal="stale",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# candidate\n",
    )
    client = TestClient(create_app(agent_output_dir=tmp_path))
    response = client.post(
        f"/api/agent/candidates/{artifact.candidate_id}/review",
        json={
            "decision": "approve",
            "note": "reviewed",
            "expected_manifest_digest": "0" * 64,
            "expected_status": "pending",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_revision_stale"
    assert not (artifact.path.parent / "approved.lock").exists()


def test_unversioned_candidate_is_readable_but_review_is_disabled(tmp_path) -> None:
    _write_unversioned_candidate(tmp_path / "agent" / "candidates", "legacy-pending")
    client = TestClient(create_app(agent_output_dir=tmp_path))

    item = client.get("/api/agent/candidates").json()["candidates"][0]

    assert item["integrity_state"] == "migration_required"
    assert item["manifest_digest"] is None
    assert len(item["observed_manifest_digest"]) == 64
    assert item["approval_enabled"] is False
    response = client.post(
        "/api/agent/candidates/legacy-pending/review",
        json={
            "decision": "approve",
            "note": "must migrate first",
            "expected_manifest_digest": item["observed_manifest_digest"],
            "expected_status": "pending",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_migration_required"
~~~

Add API tests proving omission of <code>expected_status</code> returns 422 and a second decision returns 409 without changing the first lock. Add CLI tests proving omission of either <code>--expected-digest</code> or <code>--expected-status pending</code> exits 2 and writes no lock. Add API/CLI tests proving a corrupt item does not hide a verified item. Add HQA tests proving the authoritative digest and status printed by a verified list item are the exact values the human explicitly passes to review, while <code>migration_required</code>/<code>corrupt</code> items are printed with approval disabled and never invoke review.

Add these HQA and installed-skill assertions explicitly:

~~~python
def test_approve_requires_explicit_human_cas_values_and_never_refetches(
    monkeypatch, capsys
) -> None:
    seen = {}
    monkeypatch.setattr(
        cli.quant_cli,
        "run_list_candidates",
        lambda *args, **kwargs: pytest.fail("approve must not refetch"),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_agent_review",
        lambda **kwargs: seen.update(kwargs) or (0, "ok"),
    )

    rc = cli.main(
        [
            "approve",
            "--candidate-id", "factor-x-1",
            "--expected-digest", "a" * 64,
            "--expected-status", "pending",
            "--note", "translation confirmed",
        ]
    )

    assert rc == 0
    assert seen == {
        "candidate_id": "factor-x-1",
        "decision": "approve",
        "note": "translation confirmed",
        "expected_manifest_digest": "a" * 64,
        "expected_status": "pending",
    }


def test_installed_skill_documents_exact_gate2_cas_command(tmp_path) -> None:
    scripts_dest = _install(tmp_path)
    body = (scripts_dest.parent / "skills" / "hqa-quant" / "SKILL.md").read_text()
    assert "version: 1.9.0" in body
    assert (
        "approve --candidate-id <id> --expected-digest <sha256> "
        "--expected-status pending --note \"<translation-review>\""
    ) in body
    assert "never refetch" in body.lower()
~~~

Parametrize omissions of each of the four HQA approve options, an empty/whitespace-only note, a malformed digest, and an <code>--expected-status approved</code> attempt. Argument/local validation must exit 2 before <code>run_agent_review</code> is called. Update every existing <code>version: 1.8.0</code> assertion in <code>tests/test_install.py</code> to <code>1.9.0</code> in the same change.

- [ ] **Step 2: Run cross-contract tests and confirm RED**

Run:

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
./ai-quant/bin/python -m pytest -q tests/test_api_agent.py \
  tests/test_cli_json_output.py tests/test_api_response_models.py

cd /Users/sunyibo/programs/Hermes-quant-agent
./.venv/bin/pytest -q tests/test_quant_cli.py tests/test_factor_repro.py \
  tests/test_factor_repro_cli.py tests/test_install.py
~~~

Expected: schema/signature assertions fail.

- [ ] **Step 3: Implement exact request/response contracts**

Use:

~~~python
class AgentReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=1, max_length=2000)
    expected_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_status: Literal["pending"]
~~~

Catch domain errors from most specific to most general so subclasses cannot collapse into the revision code:

~~~python
try:
    record = runner.review(...)
except CandidateReviewStateStaleError as exc:
    raise _candidate_conflict(candidate_id, "candidate_review_state_stale") from exc
except CandidateMigrationRequiredError as exc:
    raise _candidate_conflict(candidate_id, "candidate_migration_required") from exc
except CandidateIntegrityError as exc:
    raise _candidate_conflict(candidate_id, "candidate_integrity_failed") from exc
except CandidateStaleError as exc:
    raise _candidate_conflict(candidate_id, "candidate_revision_stale") from exc
~~~

<code>_candidate_conflict</code> always returns HTTP 409 with <code>{"code", "resource": "agent_candidate", "id"}</code>. Add one direct API test for each branch and assert the pre-existing decision/control bytes and candidate bytes remain unchanged.

Make detail source preview come only from <code>VerifiedCandidateSnapshot.artifact_bytes</code>. Keep factors candidate loading derived from the route's injected <code>AgentOutputDirDep</code> established in Task 1; it must not call a process-global resolver. Update every candidate Typer command to accept an optional explicit agent root but otherwise call the same resolver; no command keeps a CWD-relative <code>data/agent_run</code> default. Review requires both <code>--expected-digest</code> and <code>--expected-status pending</code>. The old Agent Studio must first read the selected candidate detail and submit both values; if detail is unavailable or status is not pending, disable approve/reject rather than submitting without CAS.

Implement HQA approve with <code>choices=("pending",)</code> and pass all fields directly to the keyword-only <code>run_agent_review</code>. Neither function calls <code>run_list_candidates</code>, candidate detail, platform API, or any parser to replace supplied values. Update propose/list output so a verified item prints <code>candidate_id</code>, authoritative <code>manifest_digest</code>, <code>status=pending</code>, and the complete copyable approve command. A <code>migration_required</code> item prints only <code>observed_manifest_digest</code> with “migration evidence; approval disabled”; corrupt prints no digest/source.

For read-only migration visibility, list/detail may use <code>list_for_read</code>. Show a source preview for <code>migration_required</code> only through the same no-symlink/no-escape exact-byte reader used to compute <code>observed_manifest_digest</code>; label that digest “迁移证据，不能审批”. A corrupt item has no source preview. The old Agent Studio and new Hermes view disable controls whenever <code>approval_enabled</code> is false.

- [ ] **Step 4: Regenerate and verify both repositories**

Run:

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
npm --prefix src/frontend run generate:api-types
./ai-quant/bin/python -m pytest -q tests/test_api_agent.py \
  tests/test_cli_json_output.py tests/test_api_response_models.py \
  tests/test_frontend_openapi_generation.py
npm --prefix src/frontend run test
npm --prefix src/frontend run type-check
npm --prefix src/frontend run lint

cd /Users/sunyibo/programs/Hermes-quant-agent
./.venv/bin/pytest -q tests/test_quant_cli.py tests/test_factor_repro.py \
  tests/test_factor_repro_cli.py tests/test_install.py
~~~

Expected: all commands pass.

- [ ] **Step 5: Commit platform and HQA changes separately**

Platform:

~~~bash
git add src/quant_system/api/routes/agent.py \
  src/quant_system/api/routes/factors.py src/quant_system/api/schemas/agent.py \
  src/quant_system/cli.py src/frontend/components/forms/AgentTaskForm.tsx \
  src/frontend/lib/api.ts src/frontend/lib/api.generated.ts \
  tests/test_api_agent.py tests/test_cli_json_output.py \
  tests/test_api_response_models.py tests/test_frontend_openapi_generation.py
git commit -m "feat(agent): require candidate revision on every review surface"
~~~

HQA:

~~~bash
git add hqa/quant_cli.py hqa/factor_repro_cli.py tests/test_quant_cli.py \
  tests/test_factor_repro.py tests/test_factor_repro_cli.py \
  skills/hermes/hqa-quant/SKILL.md tests/test_install.py
git commit -m "fix(hqa): carry candidate digest through manual Gate 2 review"
~~~

The platform commit intentionally lands first: until the HQA commit follows, an old caller is rejected for omitting the digest, which is a safe fail-closed compatibility window. Do not run a real review between the two commits, and finish both repository commits before runtime smoke.

---

### Task 6: Dry-run-first legacy root audit and migration

**Files:**

- Modify: <code>src/quant_system/agent/candidate_fs.py</code>
- Create: <code>src/quant_system/agent/candidate_migration.py</code>
- Create: <code>tests/test_candidate_migration.py</code>
- Modify: <code>src/quant_system/cli.py</code>

**Interfaces:**

- <code>audit_candidate_roots(*, legacy_dir, agent_output_dir) -> CandidateMigrationReport</code> is read-only; canonical is always <code>resolve_candidates_dir(resolve_agent_output_dir(agent_output_dir))</code>.
- <code>apply_candidate_migration(report, backup_dir) -> CandidateMigrationReport</code> refuses if source facts differ from the audit.
- The report separately lists existing canonical candidates without <code>manifest.v1.json</code> as <code>canonical_unversioned</code>; apply may add a manifest without changing metadata/artifact bytes or granting approval.
- CLI command <code>agent migrate-candidates</code> defaults to dry-run JSON; <code>--apply</code> and an explicit backup directory are both required to write.
- Dry-run opens both roots with <code>create=False</code> and creates no root, lock, backup, manifest, or temp entry. Apply reads legacy source, writes backup, and mutates canonical only through Task 2/3 held-dirfd primitives.
- Every discovered directory name passes <code>_validate_candidate_id</code>. Invalid ID, directory/metadata identity mismatch, symlink/type failure, or drift is reported and never copied.
- Legacy, canonical, and backup roots must be three distinct non-overlapping trees: no pair may share the same held-FD identity, equal real path, or have an ancestor/descendant relationship. Validate planned paths before creating backup/canonical entries, then repeat with safely opened FDs immediately before any copy/write.

- [ ] **Step 1: Write migration RED tests**

~~~python
def test_migration_never_overwrites_conflicting_canonical_candidate(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    _write_legacy_candidate(legacy, "candidate-1", b"legacy\n", approved=True)
    _write_legacy_candidate(canonical, "candidate-1", b"canonical\n", approved=False)

    report = audit_candidate_roots(
        legacy_dir=legacy,
        agent_output_dir=agent_output,
    )

    assert report.conflicts == ["candidate-1"]
    assert report.copyable == []
    before = (canonical / "candidate-1" / "factor.py.candidate").read_bytes()
    with pytest.raises(CandidateMigrationConflict):
        apply_candidate_migration(report, backup_dir=tmp_path / "backup")
    assert (canonical / "candidate-1" / "factor.py.candidate").read_bytes() == before


def test_migration_never_mutates_legacy_source_tree(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    _write_legacy_candidate(legacy, "candidate-1", b"legacy\n", approved=True)
    before = _tree_fingerprint(legacy)

    report = audit_candidate_roots(
        legacy_dir=legacy,
        agent_output_dir=agent_output,
    )
    apply_candidate_migration(report, backup_dir=tmp_path / "backup")

    assert _tree_fingerprint(legacy) == before


def test_legacy_approval_is_preserved_as_evidence_but_not_authority(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    _write_legacy_candidate(legacy, "candidate-1", b"same\n", approved=True)
    report = audit_candidate_roots(
        legacy_dir=legacy,
        agent_output_dir=agent_output,
    )
    apply_candidate_migration(report, backup_dir=tmp_path / "backup")
    snapshot = CandidatePool(agent_output).get("candidate-1")
    assert snapshot.approval_binding == "legacy_unbound"
    assert (snapshot.candidate_dir / "legacy-approved.lock").exists()


def test_existing_canonical_candidate_gets_manifest_without_byte_or_authority_change(
    tmp_path,
) -> None:
    agent_output = tmp_path / "agent-output"
    canonical = agent_output / "agent" / "candidates"
    _write_legacy_candidate(canonical, "candidate-1", b"pending\n", approved=False)
    source = canonical / "candidate-1" / "factor.py.candidate"
    metadata = canonical / "candidate-1" / "metadata.json"
    before = (source.read_bytes(), metadata.read_bytes())

    report = audit_candidate_roots(
        legacy_dir=tmp_path / "missing-legacy",
        agent_output_dir=agent_output,
    )

    assert report.canonical_unversioned == ["candidate-1"]
    apply_candidate_migration(report, backup_dir=tmp_path / "backup")
    assert (source.read_bytes(), metadata.read_bytes()) == before
    assert (canonical / "candidate-1" / "manifest.v1.json").is_file()
    assert CandidatePool(agent_output).get(
        "candidate-1"
    ).approval_binding == "pending"
~~~

Add tests that dry-run against absent roots leaves <code>tmp_path</code> byte-for-byte empty; <code>../../outside</code>, absolute, slash/backslash, dot, and reserved candidate directory names are rejected without canonical/backup writes; and <code>migration_required</code>, <code>corrupt</code>, and <code>verified</code> are reported as three mutually exclusive integrity states. Parametrize root overlap with legacy==canonical, backup==legacy, backup inside legacy, legacy inside backup, canonical inside legacy, legacy inside canonical, backup inside canonical, and canonical inside backup; every case must fail before root/lock/backup creation and leave all existing tree fingerprints unchanged. Add barrier tests that replace the legacy root, canonical root, pool lock, or canonical candidate entry after open. Apply must detect identity drift, leave the replacement/outside tree unchanged, and preserve the legacy source tree's complete inode/type/path/byte fingerprint on both success and failure.

- [ ] **Step 2: Run and confirm RED**

Run: <code>./ai-quant/bin/python -m pytest -q tests/test_candidate_migration.py</code>

Expected: module import fails.

- [ ] **Step 3: Implement idempotent audit/apply**

The report stores resolved legacy root, resolved agent-output/canonical roots, every validated candidate ID, source/canonical manifest digests, <code>copyable</code>, <code>identical</code>, <code>conflicts</code>, <code>canonical_unversioned</code>, <code>legacy_unbound</code>, and exactly one integrity state (<code>verified</code>, <code>migration_required</code>, or <code>corrupt</code>) per observed item. Before audit/apply, compare no-symlink real paths component-wise for equality/containment and, for roots that exist, compare held <code>st_dev/st_ino</code>. For an absent backup, validate its planned normalized absolute path before creation, safely create/open it, then repeat both overlap checks. Apply:

1. safely reopens the legacy root with <code>create=False</code>, reacquires the canonical root dirfd lock, and safely opens/creates the backup root only after <code>--apply</code> validation;
2. recomputes both root/candidate identities and exact digests through held FDs and rejects drift;
3. copies each legacy-only candidate into a canonical private staging directory using exclusive dirfd writes;
4. inside the staged canonical copy only, preserves an old decision as <code>legacy-approved.lock</code> or <code>legacy-rejected.lock</code>; it never modifies or renames the legacy source entry;
5. builds and verifies <code>manifest.v1.json</code> in the exact-ID staged directory;
6. publishes through <code>rename_directory_noreplace_at</code> without overwrite;
7. writes and fsyncs a complete backup through safe dirfds before canonical publication; the legacy source tree remains read-only and its inode/type/path/byte fingerprint must be identical before and after both successful and failed apply;
8. for each <code>canonical_unversioned</code> item, backs up the complete directory, re-verifies all audited bytes and held root/candidate identities under the root lock, atomically adds <code>manifest.v1.json</code> with no-replace semantics, and preserves pending status or moves a legacy-format decision to unbound evidence using only same-dirfd no-replace operations;
9. is a no-op on identical re-run.

Migration code must not contain <code>Path.open</code>, <code>Path.mkdir</code>, path-string <code>tempfile</code>, path-based <code>shutil.copy*</code>, <code>os.replace</code>, or overwrite-capable <code>os.rename</code>. Add a static source test for those bypasses.

Add Typer options:

~~~python
@agent_app.command("migrate-candidates")
def agent_migrate_candidates(
    legacy_dir: Path | None = None,
    agent_output_dir: Path | None = None,
    apply: bool = False,
    backup_dir: Path | None = None,
) -> None:
    resolved_legacy = resolve_legacy_candidates_dir(legacy_dir)
    resolved_agent_output = resolve_agent_output_dir(agent_output_dir)
    report = audit_candidate_roots(
        legacy_dir=resolved_legacy,
        agent_output_dir=resolved_agent_output,
    )
    if apply:
        if backup_dir is None:
            raise typer.BadParameter("--backup-dir is required with --apply")
        report = apply_candidate_migration(report, backup_dir=backup_dir)
    typer.echo(report.model_dump_json())
~~~

There is no <code>canonical_dir</code>/<code>--candidates-dir</code> option. Add a CLI test that <code>chdir</code>s outside the repository, runs dry-run with no path flags and a test <code>QS_AGENT_OUTPUT_DIR</code>, and observes exactly the same canonical root as API/list/run-config; HQA wrapper tests assert the environment is inherited rather than deriving a CWD-relative path.

- [ ] **Step 4: Run tests and real dry-run only**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q tests/test_candidate_migration.py
./ai-quant/bin/quant-system agent migrate-candidates
~~~

Expected on this machine: legacy root absent; no conflicts; <code>canonical_unversioned</code> contains the one pending candidate that needs a v1 manifest. The command must not change its files in dry-run mode.

- [ ] **Step 5: Commit code; stop before real apply**

~~~bash
git add src/quant_system/agent/candidate_fs.py \
  src/quant_system/agent/candidate_migration.py src/quant_system/cli.py \
  tests/test_candidate_migration.py
git commit -m "feat(agent): add conflict-safe candidate root migration"
~~~

Do not run <code>--apply</code> until the user separately authorizes mutation of real candidate data after seeing the dry-run JSON and backup path.

---

### Task 7: Persistent isolated Gate 3 worktree and scoped patch

**Files:**

- Create: <code>src/quant_system/agent/promotion_workspace.py</code>
- Create: <code>tests/test_promotion_workspace.py</code>
- Modify: <code>src/quant_system/agent/promote.py</code>
- Modify: <code>src/quant_system/cli.py</code>

**Interfaces:**

- Internal <code>prepare_promotion_workspace</code> returns <code>PromotionWorkspaceResult</code> from explicit repository, agent-output root, candidate ID, expected digest, base commit, promotion root, and worktree root keyword arguments. It resolves the candidate only through <code>CandidatePool(agent_output_dir)</code> and re-verifies immediately before materialization.
- Existing public <code>agent promote-candidate</code> becomes the only prepare entry and delegates to <code>prepare_promotion_workspace</code>. The old direct main-worktree materializer flags/path are removed or rejected; <code>promote_candidate</code> remains internal Python only.
- Exact public prepare contract is <code>agent promote-candidate --candidate-id ID --expected-digest SHA256 --base-commit COMMIT</code>. All three options are required; there is no public candidates/library/tests/repo/promotion/worktree path option. Missing any required option exits 2 before resolver, candidate, git, state, or worktree mutation.
- Prepare stdout is one JSON object with exactly <code>promotion_id</code>, <code>worktree</code>, <code>patch</code>, and <code>manifest</code>. Human instructions go to stderr so callers can parse stdout deterministically.
- Exact status contract is <code>agent promotion-status --promotion-id ID</code>. Exact cleanup contract is <code>agent cleanup-promotion --promotion-id ID [--abandon]</code>. They locate repo/candidate/worktree from the validated immutable manifest, audited mutable state, and standard resolver; they accept no candidate, digest, base, repo, worktree, or state-path override. <code>--abandon</code> is false by default and is the only force/removal escape for an unreviewed workspace.
- No shell strings: Git calls are argument arrays with <code>shell=False</code>.
- Output persists under <code>resolve_agent_output_dir()/agent/promotions/{promotion_id}</code>; detached worktree persists under a repo-independent managed temp root until explicit cleanup.
- The system creates neither branch nor commit. After reviewing the exact scoped diff, the human creates a named branch in the worktree and commits; cleanup refuses a detached commit that is not reachable from a named local branch unless the human explicitly uses <code>--abandon</code>.
- The only scoped paths are promoted factor module, promoted package <code>__init__.py</code>, and generated factor test.
- <code>manifest.v1.json</code> is immutable and deterministic: it contains no absolute candidate/worktree/promotion path, wall clock, or current date. A separate mutable <code>state.json</code> stores the managed worktree path and lifecycle. <code>promotion_id</code> is derived from the canonical candidate ID/digest, base commit, scoped paths, resulting byte digests, and patch digest, so same inputs are idempotent and concurrent different facts conflict.
- <code>state.json</code> is untrusted input on every status/cleanup. Its strict schema binds <code>promotion_id</code>, immutable-manifest SHA-256, fixed platform repo identity, managed-root identity, direct-child worktree path, and lifecycle. Unknown/missing fields, symlinks, path escape, manifest mismatch, or Git worktree-registration mismatch fail closed—even with <code>--abandon</code>.

- [ ] **Step 1: Write Gate 3 isolation RED tests**

~~~python
def test_promotion_uses_detached_worktree_and_ignores_unrelated_main_dirty(tmp_path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "unrelated.txt").write_text("user dirty\n", encoding="utf-8")
    fingerprint = _fingerprint(repo / "unrelated.txt")
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)

    result = prepare_promotion_workspace(
        repo_dir=repo,
        agent_output_dir=agent_output,
        candidate_id=candidate_id,
        expected_candidate_digest=digest,
        base_commit=_git(repo, "rev-parse", "HEAD").strip(),
        promotion_root=tmp_path / "promotion-state",
        worktree_root=tmp_path / "worktrees",
    )

    assert result.worktree_path != repo
    assert result.patch_path.read_bytes().startswith(b"diff --git ")
    assert _fingerprint(repo / "unrelated.txt") == fingerprint
    assert _git(repo, "status", "--short") == " M unrelated.txt\n"
    assert _git(result.worktree_path, "log", "-1", "--format=%H").strip() == result.base_commit


def test_promotion_refuses_changed_candidate_or_existing_scoped_target(tmp_path) -> None:
    repo = _git_repo(tmp_path)
    agent_output, candidate_id, digest = _approved_candidate(tmp_path)
    candidate = agent_output / "agent" / "candidates" / candidate_id
    (candidate / "factor.py.candidate").write_text(_CHANGED_FACTOR, encoding="utf-8")
    with pytest.raises(PromotionWorkspaceError, match="candidate"):
        prepare_promotion_workspace(
            repo_dir=repo,
            agent_output_dir=agent_output,
            candidate_id=candidate_id,
            expected_candidate_digest=digest,
            base_commit=_git(repo, "rev-parse", "HEAD").strip(),
            promotion_root=tmp_path / "state",
            worktree_root=tmp_path / "worktrees",
        )
~~~

Also test base commit mismatch, concurrent same promotion, deterministic patch/manifest digest across different candidate/worktree roots and mocked current dates, scoped target collision, any dirty/untracked scoped path in the user's main worktree, no automatic commit, explicit cleanup refusing an uncommitted worktree, and cleanup refusing a clean but unreferenced detached human commit until a named branch contains it.

Invoke the real Typer command handler with <code>CliRunner</code> against injected temp internals. Parametrize omission of <code>--candidate-id</code>, <code>--expected-digest</code>, and <code>--base-commit</code>; assert exit 2 and byte-identical candidate/repo/promotion/worktree fingerprints. On success, assert stdout parses to exactly:

~~~python
assert set(payload) == {"promotion_id", "worktree", "patch", "manifest"}
assert Path(payload["worktree"]) != repo
assert Path(payload["patch"]).read_bytes() == result.patch_path.read_bytes()
assert Path(payload["manifest"]).read_bytes() == result.manifest_path.read_bytes()
~~~

Assert <code>promotion-status --help</code> exposes only required <code>--promotion-id</code>, and <code>cleanup-promotion --help</code> exposes only required <code>--promotion-id</code> plus optional <code>--abandon</code>. Reject empty/dot/<code>../</code>/slash/backslash/absolute promotion IDs before state lookup. CLI help and an AST/source test must prove <code>agent_promote_candidate</code> calls only <code>prepare_promotion_workspace</code>, no public direct materializer flags remain, and <code>src/quant_system/cli.py</code> contains no call to <code>promote_candidate</code>.

Add cleanup/status state-injection tests that modify <code>state.json</code> to point at the main platform repo, another registered repository, an arbitrary outside directory, a symlink under the managed root, a nested rather than direct-child path, the correct path with a different promotion ID, and the correct path with a different manifest digest/repo identity. Invoke both default cleanup and <code>--abandon</code>; every case must refuse and leave the main repo, every other repo, outside tree, Git worktree registry, patch, manifest, and candidate fingerprints unchanged.

The patch test must prove both newly created factor/test files and the modified package init appear in an exact three-path <code>--binary --full-index</code> patch, replay it into a second clean checkout at the base commit, and compare all three replayed bytes and SHA-256 values to the manifest. A final-status test must tamper with the worktree after patch creation and prove the human commit is not accepted as Gate 3 completion.

- [ ] **Step 2: Run and confirm RED**

Run: <code>./ai-quant/bin/python -m pytest -q tests/test_promotion_workspace.py</code>

Expected: module import fails.

- [ ] **Step 3: Implement the orchestrator while preserving pure materializer**

Use narrow argument-array Git runners; patch-producing commands capture bytes and never round-trip through text decoding:

~~~python
def _git_text(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        shell=False,
    )


def _git_bytes(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        check=check,
        capture_output=True,
        text=False,
        shell=False,
    )
~~~

Before any write:

- resolve and verify base commit with <code>rev-parse --verify BASE^{commit}</code>, require it equals the user's main-worktree <code>git rev-parse HEAD</code>, then repeat that equality check under the promotion-state lock immediately before worktree creation;
- validate candidate ID, re-verify the digest-bound approved candidate through <code>CandidatePool(agent_output_dir)</code>, and retain its verified bytes;
- derive factor ID/class statically;
- calculate the exact three scoped relative paths;
- refuse existing factor/test target at the base commit;
- run <code>git status --porcelain=v1 --untracked-files=all -- scoped paths</code> in the user's main worktree and refuse any output while allowing unrelated dirty paths;
- acquire an exclusive promotion-state lock.

Under that lock, repeat both main <code>HEAD == base</code> and scoped-status-empty checks, then re-verify the candidate/digest immediately before <code>git worktree add</code>. After materialization and replay but before writing immutable promotion state, verify the candidate once more and require the same digest; any drift removes only the new isolated/replay worktrees and publishes no promotion record.

Then:

1. <code>git worktree add --detach WORKTREE BASE</code>;
2. call the existing materializer with paths rooted inside WORKTREE;
3. run only <code>git add --intent-to-add -- NEW_FACTOR NEW_TEST</code> inside the isolated worktree. Assert <code>git diff --cached --name-only</code> is empty, so intent-to-add makes complete new-file content visible to working-tree diff without staging content;
4. capture canonical patch bytes with <code>["git", "-C", worktree, "diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/", "--", *scoped_paths]</code>;
5. require working-tree HEAD still equals base; require <code>git diff --name-status -- scoped_paths</code> to be exactly new factor <code>A</code>, init <code>M</code>, new test <code>A</code>; require no fourth path anywhere in <code>git status --porcelain=v1 --untracked-files=all</code>; and require new-file-mode/<code>/dev/null</code> entries plus complete bytes for both new files in the patch;
6. create a second detached clean worktree at the same base, run <code>git apply --check --binary PATCH</code> then <code>git apply --binary PATCH</code>, require only the exact three scoped paths changed, compare their exact bytes/SHA-256 values to the first worktree, then remove only this internal replay worktree;
7. write immutable patch bytes and canonical <code>manifest.v1.json</code> with schema version, deterministic promotion ID, base commit, candidate ID/digest, exact ordered scoped paths, each resulting Git mode and SHA-256, and patch SHA-256. Exclude worktree path, absolute roots, timestamps, current date, and mutable status. Write strict <code>state.json</code> separately with promotion ID, manifest SHA-256, fixed platform repo <code>st_dev/st_ino</code>, managed-root <code>st_dev/st_ino</code>, direct-child worktree path, and <code>status="awaiting_human_commit"</code>;
8. emit the exact four-field JSON result on stdout and the human-only next sequence on stderr: inspect <code>git diff --binary --full-index -- scoped_paths</code>, create named branch <code>codex/promotion-{promotion_id}</code>, stage only the scoped paths, review the staged diff, and commit;
9. <code>prepare</code>/<code>status</code> never run content-staging <code>git add</code>, <code>git switch</code>, <code>git branch</code>, <code>git commit</code>, <code>git push</code>, or review-worktree removal. The sole automated review-index mutation is exact-path <code>--intent-to-add</code>; removal of the temporary replay worktree is internal verification, while removal of the persistent human review worktree belongs only to explicit cleanup.

Refactor <code>agent promote-candidate</code> to the exact prepare contract above, and add the exact promotion-ID-only status/cleanup commands. Before either command touches Git or a filesystem target, validate promotion ID; safely open the promotion directory/manifest/state without following symlinks; require strict schemas and state promotion/manifest binding; require recorded repo identity equals the fixed platform-repo constant; require the worktree is a no-symlink direct child named for that promotion under the fixed managed root; and parse <code>git worktree list --porcelain -z</code> from that fixed repo to require the exact registered worktree path. Never trust a repo/root/path supplied only by mutable state.

After state validation, status records the reviewed commit only when the user's current main-worktree HEAD still equals the recorded base, the review worktree is clean, its HEAD is exactly one commit whose parent is that base, <code>git diff-tree</code> equals the exact scoped path set, each commit blob's mode/bytes/digest equals the manifest, the candidate still verifies to its recorded digest, and <code>git for-each-ref --contains HEAD refs/heads</code> returns a named local branch.

Because a committed worktree has an empty working-tree diff, status must recompute canonical commit patch bytes with the same options as prepare plus <code>BASE..HEAD</code>:

~~~python
committed_patch = _git_bytes(
    worktree,
    "diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv",
    "--src-prefix=a/", "--dst-prefix=b/", f"{base_commit}..HEAD",
    "--", *scoped_paths,
).stdout
if hashlib.sha256(committed_patch).hexdigest() != manifest.patch_sha256:
    raise PromotionWorkspaceError("committed patch differs from reviewed patch")
if committed_patch != patch_path.read_bytes():
    raise PromotionWorkspaceError("committed patch bytes are not the prepared patch")
~~~

Tests must prove status does not mistakenly hash the now-empty <code>git diff -- scoped_paths</code>. Cleanup re-runs the full durable reviewed-commit check or requires <code>--abandon</code>; default cleanup refuses uncommitted, dirty, detached-unreferenced, changed-candidate, changed-patch, base/head mismatch, or invalid-state workspaces. Explicit <code>--abandon</code> may use forced worktree removal but must retain an audit state marked abandoned. <code>promote-candidate</code> and <code>promotion-status</code> never remove the persistent worktree.

- [ ] **Step 4: Run pure and workspace promotion tests**

Run:

~~~bash
./ai-quant/bin/python -m pytest -q tests/test_agent_promote.py \
  tests/test_promotion_workspace.py tests/test_agent_promotion.py
./ai-quant/bin/python -m ruff check src/quant_system/agent/promote.py \
  src/quant_system/agent/promotion_workspace.py tests/test_promotion_workspace.py
~~~

Expected: all pass; the static test still proves <code>promote.py</code> imports no git/process module; the workspace test proves the user's main dirty fingerprint is unchanged.

Also run:

~~~bash
./ai-quant/bin/quant-system agent promote-candidate --help
./ai-quant/bin/quant-system agent promotion-status --help
./ai-quant/bin/quant-system agent cleanup-promotion --help
rg -n "promote_candidate\(" src/quant_system/cli.py
~~~

Expected: prepare help requires candidate ID/digest/base and exposes no direct path/materializer flags; status accepts only promotion ID; cleanup accepts only promotion ID plus explicit abandon; the source search returns no direct materializer call.

- [ ] **Step 5: Commit**

~~~bash
git add src/quant_system/agent/promotion_workspace.py src/quant_system/agent/promote.py \
  src/quant_system/cli.py tests/test_promotion_workspace.py tests/test_agent_promote.py
git commit -m "feat(agent): prepare Gate 3 diffs in isolated review worktrees"
~~~

---

### Task 8: Full verification, independent code review, and documentation reconciliation

**Files:**

- Reconcile platform live docs: <code>AGENTS.md</code>, <code>README.md</code>, and <code>docs/INDEX.md</code>.
- Reconcile HQA live docs: <code>AGENTS.md</code>, <code>README.md</code>, <code>docs/README.md</code>, <code>skills/hermes/hqa-quant/SKILL.md</code>, <code>docs/design/vision-daily-life.md</code>, <code>docs/design/hermes_quant_agent_plan.md</code>, <code>docs/design/2026-07-01-roadmap-phases-0b-4.md</code>, and D-31 <code>docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md</code>.
- Do not modify historical plans, completed delivery records, archived phase docs, or checkbox history merely to make them look current.

**Interfaces:**

- Consumes every prior task.
- Produces current, evidence-backed project status; does not apply the real migration or perform a real promotion.

- [ ] **Step 1: Run focused platform safety suites**

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
./ai-quant/bin/python -m pytest -q \
  tests/test_candidate_manifest.py \
  tests/test_candidate_repository.py \
  tests/test_candidate_migration.py \
  tests/test_agent_phase7.py \
  tests/test_api_agent.py \
  tests/test_agent_propose_source_file.py \
  tests/test_agent_promotion.py \
  tests/test_agent_promote.py \
  tests/test_promotion_workspace.py \
  tests/test_factor_registry_factory.py \
  tests/test_cli_experiment_provider.py \
  tests/test_cli_json_output.py \
  tests/test_api_response_models.py \
  tests/test_frontend_openapi_generation.py \
  tests/test_frontend_e2e_config.py
./ai-quant/bin/python -m ruff check src/quant_system tests
~~~

Expected: all pass.

- [ ] **Step 2: Run frontend and HQA caller gates**

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
npm --prefix src/frontend run test
npm --prefix src/frontend run type-check
npm --prefix src/frontend run lint

cd /Users/sunyibo/programs/Hermes-quant-agent
./.venv/bin/pytest -q tests/test_quant_cli.py tests/test_factor_repro.py \
  tests/test_factor_repro_cli.py tests/test_install.py
~~~

Expected: all pass.

- [ ] **Step 3: Request adversarial code review**

Use <code>superpowers:requesting-code-review</code> and the user-requested Code Reviewer agent. The review prompt must require:

~~~text
Try to approve bytes different from the reviewed manifest; race approve/reject
and candidate regeneration; use empty/dot/../../absolute/slash/backslash/reserved
candidate IDs; swap candidate root/lock/candidate entries after dirfd open; use
symlink/FIFO/path traversal; corrupt a manifest; reuse a legacy lock; mutate the
candidate between approval and compile; bypass explicit HQA Gate 2 CAS; omit Gate
3 CLI arguments; produce an incomplete intent-to-add patch; tamper base/head/scoped
bytes; contaminate the main worktree; and find any path that commits or executes
resident paper/live code. Report findings by severity with exact files.
~~~

Address accepted findings using <code>superpowers:receiving-code-review</code> and rerun the affected plus full gates.

- [ ] **Step 4: Run complete repository gates**

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
./scripts/verify.sh

cd /Users/sunyibo/programs/Hermes-quant-agent
./.venv/bin/pytest
~~~

Expected: both complete suites pass. Record exact counts from output; do not reuse historical counts.

- [ ] **Step 5: Reconcile docs and commit**

Update docs with these exact status facts:

- one repo-anchored canonical candidate root, its <code>QS_AGENT_OUTPUT_DIR</code> override, and the fact that CWD/<code>QS_DATA_DIR</code> do not relocate it;
- current real dry-run migration result;
- real data not migrated without separate authorization;
- the <code>verified</code>/<code>migration_required</code>/<code>corrupt</code> read states and <code>legacy_unbound</code> non-authority;
- Gate 2's explicit human <code>candidate-id + expected-digest + expected-status=pending + note</code> CAS command and no-refetch rule;
- Gate 3's required candidate/digest/base prepare command, four-field result, promotion-ID-only status/cleanup, explicit-only abandon, isolated review worktree, and no automatic commit;
- new Hermes approval UI remains disabled until the frontend/bridge gates.

Use each live document for its existing role: agent rules in <code>AGENTS.md</code>; user-facing commands/capabilities in root <code>README.md</code>; current execution truth in HQA <code>docs/README.md</code> and platform <code>docs/INDEX.md</code>; Hermes command wording in the installed skill source; experience language in <code>vision-daily-life.md</code>; system flow in <code>hermes_quant_agent_plan.md</code>; decision/delivery status in the active roadmap; and security/design truth in D-31. Mark this candidate baseline delivered only after fresh gates pass, while later D-31 frontend/bridge approval exposure remains pending.

Commit the two repositories separately and stage only the named files:

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
git add AGENTS.md README.md docs/INDEX.md
git commit -m "docs(agent): record candidate integrity and Gate 3 delivery"
git diff --check HEAD^ HEAD

cd /Users/sunyibo/programs/Hermes-quant-agent
git add AGENTS.md README.md docs/README.md skills/hermes/hqa-quant/SKILL.md \
  docs/design/vision-daily-life.md docs/design/hermes_quant_agent_plan.md \
  docs/design/2026-07-01-roadmap-phases-0b-4.md \
  docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md
git commit -m "docs(agent): reconcile candidate integrity and Gate 3 delivery"
git diff --check HEAD^ HEAD
git status --short --branch
~~~

Expected: docs match current code/test evidence; unrelated dirty files remain untouched.

## Completion criteria

- API, CLI, one-shot loader, HQA, migration, and promotion all resolve the same canonical candidate through <code>resolve_agent_output_dir</code>; active candidate code has no CWD-relative <code>Path("data/agent_run")</code>, <code>QS_DATA_DIR</code> coupling, module-level candidate constant, or direct candidates-directory option.
- One shared candidate-ID validator protects creation/get/review/detail/SafetyGate/CLI/migration/promotion; empty/dot/<code>../../</code>/absolute/slash/backslash/noncanonical/reserved IDs produce zero writes, and directory/metadata/manifest IDs must agree.
- A candidate's metadata/artifacts are immutable after atomic publication.
- Same-ID retries are exactly idempotent or fail with conflict; they never overwrite.
- Candidate write/review/migration uses held no-follow dirfds, verified regular locks/controls, fsync, and no-replace publication; root/lock/candidate swaps fail closed without writing the replacement tree.
- Approval is explicit expected-digest plus <code>expected_status=pending</code> CAS, final decisions never flip, and stale/legacy approval never authorizes.
- HQA and its installed skill require human-supplied candidate ID/digest/pending/note and never refetch values during approval.
- Every compile/materialize path re-verifies exact bytes.
- The real legacy-root command remains dry-run until separately authorized.
- Until real apply is separately authorized, <code>migration_required</code>/<code>corrupt</code> candidates remain individually visible for read-only diagnosis beside <code>verified</code> items but expose no authoritative approval digest and cannot mutate or execute; legacy source bytes/types/inodes remain unchanged.
- Gate 3 prepare requires candidate ID/digest/base, emits promotion ID/worktree/patch/manifest, and creates a complete intent-to-add, binary/full-index, replay-verified three-path patch in a persistent review workspace. Status/cleanup locate it only by promotion ID, committed status replays <code>BASE..HEAD</code>, main worktree fingerprints remain unchanged, and default cleanup cannot orphan an unreferenced human commit; abandon is explicit only.
- Neither repository adds a paper/live path, automatic commit, provider call, or browser-side approval bypass.
- All listed platform/HQA live docs agree with fresh delivery evidence; historical plans remain historical.
- Focused and complete two-repository test gates pass with fresh evidence.
