"""Offline regression checks for metadata gaps, Canvas files, and ASR review state."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import requests
import server

def response(data=None, links=None, chunks=()):
    result=MagicMock()
    result.__enter__.return_value=result
    result.json.return_value=data
    result.text=json.dumps(data)
    result.links=links or {}
    result.headers={}
    result.iter_content.return_value=iter(chunks)
    return result

def test_canvas_json_guard_and_plain_json():
    for prefix in ('', 'while(1);', '  \nwhile(1);'):
        value=response([{'id':1}])
        value.text=prefix+value.text
        assert server.canvas_json(value)==[{'id':1}]
    for text in ('<html>login</html>', 'while(1);not-json'):
        value=response()
        value.text=text
        try: server.canvas_json(value)
        except ValueError: pass
        else: raise AssertionError('invalid response accepted')

def test_guarded_canvas_lists_and_file_metadata():
    groups=response([{'name':'week7','items':[{'type':'File','content_id':123}]}])
    file=response({'filename':'DTC.pdf','size':42})
    groups.text='while(1);'+groups.text
    file.text='while(1);'+file.text
    with patch('server.get',side_effect=[groups,file]):
        rows,status=server.canvas_materials(None,49010)
        assert status=='checked' and rows[0]['content_id']=='canvas-file-123'

def test_read_only_annotations_are_exported():
    tools=server.mcp._tool_manager.list_tools()
    readonly={'auth_status','list_courses','list_materials','list_weekly_content','diagnose_materials','keep_alive_status_check','get_assignment'}
    for tool in tools:
        if tool.name in readonly:
            assert tool.annotations.readOnlyHint is True
        else:
            assert tool.annotations is None or tool.annotations.readOnlyHint is not True

def test_missing_id_is_unknown():
    groups=[{'title':'1����','module_items':[{'id':42,'title':'DTC_pdf'}]}]
    with patch('server.modules',return_value=groups),patch('server.session'):
        row=server.list_weekly_content(1)[0]['items'][0]
        assert row['available'] is None and row['availability_reason']=='missing_content_metadata'
        assert row['module_item_id']==42

def test_reported_size_is_not_verified():
    groups=[{'title':'1����','module_items':[{'content_data':{'item_content_data':{'content_id':'abc','file_name':'a.pdf','total_file_size':28809}}}]}]
    with patch('server.modules',return_value=groups):
        row=server.materials(None,1)[0]
        assert row['size_bytes'] is None and row['reported_size_bytes']==28809 and not row['size_verified']

def test_native_files_pagination_and_locked_files():
    groups=[{'name':'7����','id':9}]
    items=[{'type':'File','content_id':123},{'type':'ExternalTool','content_id':456},{'type':'File','content_id':789}]
    with patch('server.canvas_pages',side_effect=[groups,items]),patch('server.get',side_effect=[response({'filename':'DTC.pdf','size':42}),response({'filename':'locked.pdf','locked_for_user':True})]) as get:
        rows,status=server.canvas_materials(None,1)
        assert status=='checked' and len(rows)==1 and rows[0]['content_id']=='canvas-file-123'
        assert rows[0]['week']=='7����' and get.call_count==2

def test_canvas_lookup_failure_stays_visible():
    with patch('server.canvas_pages',side_effect=requests.ConnectionError('secret-url')):
        rows,status=server.canvas_materials(None,1)
        assert not rows and status=='incomplete_canvas_lookup' and 'secret' not in status

def test_canvas_pagination_rejects_external_urls_and_loops():
    url='https://canvas.ssu.ac.kr/api/v1/courses/1/modules'
    for next_url in ('https://evil.test/api/v1/files',url):
        with patch('server.get',return_value=response([],{'next':{'url':next_url}})) as get:
            try: server.canvas_pages(None,url)
            except RuntimeError: pass
            else: raise AssertionError('unsafe pagination accepted')
            assert get.call_count==1

def test_native_download_checks_bytes_and_origin():
    selected={'week':'7����','content_id':'canvas-file-123','filename':'DTC.pdf','source':'canvas','reported_size_bytes':28809}
    for url,allowed in [('https://canvas.ssu.ac.kr/files/123/download',True),('https://evil.test/a.pdf',False)]:
        with TemporaryDirectory() as directory,patch('server.STAGING',Path(directory)),patch('server.session'),patch('server.materials',return_value=[selected]),patch('server.get',side_effect=[response({'url':url}),response(chunks=[b'%PDF-test'])]):
            if allowed:
                result=server.stage_material(1,'canvas-file-123','7����')
                assert result['bytes']==9 and result['size_verified'] and result['reported_size_bytes']==28809
                server.delete_staged_material(result['staging_id'])
            else:
                try: server.stage_material(1,'canvas-file-123','7����')
                except RuntimeError: pass
                else: raise AssertionError('external download accepted')
            assert not list(Path(directory).iterdir())

def test_missing_commons_metadata_triggers_native_fallback():
    with patch('server.modules',return_value=[{'module_items':[{'title':'DTC_pdf'}]}]),patch('server.canvas_materials',return_value=([{'content_id':'canvas-file-123'}],'checked')):
        assert server.materials(None,1)==[{'content_id':'canvas-file-123'}]

def test_completed_cache_is_unreviewed_without_replacing_it():
    with TemporaryDirectory() as directory,patch('lecture.ROOT',Path(directory)):
        path=Path(directory)/'existing.json'
        raw=json.dumps({'status':'complete','segments':[{'text':'���'}]})
        path.write_text(raw,encoding='utf-8')
        result=server.lecture_transcript('existing',False)
        assert result['needs_review'] and result['review_status']=='unreviewed'
        assert path.read_text(encoding='utf-8')==raw

def test_asr_records_confidence_and_keeps_raw_text():
    import lecture
    xml=response()
    xml.text='<root><content_duration>10</content_duration><main_media>a.mp4</main_media><media_uri>https://ssu-toast.commonscdn.com/contents15/ssu1000001/[MEDIA_FILE]</media_uri><content_metadata><title>���̺�</title></content_metadata></root>'
    media=response(chunks=[b'video'])
    media.is_redirect=False
    model=MagicMock()
    model.transcribe.return_value=([SimpleNamespace(start=0,end=9,text=' ��� ',avg_logprob=-0.8,no_speech_prob=0.01)],None)
    with TemporaryDirectory() as directory,patch('lecture.ROOT',Path(directory)),patch('server.session'),patch('server.get',return_value=xml),patch('lecture.requests.get',return_value=media),patch('faster_whisper.WhisperModel',return_value=model):
        lecture.transcribe('sample')
        result=json.loads((Path(directory)/'sample.json').read_text(encoding='utf-8'))
        assert result['status']=='complete' and result['needs_review']
        assert result['segments'][0]['text']=='���' and result['segments'][0]['avg_logprob']==-0.8
        assert model.transcribe.call_args.kwargs['initial_prompt']=='���̺�'

if __name__=='__main__':
    checks=[value for name,value in list(globals().items()) if name.startswith('test_') and callable(value)]
    for check in checks: check()
    print(f'{len(checks)} material and transcription regression checks passed')

