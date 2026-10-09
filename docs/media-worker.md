# Offline media worker (deployment pending approval)

The production app and released QA files do not need to change. The remaining
previews can be prepared by an Ubuntu 24.04 CPU worker in Japan East, near the
source storage, instead of transferring 463.59 GiB outside Azure.

Proposed resource: `actionclue-media-worker` in `youtube-collection`,
`Standard_D4as_v5` (4 vCPU, 16 GiB), Standard SSD OS disk, no public IP and no
inbound access. This is separate from the existing GPU and collection VMs.

Use a system-assigned identity with Blob Data Reader on `video-container` and
a custom read/write/add-only Blob role on `actionclue-review-media`. It needs
no blob deletion, source write, account-key, review-table, app-deployment, or
subscription-wide access. These new role assignments require approval.

Install Ubuntu's FFmpeg 6.1 series, Python venv and the repository requirements.
The latest conda FFmpeg build caused a 0.325 ms MP4 duration deviation in the Oracle regression test;
FFmpeg 6.1.2 passed all ten Python tests in Cloud Shell. The worker fails early
on another FFmpeg generation rather than changing immutable preview recipes.

Run from a pinned, reviewed repository commit:

```bash
python -m scripts.run_media_worker --version 1.0.1 --max-hours 20
```

Run this as a systemd service with a 21-hour maximum runtime. Configure Azure
VM auto-shutdown to deallocate the worker within 23 hours of provisioning,
including if package installation fails. Confirm the shutdown schedule before
starting the service. Powering off Linux alone does not stop VM compute billing.
Verify deallocation through Azure before reporting that compute costs stopped.

The worker validates the private release, groups QA by source, deletes only
local temporary files, and resumes from uploaded immutable v3 previews. It
checkpoints logs and per-view results every 30 seconds in the private media
container under `worker-progress/`. No QA data or logs are published to GitHub.
Individual failures remain visible and make the worker exit nonzero. A worker
timeout returns 124. Re-run only within the approved budget/runtime; do not
assume that a 20-hour pass will finish all 1,200 QA.

Proposed execution ceiling: JPY 3,000 for incremental worker compute/disk costs,
at most 48 cumulative running hours across resumptions. This is a requested
budget, not a verified price quote. Confirm live regional pricing before
provisioning; lower the runtime if needed. Preview Blob storage costs continue
after the worker stops and are separate from this execution ceiling.

Live QA judgment saving remains a separate verification item. The media worker
never writes to the review table.
