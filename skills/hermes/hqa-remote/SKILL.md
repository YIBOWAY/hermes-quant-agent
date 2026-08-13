---
name: hqa-remote
description: "Personal quant assistant remote. Use first for 派研究 / 挂仓 / 查仓. Dispatch never hangs. Hang only an existing verified candidate."
version: 1.0.0
platforms: [macos]
metadata:
  hermes:
    tags: [quant, remote, hqa]
    related_skills: [hqa-quant]
---

# Assistant remote

Chat is a remote, not a research factory. Before any write, read status.

Backend default for isolation preview is `http://127.0.0.1:8876`. Live `:8765` is a different book — do not mix them.

```bash
__HQA_REPO_DIR__/.venv/bin/python -m hqa.remote_cli --backend http://127.0.0.1:8876 status
```

## Two write commands. Never fuse them.

1. **派研究** — enqueue an owner ask. Stops at a research request. Does **not** create a hung sleeve. Does **not** invent a verified candidate.

```bash
__HQA_REPO_DIR__/.venv/bin/python -m hqa.remote_cli --backend http://127.0.0.1:8876 dispatch-research --objective "<verbatim owner ask>"
```

Add `--hang-if-pass` only when the owner wrote 过了就挂 on **this** ask. That flag is stored on the request; it is not itself a hang.

2. **挂上** — hang one existing **verified** candidate onto the daily paper book.

```bash
__HQA_REPO_DIR__/.venv/bin/python -m hqa.remote_cli --backend http://127.0.0.1:8876 hang --candidate-id <exact-id-from-status>
```

If status has no `verified` candidate, say so and stop. Do not hang a request. Do not hang because a dual-engine job passed unless the owner said 挂上 or that ask had 过了就挂.

## Red lines

- 派研究 ≠ 挂上.
- Dual-engine pass = 已验证候选 only.
- No live path. No invented universe. No seed mark-to-market as strategy P&L.
- Do not use the old D-33 enqueue / D-34 worker as a fused "research then hang" shortcut.
