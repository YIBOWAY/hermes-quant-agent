---
name: hqa-research-task
description: Read-only inspection and projection recovery for the local Agent v0.2 research workflow authority.
version: 0.2.0
platforms: [macos]
metadata:
  hermes:
    tags: [hqa, research, workflow, audit]
---

# HQA Research Task authority

This is an explicitly read-only skill for the dark, local Agent v0.2 research
workflow authority. It can inspect canonical facts and rederive the local
projection from those facts. It cannot append workflow facts or advance a Task
or Attempt.

## Read-only commands

```bash
__HERMES_SCRIPTS_DIR__/hqa-research-task.sh show --task-ref <task-ref>
__HERMES_SCRIPTS_DIR__/hqa-research-task.sh events --task-ref <task-ref> --limit 100
__HERMES_SCRIPTS_DIR__/hqa-research-task.sh audit
__HERMES_SCRIPTS_DIR__/hqa-research-task.sh rebuild
```

`show` returns one exact Task snapshot. `events` returns its canonical event
history after an optional cursor. `audit` checks journal/projection consistency.
`rebuild` replaces only the derived projection from the canonical journal; it
does not append a workflow fact.

Use exact `task_ref`, `event_id`, refs, digests, and cursors returned by the
authority. Treat every non-zero exit as fail-closed.

All dark gates remain closed: `chat_write_ready` stays **OFF**; worker
claim/dispatch, browser writes, durable runs, public composer submission, paper
trading, and live trading stay disabled.
