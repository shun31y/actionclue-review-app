"""Bounded offline preparation with progress checkpoints in private media storage."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from app.dataset import load_dataset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='1.0.1')
    parser.add_argument('--workdir', type=Path, default=Path('/var/lib/actionclue-worker'))
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--max-hours', type=float, default=20)
    args = parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+', args.version):
        parser.error('Invalid version')
    if args.max_hours <= 0 or args.max_hours > 20 or min(args.limit, args.offset) < 0:
        parser.error('Use 0 < max-hours <= 20 and nonnegative row limits')
    version_line = subprocess.check_output(['ffmpeg', '-version'], text=True).splitlines()[0]
    if not re.search(r'ffmpeg version (?:n)?6\.1(?:\.|\s)', version_line):
        raise RuntimeError('This worker requires the verified FFmpeg 6.1 series')
    args.workdir.mkdir(parents=True, exist_ok=True)
    data = args.workdir / 'data'
    data.mkdir(exist_ok=True)
    service = BlobServiceClient('https://collectedvideos.blob.core.windows.net',
                                credential=DefaultAzureCredential())
    source = service.get_container_client('video-container')
    for name in ('manifest.jsonl', 'meta.jsonl'):
        payload = source.get_blob_client(f'ActionClue/actionclue/v{args.version}/{name}').download_blob().readall()
        (data / name).write_bytes(payload)
    rows = load_dataset((data / 'manifest.jsonl').read_bytes(),
                        (data / 'meta.jsonl').read_bytes(), args.version)
    print(f'Validated {len(rows)} rows; {version_line}', flush=True)
    output = service.get_container_client(os.getenv('MEDIA_CONTAINER', 'actionclue-review-media'))
    run = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    prefix = f'worker-progress/v{args.version}/{run}/'
    report, log = args.workdir / f'{run}.jsonl', args.workdir / f'{run}.log'
    command = [sys.executable, '-u', '-m', 'scripts.prepare_media', str(data),
               '--version', args.version, '--limit', str(args.limit), '--offset', str(args.offset),
               '--cache', str(args.workdir / 'cache'), '--discard-source-after-group',
               '--keep-going', '--report', str(report)]

    def checkpoint():
        for path in (report, log):
            if path.exists():
                try:
                    output.get_blob_client(prefix + path.suffix.lstrip('.')).upload_blob(
                        path.read_bytes(), overwrite=True,
                        content_settings=ContentSettings(content_type='text/plain',
                                                         cache_control='private, no-store'))
                except Exception as error:
                    print(f'Progress checkpoint failed: {type(error).__name__}', flush=True)

    started = time.monotonic()
    result = None
    with log.open('wb') as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            while result is None:
                if time.monotonic() - started >= args.max_hours * 3600:
                    print('Worker time limit reached; uploaded previews remain resumable', flush=True)
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    result = 124
                    break
                try:
                    result = process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pass
                checkpoint()
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            checkpoint()
    print(f'Worker exit={result}; private checkpoint prefix={prefix}', flush=True)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
