import io
import json
import re
import zipfile

import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app({'TESTING': True, 'DATA_DIR': str(tmp_path / 'data'), 'CLIPFORGE_DIR': str(tmp_path / 'clipforge')})
    return app.test_client()


def token(client):
    html = client.get('/').get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def create(client, **extra):
    data = {'csrf': token(client), 'creator': '配信者', 'title': '案件',
            'source_url': 'https://kick.com/example/videos/123', 'mode': 'both', 'clips': '5'}
    data.update(extra)
    return client.post('/projects', data=data)


def test_create_and_local_only(client):
    response = create(client, title='<script>')
    assert response.status_code == 302
    page = client.get(response.location).get_data(as_text=True)
    assert '&lt;script&gt;' in page and '<script>' not in page
    assert client.get('/', environ_base={'REMOTE_ADDR': '10.0.0.3'}).status_code == 403
    assert client.get('/', headers={'Host': 'outside.example'}).status_code == 403
    assert client.post('/projects', data={}).status_code == 403


def test_url_validation_including_youtube(client):
    assert create(client, source_url='https://www.youtube.com/watch?v=abc').status_code == 302
    response = create(client, source_url='https://example.com/?token=secret')
    assert response.location == '/'
    assert '確認してください' in client.get('/').get_data(as_text=True)


@pytest.mark.parametrize('controller_text', ['[]', '{invalid json'])
def test_invalid_optional_controller_status_keeps_import_source(client, tmp_path, controller_text):
    response = create(client)
    pid = response.location.rsplit('/', 1)[-1]
    base = tmp_path / 'data' / 'productions' / pid
    base.mkdir(parents=True, exist_ok=True)
    manifest = tmp_path / 'original' / 'manifest.json'
    (base / 'source-link.json').write_text(json.dumps({'manifest': str(manifest)}), encoding='utf-8')
    (base / 'controller-status.json').write_text(controller_text, encoding='utf-8')
    detail = client.get(response.location)
    assert detail.status_code == 200
    assert '取込元の保存記録' in detail.get_data(as_text=True)
    assert str(manifest) in detail.get_data(as_text=True)


def test_export_only_project_files_and_title(client, tmp_path):
    response = create(client)
    pid = response.location.rsplit('/', 1)[-1]
    clip = tmp_path / 'data' / 'productions' / pid / 'tiktok' / 'clips' / 'clips' / 'clip-001'
    clip.mkdir(parents=True)
    (clip / 'render.json').write_text(json.dumps({'selection': {'title': '見出し'}}), encoding='utf-8')
    (clip / 'video.mp4').write_bytes(b'video')
    (clip / 'captions.srt').write_text('subtitle', encoding='utf-8')
    (clip / 'private.txt').write_text('secret')
    response = client.get(f'/projects/{pid}/download')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as bundle:
        assert sorted(bundle.namelist()) == ['tiktok/clips/clips/clip-001/captions.srt', 'tiktok/clips/clips/clip-001/video.mp4', 'titles.json', '納品内容.txt']
        assert json.loads(bundle.read('titles.json'))['clips'][0]['title'] == '見出し'


def test_import_existing_clip_preserves_source(client, tmp_path):
    response = create(client)
    pid = response.location.rsplit('/', 1)[-1]
    original = tmp_path / 'original'
    original.mkdir()
    (original / 'video.mp4').write_bytes(b'original')
    (original / 'captions.srt').write_text('subtitle', encoding='utf-8')
    client.post(f'/projects/{pid}/import', data={'csrf': token(client), 'clip_dir': str(original),
                                                 'mode': 'long', 'clip_title': '完成動画'})
    assert (original / 'video.mp4').read_bytes() == b'original'
    with zipfile.ZipFile(io.BytesIO(client.get(f'/projects/{pid}/download').data)) as bundle:
        assert any(name.endswith('video.mp4') for name in bundle.namelist())
        assert json.loads(bundle.read('titles.json'))['clips'][0]['title'] == '完成動画'


