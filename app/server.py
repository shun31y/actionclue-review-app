import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server
from app.dataset import load_dataset, media_key

ROOT = Path(__file__).parent
LOCAL = os.getenv('LOCAL_MODE') == '1'
if LOCAL and os.getenv('WEBSITE_SITE_NAME'):
    raise RuntimeError('LOCAL_MODE forbidden in Azure')
ACCOUNT = 'https://collectedvideos.blob.core.windows.net'
CONTAINER = 'video-container'
CURRENT = 'ActionClue/actionclue/current.json'
MEDIA_CONTAINER = os.getenv('MEDIA_CONTAINER', 'actionclue-review-media')
ALLOWED = {s.strip().lower() for s in os.getenv('ALLOWED_REVIEWERS','kato_shun1329@keio.jp').split(',') if s.strip()}
_lock = threading.Lock()
_cache = {'time':0}
_local_reviews = {}

def clients():
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient
    from azure.data.tables import TableServiceClient
    cred = DefaultAzureCredential()
    blobs = BlobServiceClient(ACCOUNT, credential=cred)
    tables = TableServiceClient('https://collectedvideos.table.core.windows.net',credential=cred)
    return blobs, tables.get_table_client(os.getenv('REVIEW_TABLE','ActionClueReviews'))

def snapshot():
    with _lock:
        if time.monotonic()-_cache['time'] < 20:
            return _cache['version'],_cache['rows']
        if LOCAL:
            directory = Path(os.environ['LOCAL_DATA_DIR'])
            version = os.getenv('LOCAL_VERSION','1.0.0')
            rows = load_dataset((directory/'manifest.jsonl').read_bytes(),(directory/'meta.jsonl').read_bytes(),version)
        else:
            blobs,_ = clients()
            pointer = json.loads(blobs.get_blob_client(CONTAINER,CURRENT).download_blob().readall())
            version = pointer['version']
            if not isinstance(version,str) or not __import__('re').fullmatch(r'\d+\.\d+\.\d+',version):
                raise ValueError('Invalid current version')
            prefix = f'ActionClue/actionclue/v{version}/'
            if pointer['manifest'] != prefix+'manifest.jsonl' or pointer['meta'] != prefix+'meta.jsonl':
                raise ValueError('Invalid current paths')
            manifest = blobs.get_blob_client(CONTAINER,pointer['manifest']).download_blob().readall()
            meta = blobs.get_blob_client(CONTAINER,pointer['meta']).download_blob().readall()
            rows = load_dataset(manifest,meta,version)
        _cache.update(time=time.monotonic(),version=version,rows=rows)
        return version,rows

def reviewer(environ):
    if LOCAL:
        return 'local-reviewer'
    # App Service Easy Auth MUST be configured to require authentication.
    if not environ.get('HTTP_X_MS_CLIENT_PRINCIPAL_ID'):
        return None
    email = environ.get('HTTP_X_MS_CLIENT_PRINCIPAL_NAME','').lower()
    return email if email in ALLOWED else None

def review_key(qa, who):
    return hashlib.sha256((qa+'\0'+who).encode()).hexdigest()

def all_reviews(version,who):
    if LOCAL:
        return [x for (v,_),x in _local_reviews.items() if v==version and x['reviewer_id']==who]
    _,table = clients()
    return list(table.query_entities("PartitionKey eq @version and reviewer_id eq @who",parameters={'version':version,'who':who}))

