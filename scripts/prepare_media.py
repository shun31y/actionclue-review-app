"""Offline CPU media preparation; run on a workstation/VM with ffmpeg.

Never change source videos. Oracle output contains the exact source sample indices.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
from azure.core import MatchConditions
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from app.dataset import load_dataset, blob_path, media_key
from app.media import prepare_preview


def main():
    p = argparse.ArgumentParser()
    p.add_argument('directory', type=Path)
    p.add_argument('--version', required=True)
    p.add_argument('--limit', type=int, default=1, help='QA limit; 0: all')
    p.add_argument('--offset', type=int, default=0, help='Skip this many manifest rows')
    p.add_argument('--cache', type=Path, default=Path('/tmp/actionclue-source-cache'))
    p.add_argument('--view', choices=['oracle', 'full', 'both'], default='both')
    p.add_argument('--discard-source-after-group', action='store_true',
                   help='Group by source, download once, then remove its local cached copy')
    p.add_argument('--keep-going', action='store_true',
                   help='Record failed views and continue; exit nonzero if any failed')
    p.add_argument('--report', type=Path, help='Append private per-view JSONL progress')
    a = p.parse_args()
    if a.limit < 0 or a.offset < 0:
        p.error('limit and offset must be nonnegative')
    rows = load_dataset((a.directory/'manifest.jsonl').read_bytes(),
                        (a.directory/'meta.jsonl').read_bytes(), a.version)
    selected = rows[a.offset:a.offset+a.limit if a.limit else None]
    groups = defaultdict(list)
    for row in selected:
        groups[row['manifest']['video_blob_url']].append(row)
    service = BlobServiceClient('https://collectedvideos.blob.core.windows.net',
                                credential=DefaultAzureCredential())
    output = service.get_container_client(os.getenv('MEDIA_CONTAINER', 'actionclue-review-media'))
    a.cache.mkdir(parents=True, exist_ok=True)
    counts = {'uploaded': 0, 'existing': 0, 'failed': 0}

    def record(row, view, status, **details):
        counts[status] += 1
        entry = {'version': a.version, 'qa_id': row['manifest']['id'],
                 'view': view, 'status': status, **details}
        print(json.dumps(entry), flush=True)
        if a.report:
            with a.report.open('a') as report:
                report.write(json.dumps(entry)+'\n')

    views = ('oracle', 'full') if a.view == 'both' else (a.view,)
    for url, source_rows in groups.items():
        local = None
        try:
            source = service.get_blob_client('video-container', blob_path(url))
            etag = source.get_blob_properties().etag
            source_hash = hashlib.sha256((url+etag).encode()).hexdigest()
            local = a.cache/source_hash
            for row in source_rows:
                for view in views:
                    outfile = a.cache/(media_key(row, view).rsplit('/', 1)[1])
                    try:
                        dest = output.get_blob_client(media_key(row, view))
                        if dest.exists():
                            if dest.get_blob_properties().metadata.get('source_hash') != source_hash:
                                raise ValueError('Source changed since preview creation; use a new dataset version')
                            record(row, view, 'existing')
                            continue
                        if not local.exists():
                            temp = local.with_suffix('.part')
                            with temp.open('wb') as f:
                                source.download_blob(etag=etag,
                                    match_condition=MatchConditions.IfNotModified).readinto(f)
                            temp.replace(local)
                        info = prepare_preview(local, outfile, row, view)
                        with outfile.open('rb') as f:
                            dest.upload_blob(f, overwrite=False,
                                metadata={'source_hash': source_hash, 'frames': str(info['frames']),
                                          'fps': info['fps'], 'duration_sec': str(info['duration_sec'])},
                                content_settings=ContentSettings(content_type='video/mp4',
                                    cache_control='private, max-age=86400'))
                        record(row, view, 'uploaded', **info)
                    except Exception as error:
                        record(row, view, 'failed', error=str(error))
                        if not a.keep_going:
                            raise
                    finally:
                        outfile.unlink(missing_ok=True)
        except Exception as error:
            if not a.keep_going:
                raise
            # Source-property failure occurs before individual views can be processed.
            if local is None:
                for row in source_rows:
                    for view in views:
                        record(row, view, 'failed', error=str(error))
        finally:
            if a.discard_source_after_group and local is not None:
                local.unlink(missing_ok=True)
                local.with_suffix('.part').unlink(missing_ok=True)
    print(json.dumps({'summary': counts}), flush=True)
    return 1 if counts['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