def test_clip_preview_subtitle_and_title_edit(client, tmp_path):
    response = create(client)
    pid = response.location.rsplit('/', 1)[-1]
    clip = tmp_path / 'data' / 'productions' / pid / 'long' / 'clips' / 'clips' / 'clip-001'
    clip.mkdir(parents=True)
    (clip / 'video.mp4').write_bytes(b'video content')
    (clip / 'captions.srt').write_text('字幕', encoding='utf-8')
    (clip / 'render.json').write_text(json.dumps({'selection': {'title': '元のタイトル'}}), encoding='utf-8')
    relative = 'long/clips/clips/clip-001'
    page = client.get(response.location).get_data(as_text=True)
    assert '元のタイトル' in page and 'captions.srt を保存' in page
    video = client.get(f'/projects/{pid}/files/{relative}/video.mp4', headers={'Range': 'bytes=0-4'})
    assert video.status_code == 206 and video.data == b'video'
    assert client.get(f'/projects/{pid}/files/{relative}/captions.srt').status_code == 200
    assert client.get(f'/projects/{pid}/files/{relative}/render.json').status_code == 404
    client.post(f'/projects/{pid}/clip-title', data={'csrf': token(client), 'relative': relative, 'title': '納品タイトル'})
    assert '納品タイトル' in client.get(response.location).get_data(as_text=True)
    with zipfile.ZipFile(io.BytesIO(client.get(f'/projects/{pid}/download').data)) as bundle:
        assert json.loads(bundle.read('titles.json'))['clips'][0]['title'] == '納品タイトル'
    assert json.loads((clip / 'render.json').read_text())['selection']['title'] == '元のタイトル'
    client.post(f'/projects/{pid}/clip-title', data={'csrf': token(client), 'relative': '../other', 'title': '不正'})
    assert client.get(f'/projects/{pid}/files/../other/video.mp4').status_code == 404


def test_project_management_search_and_expenses(client):
    response = create(client)
    pid = response.location.rsplit('/', 1)[-1]
    csrf = token(client)
    client.post(f'/projects/{pid}/edit', data={'csrf': csrf, 'creator': 'クリエイターA', 'title': '編集後', 'due_date': '2027-01-02', 'note': '依頼メモ'})
    assert '編集後' in client.get('/?q=クリエイターA').get_data(as_text=True)
    assert '編集後' not in client.get('/?q=別の人').get_data(as_text=True)
    for description, amount, currency in [('API', '1.25', 'USD'), ('制作', '2.50', 'USD'), ('素材', '100', 'JPY')]:
        client.post(f'/projects/{pid}/expenses', data={'csrf': csrf, 'description': description, 'amount': amount, 'currency': currency})
    client.post(f'/projects/{pid}/expenses', data={'csrf': csrf, 'description': '不正', 'amount': '1e-999999999', 'currency': 'USD'})
    page = client.get(response.location).get_data(as_text=True)
    assert 'USD 3.75' in page and 'JPY 100' in page and '依頼メモ' in page
    assert '1e-999999999' not in page
    client.post(f'/projects/{pid}/expenses/1/delete', data={'csrf': csrf})
    assert 'USD 2.50' in client.get(response.location).get_data(as_text=True)


def test_selected_delivery_and_subtitle_edits(client, tmp_path):
    response = create(client)
    pid = response.location.rsplit('/', 1)[-1]
    base = tmp_path / 'data' / 'productions' / pid / 'long' / 'clips' / 'clips'
    for clip_id in ('clip-001', 'clip-002'):
        clip = base / clip_id
        clip.mkdir(parents=True)
        (clip / 'video.mp4').write_bytes(clip_id.encode())
        (clip / 'captions.srt').write_text('元の字幕', encoding='utf-8')
    relative = 'long/clips/clips/clip-001'
    csrf = token(client)
    client.post(f'/projects/{pid}/subtitle', data={'csrf': csrf, 'relative': relative, 'content': '編集した字幕'})
    client.post(f'/projects/{pid}/clip-note', data={'csrf': csrf, 'relative': relative, 'status': 'ready', 'note': '納品待ち'})
    assert '納品待ち' in client.get(response.location).get_data(as_text=True)
    edited = client.get(f'/projects/{pid}/files/{relative}/captions-edited.srt')
    assert edited.data.decode() == '編集した字幕'
    response = client.post(f'/projects/{pid}/download', data={'csrf': csrf, 'clip': relative})
    with zipfile.ZipFile(io.BytesIO(response.data)) as bundle:
        assert all('clip-002' not in n for n in bundle.namelist())
        assert bundle.read(relative + '/captions.srt').decode() == '元の字幕'
        assert bundle.read(relative + '/captions-edited.srt').decode() == '編集した字幕'
        assert bundle.getinfo(relative + '/video.mp4').compress_type == zipfile.ZIP_STORED
    assert (base / 'clip-001' / 'captions.srt').read_text() == '元の字幕'


