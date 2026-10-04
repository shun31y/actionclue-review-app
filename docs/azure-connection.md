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
The first QA has prepared Oracle/full browser previews, with validated frame
counts of 64/2357. Preparing the remaining previews is still required before
the entire dataset can be reviewed.

## GitHub OIDC setup pending approval

`infra/github-oidc-plan.json` defines two secretless identities with separate
GitHub environments. Restrict both environments to deployments from `main`.

| Environment | Identity | Access |
| --- | --- | --- |
| `azure-production` | `actionclue-github-app-deploy` | Website Contributor on this Web App only |
| `azure-datasets` | `actionclue-github-dataset-publish` | Custom manifest publisher role on `video-container`, with a path condition |

The custom role and its ABAC condition are in `infra/`. It reads only
`ActionClue/` paths, creates/updates only `ActionClue/actionclue/` paths, and
does not grant blob deletion, movement, account keys, review table access, or
source-video writes. Both role definition and condition must be applied together.

After creating the identities, set repository/environment variables:
`AZURE_APP_CLIENT_ID`, `AZURE_DATA_CLIENT_ID`, `AZURE_TENANT_ID`,
`AZURE_SUBSCRIPTION_ID`, and `AZURE_WEBAPP_NAME`. No client secret is required.
The dataset workflow uses `azure-datasets` and refuses non-main dispatches.

The initial deployment and dataset publication were performed manually using
the owner's Azure Cloud Shell session. GitHub-to-Azure deployment has not yet
been verified; the OIDC grants and GitHub variables are still pending.

References:
- [App Service GitHub Actions deployment](https://learn.microsoft.com/en-us/azure/app-service/deploy-github-actions)
- [Blob path conditions](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-auth-abac-examples)