def respond(start,status,body,content_type='application/json'):
    data = body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False).encode()
    start(status,[('Content-Type',content_type),('Content-Length',str(len(data))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Referrer-Policy','no-referrer')])
    return [data]

def application(environ,start):
    path = environ.get('PATH_INFO','/')
    method = environ.get('REQUEST_METHOD','GET')
    if path == '/health':
        return respond(start,'200 OK',{'status':'ok'})
    who = reviewer(environ)
    if not who:
        return respond(start,'403 Forbidden',{'error':'Sign in with an allowed reviewer account.'})
    if path in ('/','/ui.js','/style.css') and method == 'GET':
        file = {'/':('index.html','text/html; charset=utf-8'),'/ui.js':('ui.js','application/javascript'),'/style.css':('style.css','text/css')}[path]
        return respond(start,'200 OK',(ROOT/'static'/file[0]).read_bytes(),file[1])
    try:
        version,rows = snapshot()
        args = parse_qs(environ.get('QUERY_STRING',''))
        if path == '/api/items' and method == 'GET':
            reviews = {r['qa_id']:r for r in all_reviews(version,who)}
            return respond(start,'200 OK',{'version':version,'reviewer':who,'items':[{'id':r['manifest']['id'],'source':r['manifest']['source_dataset'],'question':r['meta']['question'],'status':reviews.get(r['manifest']['id'],{}).get('status','pending'),'warnings':r['warnings']} for r in rows]})
        qa = args.get('id',[''])[0]
        row = next((r for r in rows if r['manifest']['id']==qa),None)
        if path == '/api/item' and method == 'GET' and row:
            reviews = [r for r in all_reviews(version,who) if r['qa_id']==qa]
            return respond(start,'200 OK',{'version':version,**row,'review':reviews[0] if reviews else None})
        if path == '/api/media' and method == 'GET' and row:
            if args.get('version',[version])[0] != version:
                return respond(start,'409 Conflict',{'error':'Dataset version changed. Reload before playing.'})
            view = args.get('view',['oracle'])[0]
            if view not in ('oracle','full'):
                return respond(start,'400 Bad Request',{'error':'Invalid view'})
            if LOCAL:
                return respond(start,'404 Not Found',{'error':'Media unavailable in local data-only mode'})
            blobs,_ = clients()
            key = media_key(row,view)
            if not blobs.get_blob_client(MEDIA_CONTAINER,key).exists():
                return respond(start,'404 Not Found',{'error':'Browser preview has not been prepared yet.'})
            from azure.storage.blob import generate_blob_sas, BlobSasPermissions
            now = datetime.now(timezone.utc)
            delegation = blobs.get_user_delegation_key(now-timedelta(minutes=1),now+timedelta(hours=1))
            sas = generate_blob_sas('collectedvideos',MEDIA_CONTAINER,key,user_delegation_key=delegation,permission=BlobSasPermissions(read=True),start=now-timedelta(minutes=1),expiry=now+timedelta(minutes=30),protocol='https')
            return respond(start,'200 OK',{'url':ACCOUNT+'/'+MEDIA_CONTAINER+'/'+key+'?'+sas})
        if path == '/api/review' and method == 'POST':
            # Custom header and same-origin check block browser CSRF; no CORS is enabled.
            if environ.get('HTTP_X_ACTIONCLUE_REVIEW') != '1':
                return respond(start,'403 Forbidden',{'error':'Missing request header'})
            origin = environ.get('HTTP_ORIGIN')
            expected = ('http' if LOCAL else 'https')+'://'+environ.get('HTTP_HOST','')
            if origin and origin != expected:
                return respond(start,'403 Forbidden',{'error':'Unexpected origin'})
            size = int(environ.get('CONTENT_LENGTH','0'))
            if not 0 < size <= 16384:
                return respond(start,'413 Payload Too Large',{'error':'Invalid body size'})
            body = json.loads(environ['wsgi.input'].read(size))
            if body.get('version') != version:
                return respond(start,'409 Conflict',{'error':'Dataset version changed. Reload before saving.'})
            row = next((r for r in rows if r['manifest']['id']==body.get('qa_id')),None)
            if not row or body.get('status') not in ('good','bad','uncertain') or len(body.get('comment',''))>4000:
                return respond(start,'400 Bad Request',{'error':'Invalid review'})
            checks = body.get('checks',{})
            names = ('unique_anchor','gold_supported','distractors_false','video_required')
            if set(checks)!=set(names) or any(type(checks[n]) is not bool for n in names) or (body['status']=='good' and not all(checks.values())):
                return respond(start,'400 Bad Request',{'error':'Good requires all four checks'})
            entity = {'PartitionKey':version,'RowKey':review_key(body['qa_id'],who),'dataset_version':version,'qa_id':body['qa_id'],'reviewer_id':who,'status':body['status'],'issue_type':str(body.get('issue_type',''))[:100],'comment':body.get('comment',''),'checks_json':json.dumps(checks),'updated_at':datetime.now(timezone.utc).isoformat()}
            if LOCAL:
                _local_reviews[(version,entity['RowKey'])]=entity
            else:
                from azure.data.tables import UpdateMode
                _,table=clients()
                table.upsert_entity(entity,mode=UpdateMode.REPLACE)
            return respond(start,'200 OK',{'saved':True})
        if path == '/api/export' and method == 'GET':
            return respond(start,'200 OK',all_reviews(version,who))
        return respond(start,'404 Not Found',{'error':'Not found'})
    except Exception:
        # Never return Azure credentials, SAS or internal error details to clients.
        import logging
        logging.exception('Request failed')
        return respond(start,'503 Service Unavailable',{'error':'Data service unavailable. Check server logs.'})

if __name__ == '__main__':
    if not LOCAL:
        raise SystemExit('Use gunicorn for Azure deployment')
    make_server('127.0.0.1',8000,application).serve_forever()
