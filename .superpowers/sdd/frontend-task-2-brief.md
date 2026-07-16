### Task 2: F1 clickable full-state prototype

**Files:**

- Create <code>docs/design/hermes-workbench/f1/prototype.html</code>.
- Create <code>docs/design/hermes-workbench/f1/prototype.css</code>.
- Create five JSON state catalogs.
- Modify <code>docs/design/hermes-workbench/README.md</code>.

**Interfaces:**

- Consumes the exact selected F0 direction and user adjustments.
- Produces a keyboard-operable local prototype covering the complete state matrix; no production import or network.

- [ ] **Step 1: Define complete strict state catalogs**

Each JSON file has this root shape:

~~~json
{
  "schema_version": "1.0",
  "surface": "home",
  "default_state": "normal",
  "states": [
    {
      "id": "normal",
      "title": "1 项需要你确认，其余研究运行正常",
      "status": "available",
      "announcements": [],
      "actions": [{"id": "approval-1", "label": "查看准确摘要"}],
      "technical": [{"label": "source", "value": "automation_status"}]
    }
  ]
}
~~~

Use these exact state IDs:

- home: <code>empty/loading/normal/degraded/hermes_offline</code>
- conversation: <code>sending/queued/streaming/reconnecting/stopping/reconciling/failed/quota/fallback</code>
- tasks: <code>queued/running/waiting_gate/stop_requested/reconciling/completed/partial/failed/stopped</code>
- approvals: <code>available/approved/rejected/expired/stale/digest_mismatch</code>
- results: <code>loading/partial/no_data/audit_warning/source_missing</code>

Each state must include Chinese/English copy, one long error, and non-color status text.

- [ ] **Step 2: Implement state navigation and the full research walkthrough**

Prototype navigation must traverse:

~~~text
提出目标
→ Hermes 结构化计划
→ Gate 1 formula/plan confirmation
→ streaming execution with real event labels
→ completed_degraded result
→ Gate 2 exact manifest summary
→ Gate 3 scoped diff summary
~~~

The prototype uses only the exact local catalogs <code>fetch("./states/home.json")</code>, <code>conversation.json</code>, <code>tasks.json</code>, <code>approvals.json</code>, and <code>results.json</code>, plus DOM APIs. It must not submit a form or contact localhost services. Include a visible “prototype data” label outside the simulated product chrome so it cannot be mistaken for a live session.

- [ ] **Step 3: Add keyboard and responsive acceptance script**

In prototype JavaScript, provide state buttons with <code>aria-pressed</code>, restore focus after modal-like approval detail closes, and announce state transitions through one <code>aria-live="polite"</code> region. On mobile, order content as status → conversation → plan/execution → result → composer.

- [ ] **Step 4: Independent review and written user gate**

The independent reviewer clicks the complete walkthrough at all four viewports and records:

~~~markdown
## F1 review

- Full lifecycle: pass
- State catalog: pass
- 1440/1280/768/390: pass
- Keyboard-only: pass
- Reduced motion: pass
- Horizontal overflow: none
- Console errors/warnings: 0/0
~~~

Then stop for written user approval. Record the actual approval in the README; do not create anything under <code>src/frontend/app</code>, <code>components</code>, or <code>lib</code> before it.

- [ ] **Step 5: Commit approved prototype**

~~~bash
git add docs/design/hermes-workbench/f1 docs/design/hermes-workbench/README.md
git commit -m "docs(frontend): approve Hermes full-state interaction prototype"
~~~

---

