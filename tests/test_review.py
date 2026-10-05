import copy
import hashlib
import importlib
import io
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest
from app.dataset import blob_path, load_dataset, media_candidates

def data():
    q={'id':'example:1','benchmark_version':'1.0.0','question':'What follows?','choices':['A1','B1','C1','D1'],'right_answer':'A','answer':'A1','oracle_frame_count':2,'oracle_frame_indices_in_source':[4,5],'oracle_frame_indices_in_clip':[1,2]}
    raw=json.dumps(q).encode()
    m={'schema_version':'actionclue.manifest.v1','benchmark_version':'1.0.0','id':q['id'],'source_dataset':'Synthetic','video_blob_url':'https://collectedvideos.blob.core.windows.net/video-container/ActionClue/example.mp4','meta_blob_url':'https://collectedvideos.blob.core.windows.net/video-container/ActionClue/actionclue/v1.0.0/meta.jsonl','meta_line_number':1,'meta_sha256':hashlib.sha256(raw).hexdigest(),'sampling_fps_numerator':3,'sampling_fps_denominator':1,'clip_start_frame':3,'clip_end_frame_exclusive':8,'clip_frame_count':5}
    return json.dumps(m).encode(),raw

class DatasetTests(unittest.TestCase):
    def test_corrupt_meta_rejected(self):
        m,q=data()
        with self.assertRaises(ValueError):load_dataset(m,q+b' ','1.0.0')
    def test_source_url_boundary(self):
        for url in ['http://collectedvideos.blob.core.windows.net/video-container/ActionClue/x','https://evil.test/video-container/ActionClue/x','https://collectedvideos.blob.core.windows.net/video-container/ActionClue/../private','https://collectedvideos.blob.core.windows.net/video-container/ELMA/x']:
            with self.assertRaises(ValueError):blob_path(url)
    def test_frame_warning_preserves_source(self):
        m,q=data();j=json.loads(m);j['clip_start_frame']=2;j['clip_frame_count']=6
        r=load_dataset(json.dumps(j).encode(),q,'1.0.0')
        self.assertEqual(r[0]['meta']['oracle_frame_indices_in_source'],[4,5]);self.assertTrue(r[0]['warnings'])

class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();p=Path(cls.temp.name);m,q=data();(p/'manifest.jsonl').write_bytes(m);(p/'meta.jsonl').write_bytes(q)
        os.environ.update(LOCAL_MODE='1',LOCAL_DATA_DIR=str(p));cls.server=importlib.import_module('app.server')
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def request(self,body,header='1',origin='http://localhost'):
        raw=json.dumps(body).encode();e={'PATH_INFO':'/api/review','REQUEST_METHOD':'POST','wsgi.input':io.BytesIO(raw),'CONTENT_LENGTH':str(len(raw)),'HTTP_X_ACTIONCLUE_REVIEW':header,'HTTP_ORIGIN':origin,'HTTP_HOST':'localhost'}
        status=[];result=self.server.application(e,lambda s,h:status.append(s));return status[0],json.loads(b''.join(result))
    def body(self):return {'version':'1.0.0','qa_id':'example:1','status':'good','checks':{k:True for k in ('unique_anchor','gold_supported','distractors_false','video_required')},'comment':'Checked'}
    def test_stale_version_not_saved(self):
        b=self.body();b['version']='0.9.0';self.assertEqual(self.request(b)[0],'409 Conflict')
    def test_csrf_rejected(self):
        self.assertEqual(self.request(self.body(),origin='https://evil.test')[0],'403 Forbidden');self.assertEqual(self.request(self.body(),header='')[0],'403 Forbidden')
    def test_good_requires_checks(self):
        b=self.body();b['checks']['unique_anchor']=False;self.assertEqual(self.request(b)[0],'400 Bad Request')
    def test_review_identity_and_version(self):
        self.assertEqual(self.request(self.body())[0],'200 OK');r=self.server.all_reviews('1.0.0','local-reviewer');self.assertEqual(r[0]['reviewer_id'],'local-reviewer');self.assertEqual(self.server.all_reviews('2.0.0','local-reviewer'),[])

    def test_media_prefers_v3_and_keeps_verified_v2_available(self):
        m,q=data();row=load_dataset(m,q,'1.0.0')[0]
        v3,v2=media_candidates(row,'full')
        self.assertNotEqual(v3,v2)
        storage=SimpleNamespace(generate_blob_sas=lambda *a,**kw:'test-token',
                                BlobSasPermissions=lambda **kw:kw)
        for available,expected in [({v3,v2},v3),({v2},v2),(set(),None)]:
            with self.subTest(available=available):
                blobs=SimpleNamespace(get_blob_client=lambda container,key:
                    SimpleNamespace(exists=lambda:key in available),
                    get_user_delegation_key=lambda *a:object())
                e={'PATH_INFO':'/api/media','REQUEST_METHOD':'GET',
                   'QUERY_STRING':'id=example%3A1&version=1.0.0&view=full'}
                status=[]
                with patch.object(self.server,'LOCAL',False), \
                     patch.object(self.server,'reviewer',return_value='test-reviewer'), \
                     patch.object(self.server,'snapshot',return_value=('1.0.0',[row])), \
                     patch.object(self.server,'clients',return_value=(blobs,None)), \
                     patch.dict(sys.modules,{'azure.storage.blob':storage}):
                    result=self.server.application(e,lambda s,h:status.append(s))
                body=json.loads(b''.join(result))
                if expected:
                    self.assertEqual(status[0],'200 OK')
                    self.assertIn('/'+expected+'?',body['url'])
                else:
                    self.assertEqual(status[0],'404 Not Found')

if __name__=='__main__':unittest.main()
