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

