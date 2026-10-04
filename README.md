# ActionClue Review

Review four-choice ActionClue QA with Oracle/full video, evidence, four human checks,
version-scoped reviews, dataset filters and JSONL export.

## Data contract

Storage: `collectedvideos`, container `video-container`.
Release: `ActionClue/actionclue/v1.0.0/{manifest,meta}.jsonl`.
Pointer: `ActionClue/actionclue/current.json`.

Every meta line is verified against the manifest SHA256. The supplied release has
1,200 rows. 415 rows contain inconsistent Oracle source/clip indices; originals
are preserved and the UI flags them. Preview conversion follows explicit source
indices after the specified ffmpeg sampling filter. Oracle playback is 3fps
(64 frames = about 21.33 seconds). Exact benchmark images can also depend on resize
and decode conventions; no claim of bit-identical benchmark frames is made.

This repository contains application code and the current pointer. Existing QA
files stay in the private Azure container. Future releases may be placed at
`datasets/actionclue/vX.Y.Z/{manifest,meta}.jsonl` **only if publishing their
contents in this public repository is intended**. Otherwise upload immutable
release files to Blob first, then commit only `current.json`.

## Local data-only preview

Python 3.12; no dependencies required in local mode.

```bash
mkdir -p local-data
# Copy supplied files as local-data/manifest.jsonl and local-data/meta.jsonl.
LOCAL_MODE=1 LOCAL_DATA_DIR=local-data python -m app.server
python -m unittest discover -s tests -v
python -m scripts.validate_dataset local-data --version 1.0.0
```

Open http://127.0.0.1:8000. Local reviews are in-memory and cleared on restart.
Azure media is deliberately unavailable in local data-only mode.

## Azure deployment prerequisites

- Linux App Service, Python 3.12, one or more instances.
- Startup: `gunicorn --pythonpath=/home/site/wwwroot/.python_packages/lib/site-packages --bind=0.0.0.0:8000 --workers=2 --timeout=120 app.server:application`.
- Bundle requirements into `.python_packages/lib/site-packages` using Python
  3.12. Set `SCM_DO_BUILD_DURING_DEPLOYMENT=false` and `ENABLE_ORYX_BUILD=false`;
  the deployment workflow builds dependencies before uploading the package.
- App Service authentication (Easy Auth): require authentication, Microsoft Entra
  tenant `789acfad-6fe0-4cdb-975a-04ab117882ae`. The app depends on Easy Auth
  stripping untrusted identity headers. Never expose it behind an untrusted
  proxy or disable Easy Auth.
- `ALLOWED_REVIEWERS=kato_shun1329@keio.jp` initially. Add approved reviewer emails
  explicitly. Configure the same allowlist in Easy Auth when feasible.
- Create private Blob container `actionclue-review-media` and Table
  `ActionClueReviews`; this existing StorageV2 account supports both services.
- Managed identity: Storage Blob Data Reader on source + preview containers;
  Storage Blob Delegator on storage account for user-delegation SAS; Storage Table
  Data Contributor for the review table. The app does not need storage account keys.
- Offline media-preparer identity: source reader and preview contributor.
- Dataset-publisher identity: source read and dataset write. Built-in container
  contributor can modify other blobs in `video-container`; use a custom role with
  an Azure ABAC condition limiting writes to `ActionClue/actionclue/`.
- App deployment identity: Website Contributor scoped to this app only.
- Use separate GitHub OIDC identities/environments: `azure-production` for the
  app and `azure-datasets` for dataset publishing. Restrict both environments
  to `main` before enabling CI. Exact subjects/scopes are in `infra/`.

GitHub variables: `AZURE_WEBAPP_NAME`, `AZURE_APP_CLIENT_ID`,
`AZURE_DATA_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`.
Deployment is skipped until variables are configured. Dataset publishing never
redeploys the app. The app rechecks current.json within 20 seconds; an open review
stays pinned to its loaded version and stale-version saves are rejected.

## Prepare browser-compatible videos

Install requirements and ffmpeg on a workstation/VM with Azure access. Run
`python -m scripts.prepare_media local-data --version 1.0.0 --limit 1` to verify one
QA. After checking it, use `--limit 0` for all. Source videos are downloaded once
per unique source/ETag into local cache; source files are never overwritten.
The outputs are immutable H.264 MP4 clips. Frame counts, frame rate and duration
are checked with ffprobe; output fps is explicitly fixed to the dataset rate.
Output metadata detects changes to previously processed source files.
Current source URLs are not content-addressed; retain/lock source blobs to ensure
old releases remain reproducible. Full conversion of 475 sources needs compute,
disk and storage budgeting and is separate from the web app.

## Publish a release

Upload both immutable JSONL files, then update the pointer in Git. The dataset
workflow validates all hashes/IDs/answers and checks every distinct source video
exists. Existing releases cannot be overwritten with different data. The current
pointer is updated last with ETag compare-and-swap to reject concurrent changes.
No pointer is published if validation or source checks fail.

## Review storage and limits

Table keys include version, QA and authenticated reviewer. Re-saving a QA replaces
that reviewer's latest judgment for the same version; earlier dataset versions
stay intact. It is not an edit-history log. Same-reviewer simultaneous edits use
last-write-wins. JSONL export includes the current reviewer's current-version
reviews. Media URLs expire after 30 minutes; reopen the player to refresh them.

## Verified so far

Local schema/security regression tests and supplied data validation pass. Azure
resources, Easy Auth, and app managed-identity roles are configured. Dataset
v1.0.1 is published, and initial preview frame counts are validated. Full-dataset
preview preparation, live review-save verification, and GitHub OIDC remain
pending. See [Azure connection status](docs/azure-connection.md) for details.

## キーボードでのレビュー

デスクトップでは動画とQAを左右に配置し、画面内でレビューします。データソースの選択はありません。

- `A`: Acceptを保存して次のQAへ。4つの品質基準をすべて満たす判定です。
- `R`: Rejectを保存して次のQAへ。保存に失敗した場合は現在のQAに留まります。
- `E`: 根拠区間を順にジャンプして再生。Oracle表示中は全体クリップに切り替え、source frame indicesから時刻を計算します。
- `Space`: 再生・停止。`←` / `→`: 前・次のQA。
- `C`: コメント入力。`Esc`: 入力を終了してショートカット操作へ戻る。入力中やキーの長押しでは判定しません。

最終QAの保存後はその場に留まります。スマートフォン幅では読みやすさのため縦に並べます。
