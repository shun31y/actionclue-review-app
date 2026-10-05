import hashlib
import json
from urllib.parse import urlparse, unquote

ACCOUNT_HOST = 'collectedvideos.blob.core.windows.net'
CONTAINER = 'video-container'
PREFIX = 'ActionClue/'

def blob_path(url):
    p = urlparse(url)
    if p.scheme != 'https' or p.hostname != ACCOUNT_HOST or p.query or p.fragment:
        raise ValueError('Unexpected blob URL')
    path = unquote(p.path).lstrip('/')
    if not path.startswith(CONTAINER + '/' + PREFIX) or any(x in ('.', '..') for x in path.split('/')):
        raise ValueError('Blob outside ActionClue')
    return path[len(CONTAINER) + 1:]

def load_dataset(manifest_bytes, meta_bytes, version):
    lines = meta_bytes.splitlines()
    rows, ids = [], set()
    for raw in manifest_bytes.splitlines():
        m = json.loads(raw)
        if m['schema_version'] != 'actionclue.manifest.v1' or m['benchmark_version'] != version:
            raise ValueError('Manifest schema/version mismatch')
        n = m['meta_line_number']
        if type(n) is not int or not 1 <= n <= len(lines):
            raise ValueError('Invalid meta line number')
        if hashlib.sha256(lines[n-1]).hexdigest() != m['meta_sha256']:
            raise ValueError('Meta checksum mismatch')
        q = json.loads(lines[n-1])
        if q['id'] != m['id'] or q['benchmark_version'] != version or m['id'] in ids:
            raise ValueError('ID/version mismatch or duplicate ID')
        ids.add(m['id'])
        for field in ('video_blob_url', 'meta_blob_url'):
            blob_path(m[field])
        if m['sampling_fps_numerator'] <= 0 or m['sampling_fps_denominator'] <= 0:
            raise ValueError('Invalid sampling rate')
        if not 0 <= m['clip_start_frame'] < m['clip_end_frame_exclusive'] or m['clip_frame_count'] != m['clip_end_frame_exclusive']-m['clip_start_frame']:
            raise ValueError('Invalid clip interval')
        if len(q['choices']) != 4 or q['right_answer'] not in 'ABCD' or q['answer'] != q['choices']['ABCD'.index(q['right_answer'])]:
            raise ValueError('Invalid four-choice answer')
        source = q['oracle_frame_indices_in_source']
        clip = q['oracle_frame_indices_in_clip']
        if len(source) != q['oracle_frame_count'] or len(source) != len(clip):
            raise ValueError('Invalid oracle frame count')
        warnings = []
        if any(s != c + m['clip_start_frame'] for s,c in zip(source,clip)):
            warnings.append('Oracle source/clip frame indices disagree; preview uses source indices.')
        if any(s < m['clip_start_frame'] or s >= m['clip_end_frame_exclusive'] for s in source):
            warnings.append('Oracle source frame lies outside clip.')
        rows.append({'manifest':m, 'meta':q, 'warnings':warnings})
    if len(rows) != len(lines):
        raise ValueError('Manifest/meta row counts differ')
    return rows

def media_key(row, view, recipe='sample3-h264-v3'):
    # Depends on exact data and source path; conversion never changes released data.
    signature = json.dumps({'manifest':row['manifest'], 'view':view, 'recipe':recipe},sort_keys=True,separators=(',',':'))
    return 'browser-media/' + hashlib.sha256(signature.encode()).hexdigest() + '.mp4'

def media_candidates(row, view):
    # v2 outputs passed the same count/rate/duration checks; retain them while
    # v3 media is prepared. Never fall back to the incorrect native-rate v1.
    return (media_key(row, view), media_key(row, view, 'sample3-h264-v2'))
