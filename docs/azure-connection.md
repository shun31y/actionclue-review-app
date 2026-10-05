# Azure connection and initial release

The application is deployed to `actionclue-review-shun31y` in Japan East,
resource group `youtube-collection`. Microsoft sign-in is required and the
reviewer allowlist is `kato_shun1329@keio.jp`.

The app's managed identity has Blob Delegator at storage account scope,
Blob Data Reader on `video-container` and `actionclue-review-media`, and
Table Data Contributor on `ActionClueReviews` only.

## Dataset v1.0.1

The initial Blob release v1.0.0 remains unchanged. v1.0.1 corrects 65 missing
FineGym source paths, affecting 125 of 1,200 QA rows. Each correction uses the
unique existing file with the same video ID, with its actual `.mp4` or `.webm`
extension. The question, choices, gold answer, source/clip evidence frames,
and clip timing are unchanged; version fields and metadata hashes are updated.

All 65 replacement files contain the required clip end time according to their
container durations. This check does not prove that the unavailable MKV files
were pixel-identical. The existing source/clip evidence-index discrepancies
remain visible as warnings and have not been silently repaired.

Both manifests and metadata stay in private Blob storage under
`ActionClue/actionclue/v1.0.1/`. `audit.json` records the source-file mapping,
original SHA256 hashes, and duration checks. Git tracks the current pointer.
The initial preview recipe inherited the native source frame rate, making the
encoded durations too short despite matching frame counts. Recipe
`sample3-h264-v2` explicitly fixes output rate and verifies frame count, rate,
and duration before upload. Its distinct media keys retain the old previews
without serving them. A real FFmpeg regression test checks source-sample order
using a 25fps video and both 3fps preview views.

The first QA's corrected Oracle/full previews contain 64/2357 frames, with
durations 21.333333/785.666667 seconds. The second QA has 64/1408 frames
(21.333333/469.333333 seconds). Both full clips and evidence jumps were verified
in the live browser. Five validated v2 previews remain available (two full and three Oracle).
The third full clip's mismatch was diagnosed against the actual source, which
lasts 748.469388 seconds. EOF rounding produced 2245 source samples; setting
`eof_action=pass` produced 2246, with identical hashes for all 2245 shared samples.
Recipe `sample3-h264-v3` keeps that valid final sample and still rejects genuinely
out-of-source requests. New keys preserve immutable v2 outputs; playback prefers
v3 and falls back to validated v2, never to the incorrect native-rate v1.
The third v3 full/Oracle clips were validated and uploaded: 1628/64 frames,
542.666667/21.333333 seconds. Preparing the remaining previews is still required.
The 475 source blobs total 463.59 GiB; the largest is 4.34 GiB. Grouped processing
can discard each local source after its QA rows while retaining uploaded progress.

## GitHub OIDC connection

`infra/github-oidc-plan.json` defines two secretless identities with separate
GitHub environments. Both are configured with one allowed branch (`main`) and no allowed tags.
The observed GitHub OIDC subjects contain owner/repository IDs; the exact strings
in `infra/github-oidc-plan.json` match Azure's federated credentials.

| Environment | Identity | Access |
| --- | --- | --- |
| `azure-production` | `actionclue-github-app-deploy` | Website Contributor on this Web App only |
| `azure-datasets` | `actionclue-github-dataset-publish` | Custom manifest publisher role on `video-container`, with a path condition |

The custom role and its ABAC condition are in `infra/`. It reads only
`ActionClue/` paths, creates/updates only `ActionClue/actionclue/` paths, and
does not grant blob deletion, movement, account keys, review table access, or
source-video writes. Both role definition and condition must be applied together.

Both identities and their scoped role assignments are created and verified.
The following repository variables are configured:
`AZURE_APP_CLIENT_ID`, `AZURE_DATA_CLIENT_ID`, `AZURE_TENANT_ID`,
`AZURE_SUBSCRIPTION_ID`, and `AZURE_WEBAPP_NAME`. No client secret is required.
The dataset workflow uses `azure-datasets` and refuses non-main dispatches.

Blob dataset retrieval and isolated table write/read have been verified using
the application identity. The table connectivity marker uses partition
`__connectivity_checks__`, which is excluded from all dataset-review queries.
No QA judgment was created by the connectivity test.

The dataset workflow authenticated through OIDC and published v1.0.1 with all
1,200 records on 2026-10-05. It checks all 475 distinct source paths, keeps the
release files immutable, and updates the pointer without deploying the app.
[Verified dataset run](https://github.com/shun31y/actionclue-review-app/actions/runs/37310461986).
The app workflow also authenticated through OIDC, passed application validation,
and deployed successfully on 2026-10-05.
[Verified app run](https://github.com/shun31y/actionclue-review-app/actions/runs/37310380359).
After deployment, the live app loaded v1.0.1 and played the first full clip;
keyboard evidence jumps and the 1363 by 936 desktop layout were checked.

Runtime packaging includes requirements in `.python_packages/lib/site-packages`
for Python 3.12. App Service build flags are disabled to use that uploaded
dependency tree. Gunicorn's `--pythonpath` explicitly includes that directory.
The app workflow applies the build flags and startup command before deployment.

References:
- [App Service GitHub Actions deployment](https://learn.microsoft.com/en-us/azure/app-service/deploy-github-actions)
- [Blob path conditions](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-auth-abac-examples)
