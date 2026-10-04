"""Validate/upload immutable release, then atomically replace current pointer.

When version files are absent in Git, validate the existing release in Blob.
"""
import hashlib
import json
from pathlib import Path
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core import MatchConditions
from azure.core.exceptions import ResourceNotFoundError, ResourceExistsError
from app.dataset import load_dataset, blob_path

container=BlobServiceClient('https://collectedvideos.blob.core.windows.net',credential=DefaultAzureCredential()).get_container_client('video-container')
pointer_bytes=Path('datasets/actionclue/current.json').read_bytes()
pointer=json.loads(pointer_bytes)
version=pointer['version']
import re
if not re.fullmatch(r'\d+\.\d+\.\d+',version):
    raise ValueError('Invalid version')
prefix=f'ActionClue/actionclue/v{version}/'
if pointer['manifest']!=prefix+'manifest.jsonl' or pointer['meta']!=prefix+'meta.jsonl':
    raise ValueError('Invalid release paths')
current=container.get_blob_client('ActionClue/actionclue/current.json')
try:
    prior=current.get_blob_properties().etag
except ResourceNotFoundError:
    prior=None
contents={}
for filename in ('manifest.jsonl','meta.jsonl'):
    local=Path(f'datasets/actionclue/v{version}')/filename
    contents[filename]=local.read_bytes() if local.exists() else container.get_blob_client(prefix+filename).download_blob().readall()
rows=load_dataset(contents['manifest.jsonl'],contents['meta.jsonl'],version)
for path in sorted({blob_path(r['manifest']['video_blob_url']) for r in rows}):
    if not container.get_blob_client(path).exists():
        raise ValueError(f'Missing source video: {path}')
for filename,data in contents.items():
    blob=container.get_blob_client(prefix+filename)
    try:
        blob.upload_blob(data,overwrite=False,content_settings=ContentSettings(content_type='application/x-ndjson'))
    except ResourceExistsError:
        if hashlib.sha256(blob.download_blob().readall()).digest()!=hashlib.sha256(data).digest():
            raise ValueError('Existing release differs; create a new version')
if prior:
    current.upload_blob(pointer_bytes,overwrite=True,etag=prior,match_condition=MatchConditions.IfNotModified,content_settings=ContentSettings(content_type='application/json',cache_control='no-cache'))
else:
    current.upload_blob(pointer_bytes,overwrite=False,content_settings=ContentSettings(content_type='application/json',cache_control='no-cache'))
print(f'Published {version}: {len(rows)} records')
