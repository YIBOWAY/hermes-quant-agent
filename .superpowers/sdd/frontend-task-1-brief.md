### Task 1: F0 professional visual directions

**Files:**

- Create all <code>docs/design/hermes-workbench/f0/</code> files.
- Create <code>docs/design/hermes-workbench/README.md</code>.

**Interfaces:**

- Consumes the approved D-31 information architecture and real 9H field lengths.
- Produces three directly browsable, full-size directions with identical content/state coverage.

- [ ] **Step 1: Dispatch the professional design agent with a fixed brief**

The executing agent must use the <code>web-design-engineer</code> skill and receive this exact brief:

~~~text
Design three high-fidelity directions for the approved Hermes unified research
workbench. Do not reuse or trace the .superpowers brainstorming preview. Use the
platform's real dark theme/token/font/icon vocabulary, real Chinese and English
copy, long run IDs, one failed automation, one pending approval, one recent
factor result, and an honest disabled conversation boundary.

Every direction must show:
1. idle Today view,
2. active conversation/execution composition,
3. approval state,
4. factor/backtest/experiment result composition,
5. 1440, 1280, 768 and 390 responsive behavior without scaling the whole UI.

Direction A: COO desk — action and status first.
Direction B: research timeline — change and progress first.
Direction C: quiet split canvas — conversation and result first, but idle mode
still answers safety/action/current-work/recent-result in five seconds.

Only the global top SafetyStrip may show paper/live/kill/API. Normal automation
compresses to one row. Technical cron/run/path details are collapsed.
~~~

- [ ] **Step 2: Implement a shared full-size frame**

Create <code>shared.css</code> with real responsive breakpoints, not transform scaling:

~~~css
:root {
  color-scheme: dark;
  --bg: #0c0d10;
  --surface: #13151a;
  --surface-2: #181b21;
  --line: #2a2e37;
  --text: #f1f3f6;
  --muted: #9ca3af;
  --hermes: #8b7cf6;
  --warning: #f5b942;
  --danger: #f06a6a;
  --success: #55c98f;
  font-family: Inter, "PingFang SC", system-ui, sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; min-width: 320px; background: var(--bg); color: var(--text); }
.safety { height: 36px; display: grid; place-items: center; border-bottom: 1px solid #5c451c; }
.prototype { min-height: calc(100vh - 36px); display: grid; }
button, a, input, textarea { min-height: 44px; }
:focus-visible { outline: 2px solid var(--hermes); outline-offset: 3px; }
@media (max-width: 1279px) { .secondary-panel { display: none; } }
@media (max-width: 767px) {
  .desktop-only { display: none !important; }
  .prototype { display: block; }
  .content { padding: 16px; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
~~~

Each direction imports only this local stylesheet plus its additive direction rules.

- [ ] **Step 3: Build each direction with the same realistic content**

Each HTML file must include these exact visible facts so comparison is about hierarchy, not content:

~~~html
<div class="safety" role="status">
  仅模拟 · 实盘交易已禁用 · 熔断开关 开 · 接口 OK
</div>
<main class="prototype">
  <section aria-labelledby="today-title">
    <p>7 月 13 日 · 今日</p>
    <h1 id="today-title">1 项需要你确认，其余研究运行正常</h1>
    <article>
      <h2>研究审批项</h2>
      <p>factor-momentum_20d_reversal-323b045e4b</p>
      <button type="button">查看准确摘要</button>
    </article>
    <article>
      <h2>自动化 3/4 正常</h2>
      <p>weekly_review 已过期；最近成功 2026-07-05T01:00:11Z</p>
      <details><summary>技术详情</summary><code>0 9 * * 0 · run weekly-review-2026-07-13-01</code></details>
    </article>
    <article>
      <h2>最近结果</h2>
      <p>AAPL 风险与新因子计划 · completed_degraded</p>
    </article>
  </section>
  <section aria-label="Hermes conversation">
    <textarea aria-label="和 Hermes 对话" disabled>真实 Hermes 写入能力尚未通过</textarea>
    <button type="button" disabled>发送</button>
  </section>
</main>
~~~

Add active/approval/result toggles inside each file using local JavaScript and semantic buttons. Do not load any CDN or remote asset.

- [ ] **Step 4: Verify four real viewports**

Serve the platform repository read-only:

~~~bash
cd /Users/sunyibo/programs/ai-quant-platform
python3 -m http.server 4173 --directory docs/design/hermes-workbench
~~~

Inspect every direction at 1440×900, 1280×800, 768×1024, and 390×844. At each width verify:

~~~text
document.documentElement.scrollWidth <= window.innerWidth
all interactive targets >= 44 CSS pixels
focus order follows visible reading order
no safety message is duplicated inside the content
normal automation never expands into four equal cards
~~~

- [ ] **Step 5: Independent review, user gate, and commit**

Have a separate frontend/UX reviewer record pass/fail for hierarchy, long Chinese text, long IDs, reduced motion, contrast, and viewport behavior in <code>docs/design/hermes-workbench/README.md</code>.

Then stop and obtain written user selection. After approval, add an <code>F0 decision</code> section containing: status <code>approved</code>; the exact selected filename stem that exists under <code>f0/</code>; approver <code>user</code>; the verbatim output of <code>date +%F</code>; and only the adjustments explicitly requested by the user. Never pre-fill a direction or invent adjustments.

Do not write “approved” before the user says so. After approval:

~~~bash
git add docs/design/hermes-workbench
git commit -m "docs(frontend): approve Hermes high-fidelity visual direction"
~~~

---

