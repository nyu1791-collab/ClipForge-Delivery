"""Copy local deliverables in batches, keeping original files and repeated imports."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from filelock import FileLock

MODES={'long','tiktok','tiktok-capcut'}


def copy_clip(source,base,mode,title=''):
    if not str(source).strip():
        raise ValueError('動画フォルダを指定してください')
    source=Path(source).expanduser()
    if source.is_symlink():
        raise ValueError('動画フォルダへのリンクは取り込めません')
    source=source.resolve()
    if mode not in MODES:
        raise ValueError('対応する動画形式を指定してください')
    files={}
    for target,names in {'video.mp4':['video.mp4'],'captions.srt':['captions.srt','subtitles.srt'],
                         'captions.ass':['captions.ass','subtitles.ass'],'render.json':['render.json']}.items():
        found=next((source/name for name in names if (source/name).is_file()),None)
        if found:
            if found.is_symlink():
                raise ValueError('ファイルへのリンクは取り込めません')
            files[target]=found
    if 'video.mp4' not in files:
        raise FileNotFoundError(f'video.mp4 がありません: {source}')
    video_stat=files['video.mp4'].stat()
    signature=[str(source),video_stat.st_size,video_stat.st_mtime_ns]
    key=hashlib.sha256(json.dumps(signature).encode()).hexdigest()[:20]
    root=Path(base)/mode/'clips'/'clips'
    root.mkdir(parents=True,exist_ok=True)
    target=root/('clip-import-'+key)
    if (target/'video.mp4').is_file():
        updated=False
        for name,path in files.items():
            if name=='video.mp4':
                continue
            destination=target/name
            incoming=path.stat()
            existing=destination.stat() if destination.is_file() else None
            if existing is None or (incoming.st_size,incoming.st_mtime_ns)!=(existing.st_size,existing.st_mtime_ns):
                temporary=destination.with_suffix(destination.suffix+'.tmp')
                shutil.copy2(path,temporary)
                temporary.replace(destination)
                updated=True
        return {'status':'updated' if updated else 'reused','directory':str(target),'mode':mode,'title':title}
    with tempfile.TemporaryDirectory(dir=root,prefix='.import-') as temp:
        staging=Path(temp)/'clip'
        staging.mkdir()
        for name,path in files.items():
            shutil.copy2(path,staging/name)
        if 'render.json' not in files:
            (staging/'render.json').write_text(json.dumps({'selection':{'title':title or source.name}},ensure_ascii=False),encoding='utf-8')
        staging.rename(target)
    return {'status':'imported','directory':str(target),'mode':mode,'title':title}


def import_many(entries,base):
    base=Path(base)
    base.mkdir(parents=True,exist_ok=True)
    results=[]
    with FileLock(str(base/'import.lock'),timeout=0):
        for item in entries:
            try:
                if 'error' in item:
                    raise ValueError(item['error'])
                results.append(copy_clip(item['directory'],base,item['mode'],item.get('title','')))
            except (OSError,ValueError,KeyError) as error:
                results.append({'status':'failed','message':str(error)})
    return results


def read_manifest(path,default_mode):
    path=Path(path).expanduser().resolve()
    data=json.loads(path.read_text(encoding='utf-8'))
    entries=[]
    items=data['clips'] if 'clips' in data else data['rendered']
    for entry in items:
        try:
            item={'directory':entry} if isinstance(entry,str) else dict(entry)
            source=Path(item['directory']).expanduser()
            item['directory']=str(source if source.is_absolute() else path.parent/source)
            item['mode']=item.get('mode') or default_mode
            entries.append(item)
        except (KeyError,TypeError,ValueError) as error:
            entries.append({'error':'素材の指定を読み込めません: '+str(error)})
    return entries
