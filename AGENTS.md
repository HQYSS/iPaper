# iPaper Agent Rules

This file is the mandatory entry point for repository work. Read it before
editing code or reporting a fix as complete. Detailed guidance lives in
`docs/dev/开发规范.md`.

## Definition Of Done

For a user-requested fix in a running iPaper environment, completion means all
of the following:

1. Inspect the actual runtime and logs before choosing a code path.
2. Change the source and run the relevant tests.
3. Deploy or restart every environment needed by the changed execution path.
4. Reproduce or exercise the original workflow in the user's actual target.
5. Verify runtime evidence, then report the result.

Source changes and passing tests alone are not a completed fix. Do not say
"fixed", "deployed", or "verified" unless that exact layer was completed.
Diagnosis, review, and explanation-only requests do not authorize deployment or
other writes.

## Required Delivery Matrix

| Changed path or behavior | Required delivery |
| --- | --- |
| `backend/` | `./scripts/deploy.sh --backend`, then verify cloud runtime |
| Sync API, `sync_service.py`, or sync revisions | Deploy cloud first, fully restart the Electron runtime, exercise a real sync |
| `frontend/` | Build and deploy frontend; verify public `release.json` |
| `electron/main.js`, preload, or launch scripts | Fully quit and restart `iPaper.app`; opening it while alive only focuses the old process |
| Chrome extension | Reload the extension in the user's Chrome profile, then retest the target page |

Do not modify or restart Xray. Preserve unrelated dirty-worktree changes.

## Mandatory Commands

Use an explicit scope so unrelated dirty files do not expand the deployment:

```bash
./scripts/test.sh backend
./scripts/deploy.sh --backend
./scripts/verify-delivery.sh --sync
```

For frontend-only work:

```bash
./scripts/test.sh frontend
./scripts/deploy.sh --frontend
./scripts/verify-delivery.sh --frontend
```

`DELIVERY_COMPLETE=yes` is required before reporting an implementation complete.
If verification cannot be completed, report the exact incomplete layer and the
blocking evidence instead.

