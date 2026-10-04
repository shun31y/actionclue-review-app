"""Offline CPU media preparation; run on a workstation/VM with ffmpeg.

Never change source videos. Oracle output contains the exact source sample indices.
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from app.dataset import load_dataset, blob_path, media_key

p=argparse.ArgumentParser()
p.add_argument('directory',type=Path)
p.add_argument('--version',required=True)
p.add_argument('--limit',type=int,default=1,help='Default: one QA for end-to-end verification; 0: all')
p.add_argument('--cache',type=Path,default=Path('/tmp/actionclue-source-cache'))
p.add_argument('--view',choices=['oracle','full','both'],default='both')
a=p.parse_args()
rows=load_dataset((a.directory/'manifest.jsonl').read_bytes(),(a.directory/'meta.jsonl').read_bytes(),a.version)
service=BlobServiceClient('https://collectedvideos.blob.core.windows.net',credential=DefaultAzureCredential())
output=service.get_container_client(os.getenv('MEDIA_CONTAINER','actionclue-review-media'))
a.cache.mkdir(parents=True,exist_ok=True)
for row in rows[:a.limit or len(rows)]:
    m,q=row['manifest'],row['meta']
    source=service.get_blob_client('video-container',blob_path(m['video_blob_url']))
    etag=source.get_blob_properties().etag
    source_hash=hashlib.sha256((m['video_blob_url']+etag).encode()).hexdigest()
    local=a.cache/source_hash
    views=('oracle','full') if a.view=='both' else (a.view,)
    for view in views:
        key=media_key(row,view)
        dest=output.get_blob_client(key)
        if dest.exists():
            if dest.get_blob_properties().metadata.get('source_hash')!=source_hash:
                raise ValueError('Source changed since preview creation; use a new dataset version')
            continue
        if not local.exists():
            temp=local.with_suffix('.part')
            with temp.open('wb') as f:
                source.download_blob(etag=etag,match_condition=__import__('azure.core',fromlist=['MatchConditions']).MatchConditions.IfNotModified).readinto(f)
            temp.replace(local)
        fps=f"{m['sampling_fps_numerator']}/{m['sampling_fps_denominator']}"
        if view=='oracle':
            indices=q['oracle_frame_indices_in_source']
            if len(set(indices))!=len(indices) or indices!=sorted(indices):
                raise ValueError('Oracle source indices must be strictly increasing')
            selection='+'.join(f'eq(n\\,{i})' for i in indices)
            count=len(indices)
        else:
            selection=f"between(n\\,{m['clip_start_frame']}\\,{m['clip_end_frame_exclusive']-1})"
            count=m['clip_frame_count']
        outfile=a.cache/(key.rsplit('/',1)[1])
        filters=f'fps=fps={fps}:start_time=0:round=near,select={selection},setpts=N/({fps}*TB),scale=1280:960:force_original_aspect_ratio=decrease,pad=1280:960:(ow-iw)/2:(oh-ih)/2,setsar=1'
        subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-i',str(local),'-an','-vf',filters,'-frames:v',str(count),'-c:v','libx264','-preset','fast','-crf','23','-pix_fmt','yuv420p','-movflags','+faststart',str(outfile)],check=True)
        actual=int(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-count_frames','-show_entries','stream=nb_read_frames','-of','default=noprint_wrappers=1:nokey=1',str(outfile)]))
        if actual!=count:
            raise ValueError(f'Expected {count} frames, got {actual}')
        with outfile.open('rb') as f:
            dest.upload_blob(f,overwrite=False,metadata={'source_hash':source_hash},content_settings=ContentSettings(content_type='video/mp4',cache_control='private, max-age=86400'))
        print(f"Prepared {m['id']} {view}: {actual} frames")
