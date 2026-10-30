import io
import json
from pathlib import Path
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
        assert sorted(bundle.namelist()) == ['tiktok/clips/clips/clip-001/captions.srt', 'tiktok/clips/clips/clip-001/video.mp4', 'titles.json']
        assert json.loads(bundle.read('titles.json'))['clips'][0]['title'] == '見出し'


def test_start_does_not_repeat_dispatch(client, tmp_path, monkeypatch):
    import app as module
    response = create(client)
    pid = response.location.rsplit('/', 1)[-1]
    root = tmp_path / 'clipforge'
    (root / 'tools').mkdir(parents=True)
    (root / 'tools' / 'produce_formats.py').write_text('')
    (root / '.venv' / 'bin').mkdir(parents=True)
    (root / '.venv' / 'bin' / 'python').write_text('')
    calls = []
    monkeypatch.setattr(module, 'shutil_which', lambda _: '/usr/bin/gh')
    monkeypatch.setattr(module.subprocess, 'Popen', lambda argv, **kw: calls.append((argv, kw)))
    csrf = token(client)
    client.post(f'/projects/{pid}/start', data={'csrf': csrf})
    client.post(f'/projects/{pid}/start', data={'csrf': csrf})
    assert len(calls) == 1
    assert '--mode' in calls[0][0] and 'both' in calls[0][0]
    assert not calls[0][1].get('shell', False)


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
