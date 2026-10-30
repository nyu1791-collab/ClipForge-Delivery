"""Local, single-user delivery workspace for ClipForge productions."""
import json
import io
import os
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from urllib.parse import urlsplit, parse_qsl

from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = Path.home() / '.clipforge-delivery'
MODES = {'long': '横動画', 'tiktok': '縦動画', 'both': '横動画＋縦動画', 'tiktok-capcut': 'CapCut向け縦動画'}
DELIVERY = {'pending': '未納品', 'ready': '納品準備完了', 'delivered': '納品済み'}


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(DATA_DIR=os.environ.get('CLIPFORGE_DELIVERY_DATA', str(DEFAULT_DATA)),
                      CLIPFORGE_DIR=os.environ.get('CLIPFORGE_DIR', str(ROOT.parent / 'ClipForge')),
                      CLIPFORGE_PYTHON=os.environ.get('CLIPFORGE_PYTHON', ''),
                      MAX_CONTENT_LENGTH=1024 * 1024)
    if test_config:
        app.config.update(test_config)
    data = Path(app.config['DATA_DIR']).expanduser().resolve()
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    (data / 'productions').mkdir(exist_ok=True, mode=0o700)
    secret = data / 'session.key'
    if not secret.exists():
        try:
            fd = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    app.secret_key = secret.read_text(encoding='ascii')
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
    database = data / 'delivery.sqlite3'

    @app.template_filter('localtime')
    def localtime(value):
        return datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M')

    def connect():
        db = sqlite3.connect(database, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    with connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, creator TEXT NOT NULL, title TEXT NOT NULL,
          source_url TEXT NOT NULL, mode TEXT NOT NULL, clips INTEGER NOT NULL,
          due_date TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'draft', delivery TEXT NOT NULL DEFAULT 'pending',
          cost_amount TEXT NOT NULL DEFAULT '', cost_currency TEXT NOT NULL DEFAULT '',
          delivery_url TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
          updated_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, project_id TEXT NOT NULL,
          event TEXT NOT NULL, created_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS clip_titles (project_id TEXT NOT NULL,
          relative TEXT NOT NULL, title TEXT NOT NULL,
          PRIMARY KEY (project_id, relative));
          CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY, project_id TEXT NOT NULL,
          description TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL, created_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS clip_notes (project_id TEXT NOT NULL, relative TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', note TEXT NOT NULL DEFAULT '',
          PRIMARY KEY (project_id, relative));
          CREATE TABLE IF NOT EXISTS subtitle_edits (project_id TEXT NOT NULL, relative TEXT NOT NULL,
          content TEXT NOT NULL,
          PRIMARY KEY (project_id, relative));''')

    def project(pid):
        if not re_id(pid):
            abort(404)
        with connect() as db:
            row = db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
        if not row:
            abort(404)
        return dict(row)

    def event(db, pid, value):
        db.execute('INSERT INTO history(project_id,event,created_at) VALUES (?,?,?)', (pid, value, time.time()))

    def project_assets(pid):
        found = assets(data / 'productions' / pid)
        with connect() as db:
            titles = dict(db.execute('SELECT relative,title FROM clip_titles WHERE project_id=?', (pid,)).fetchall())
            notes = {r['relative']: dict(r) for r in db.execute('SELECT relative,status,note FROM clip_notes WHERE project_id=?', (pid,))}
        for item in found:
            item['title'] = titles.get(item['relative'], item['title'])
            item.update(notes.get(item['relative'], {'status': 'pending', 'note': ''}))
        return found

    @app.before_request
    def protect():
        if request.remote_addr not in ('127.0.0.1', '::1'):
            abort(403)
        try:
            host = urlsplit('http://' + request.host).hostname
        except ValueError:
            abort(403)
        if host not in ('127.0.0.1', 'localhost', '::1'):
            abort(403)
        if request.method == 'POST' and (not session.get('csrf') or not secrets.compare_digest(session['csrf'], request.form.get('csrf', ''))):
            abort(403)

    @app.context_processor
    def csrf_context():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        return {'csrf': session['csrf'], 'modes': MODES, 'deliveries': DELIVERY}

    @app.get('/')
    def index():
        query = request.args.get('q', '').strip()[:200]
        delivery = request.args.get('delivery', '')
        with connect() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM projects ORDER BY updated_at DESC')]
        if query:
            rows = [r for r in rows if query.casefold() in (r['creator'] + ' ' + r['title']).casefold()]
        if delivery in DELIVERY:
            rows = [r for r in rows if r['delivery'] == delivery]
        return render_template('index.html', projects=rows, query=query, selected_delivery=delivery)

    @app.post('/projects')
    def create():
        creator, title, source = (request.form.get(k, '').strip() for k in ('creator', 'title', 'source_url'))
        mode = request.form.get('mode', 'tiktok')
        try:
            count = int(request.form.get('clips', '5'))
        except ValueError:
            count = 0
        try:
            parsed = urlsplit(source)
            host = (parsed.hostname or '').lower()
            query = parse_qsl(parsed.query, keep_blank_values=True)
            youtube_query = host in ('youtube.com', 'www.youtube.com', 'm.youtube.com') and len(query) == 1 and query[0][0] == 'v' and bool(query[0][1])
            valid_url = parsed.scheme == 'https' and bool(host) and not parsed.username and not parsed.password and (not parsed.query or youtube_query) and not parsed.fragment
        except ValueError:
            valid_url = False
        if not creator or not title or len(creator) > 100 or len(title) > 200 or len(source) > 2000 or not valid_url or mode not in MODES or not 1 <= count <= 10:
            flash('配信者・案件名・公開HTTPS URL・本数（1〜10）を確認してください。')
            return redirect(url_for('index'))
        pid, now = uuid.uuid4().hex, time.time()
        with connect() as db:
            db.execute('INSERT INTO projects(id,creator,title,source_url,mode,clips,due_date,note,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (pid, creator, title, source, mode, count, request.form.get('due_date', '')[:10], request.form.get('note', '')[:2000], now, now))
            event(db, pid, '案件を作成')
        return redirect(url_for('detail', pid=pid))

    @app.get('/projects/<pid>')
    def detail(pid):
        row = project(pid)
        base = data / 'productions' / pid
        states = []
        for name in ('long', 'tiktok', 'tiktok-capcut'):
            state = base / name / 'production-state.json'
            if state.is_file() and not state.is_symlink():
                try:
                    obj = json.loads(state.read_text(encoding='utf-8'))
                    stages = obj.get('stages') or []
                    run_id = obj.get('render_run_id') or next((s.get('run_id') for s in stages if isinstance(s, dict) and s.get('run_id')), None)
                    repo = obj.get('repository', '')
                    run_url = f'https://github.com/{repo}/actions/runs/{run_id}' if repo in ('nyu1791-collab/ClipForge', 'nyu1791-collab/ai-model-workers') and str(run_id).isdigit() else None
                    states.append({'name': name, 'status': obj.get('status', '不明'), 'run_id': run_id, 'run_url': run_url,
                                   'stages': [s for s in stages if isinstance(s, dict)], 'elapsed': obj.get('elapsed_sec')})
                except (ValueError, OSError, TypeError, AttributeError):
                    states.append({'name': name, 'status': '記録を読み取れません'})
        with connect() as db:
            history = [dict(r) for r in db.execute('SELECT event,created_at FROM history WHERE project_id=? ORDER BY id DESC LIMIT 20', (pid,))]
            expenses = [dict(r) for r in db.execute('SELECT * FROM expenses WHERE project_id=? ORDER BY id DESC', (pid,))]
        controller_status = None
        try:
            status_path = base / 'controller-status.json'
            if status_path.is_file() and not status_path.is_symlink():
                controller_status = json.loads(status_path.read_text(encoding='utf-8'))
                if not isinstance(controller_status, dict):
                    controller_status = None
        except (OSError, ValueError):
            pass
        totals = {}
        for expense in expenses:
            totals[expense['currency']] = totals.get(expense['currency'], Decimal('0')) + Decimal(expense['amount'])
        files = project_assets(pid)
        with connect() as db:
            edits = dict(db.execute('SELECT relative,content FROM subtitle_edits WHERE project_id=?', (pid,)).fetchall())
        for item in files:
            item['subtitle_editor'] = None
            item['subtitle_edited'] = item['relative'] in edits
            path = base / item['relative'] / 'captions.srt'
            try:
                if 'captions.srt' in item['subtitles'] and path.stat().st_size <= 512 * 1024:
                    item['subtitle_editor'] = edits[item['relative']] if item['subtitle_edited'] else path.read_text(encoding='utf-8-sig')
            except (OSError, UnicodeError):
                pass
        return render_template('detail.html', p=row, states=states, files=files, history=history, expenses=expenses, totals=totals, controller_status=controller_status)

    @app.post('/projects/<pid>/edit')
    def edit_project(pid):
        project(pid)
        creator, title, due, note = (request.form.get(k, '').strip() for k in ('creator', 'title', 'due_date', 'note'))
        try:
            if due:
                date.fromisoformat(due)
            valid = bool(creator and title) and len(creator) <= 100 and len(title) <= 200 and len(note) <= 2000
        except ValueError:
            valid = False
        if not valid:
            flash('配信者名・案件名・納期・メモを確認してください。')
            return redirect(url_for('detail', pid=pid))
        with connect() as db:
            db.execute('UPDATE projects SET creator=?,title=?,due_date=?,note=?,updated_at=? WHERE id=?', (creator, title, due, note, time.time(), pid))
            event(db, pid, '案件情報を更新')
        flash('案件情報を保存しました。')
        return redirect(url_for('detail', pid=pid))

    @app.post('/projects/<pid>/expenses')
    def add_expense(pid):
        project(pid)
        description = request.form.get('description', '').strip()
        amount = request.form.get('amount', '').strip()
        currency = request.form.get('currency', '').strip().upper()
        try:
            number = Decimal(amount)
            valid = (number.is_finite() and 0 <= number <= Decimal('1000000000000')
                     and len(amount) <= 30 and -8 <= number.as_tuple().exponent <= 12)
        except InvalidOperation:
            valid = False
        if not valid or not description or len(description) > 100 or not currency.isascii() or not currency.isalpha() or not 3 <= len(currency) <= 8:
            flash('費用の内容・金額・通貨を確認してください。')
            return redirect(url_for('detail', pid=pid))
        with connect() as db:
            db.execute('INSERT INTO expenses(project_id,description,amount,currency,created_at) VALUES (?,?,?,?,?)', (pid, description, format(number, 'f'), currency, time.time()))
            event(db, pid, '費用を記録: ' + description)
        flash('費用を記録しました。請求額の自動取得ではありません。')
        return redirect(url_for('detail', pid=pid))

    @app.post('/projects/<pid>/expenses/<int:expense_id>/delete')
    def delete_expense(pid, expense_id):
        project(pid)
        with connect() as db:
            if db.execute('DELETE FROM expenses WHERE id=? AND project_id=?', (expense_id, pid)).rowcount:
                event(db, pid, '費用の記録を削除')
        return redirect(url_for('detail', pid=pid))

    @app.post('/projects/<pid>/clip-note')
    def clip_note(pid):
        project(pid)
        relative, status, note = (request.form.get(k, '').strip() for k in ('relative', 'status', 'note'))
        if relative not in {f['relative'] for f in project_assets(pid)} or status not in DELIVERY or len(note) > 1000:
            abort(400)
        with connect() as db:
            db.execute('INSERT INTO clip_notes(project_id,relative,status,note) VALUES (?,?,?,?) ON CONFLICT(project_id,relative) DO UPDATE SET status=excluded.status,note=excluded.note', (pid, relative, status, note))
            event(db, pid, '動画の納品メモを更新')
        flash('動画の納品状況とメモを保存しました。')
        return redirect(url_for('detail', pid=pid))

    @app.post('/projects/<pid>/clip-title')
    def clip_title(pid):
        project(pid)
        relative = request.form.get('relative', '')
        title = request.form.get('title', '').strip()
        if not title or len(title) > 200 or relative not in {f['relative'] for f in project_assets(pid)}:
            flash('動画とタイトルを確認してください。')
            return redirect(url_for('detail', pid=pid))
        with connect() as db:
            db.execute('INSERT INTO clip_titles(project_id,relative,title) VALUES (?,?,?) ON CONFLICT(project_id,relative) DO UPDATE SET title=excluded.title', (pid, relative, title))
            event(db, pid, '動画タイトルを更新')
        flash('タイトルを保存しました。ZIPのタイトル一覧にも反映されます。')
        return redirect(url_for('detail', pid=pid))

    @app.post('/projects/<pid>/subtitle')
    def save_subtitle(pid):
        project(pid)
        relative = request.form.get('relative', '')
        content = request.form.get('content', '')
        item = next((f for f in project_assets(pid) if f['relative'] == relative), None)
        if item is None or 'captions.srt' not in item['subtitles'] or len(content.encode('utf-8')) > 512 * 1024:
            abort(400)
        with connect() as db:
            db.execute('INSERT INTO subtitle_edits(project_id,relative,content) VALUES (?,?,?) ON CONFLICT(project_id,relative) DO UPDATE SET content=excluded.content', (pid, relative, content))
            event(db, pid, '字幕の編集版を保存')
        flash('字幕の編集版を保存しました。元字幕と動画は変更していません。')
        return redirect(url_for('detail', pid=pid))

    @app.get('/projects/<pid>/files/<path:relative>/<name>')
    def clip_file(pid, relative, name):
        project(pid)
        if name not in ('video.mp4', 'captions.srt', 'captions.ass', 'captions-edited.srt') or relative not in {f['relative'] for f in project_assets(pid)}:
            abort(404)
        if name == 'captions-edited.srt':
            with connect() as db:
                row = db.execute('SELECT content FROM subtitle_edits WHERE project_id=? AND relative=?', (pid, relative)).fetchone()
            if row is None:
                abort(404)
            return send_file(io.BytesIO(row['content'].encode('utf-8')), mimetype='application/x-subrip', as_attachment=True, download_name=name)
        base = data / 'productions' / pid
        path = base / relative / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
            abort(404)
        return send_file(path, as_attachment=name != 'video.mp4', conditional=True)

    def production_tools(name):
        root = Path(app.config['CLIPFORGE_DIR']).expanduser().resolve()
        configured = app.config['CLIPFORGE_PYTHON']
        python = Path(configured).expanduser().resolve() if configured else root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        return root, root / 'tools' / name, python

    def launch(base, action, command):
        with (base / 'controller.log').open('ab') as log:
            kwargs = {'cwd': str(Path(app.config['CLIPFORGE_DIR']).expanduser().resolve()),
                      'stdin': subprocess.DEVNULL, 'stdout': log, 'stderr': subprocess.STDOUT,
                      'env': {**os.environ, 'PYTHONUTF8': '1'}}
            if os.name == 'nt':
                kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs['start_new_session'] = True
            subprocess.Popen([sys.executable, str(ROOT / 'controller.py'), '--project-dir', str(base),
                              '--action', action, '--database', str(database), '--', *map(str, command)], **kwargs)

    @app.post('/projects/<pid>/start')
    def start(pid):
        row = project(pid)
        clipforge, script, python = production_tools('produce_formats.py')
        if not script.is_file() or not python.is_file() or not shutil_which('gh'):
            flash('ClipForge、仮想環境、またはGitHub CLIが見つかりません。設定手順を確認してください。')
            return redirect(url_for('detail', pid=pid))
        base = data / 'productions' / pid
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        with connect() as db:
            changed = db.execute("UPDATE projects SET status='starting',updated_at=? WHERE id=? AND status IN ('draft','start_failed')", (time.time(), pid)).rowcount
            if not changed:
                flash('この案件は既に開始済みです。重複投入はしません。')
                return redirect(url_for('detail', pid=pid))
            event(db, pid, '制作開始を指示')
        try:
            launch(base, 'start', [python, script, row['source_url'], '--mode', row['mode'], '--output', base, '--clips', row['clips']])
            with connect() as db:
                changed = db.execute("UPDATE projects SET status='started',updated_at=? WHERE id=? AND status='starting'", (time.time(), pid)).rowcount
                if changed:
                    event(db, pid, '制作コントローラー起動')
            flash('制作を指示しました。実行状態は下の記録に表示します。')
        except OSError:
            with connect() as db:
                db.execute("UPDATE projects SET status='start_failed',updated_at=? WHERE id=?", (time.time(), pid))
                event(db, pid, 'コントローラーを起動できませんでした')
            flash('起動に失敗しました。状態を確認してください。')
        return redirect(url_for('detail', pid=pid))

    @app.post('/projects/<pid>/delivery')
    def update_delivery(pid):
        project(pid)
        status = request.form.get('delivery', '')
        if status not in DELIVERY:
            abort(400)
        cost, currency, link = (request.form.get(k, '').strip() for k in ('cost_amount', 'cost_currency', 'delivery_url'))
        if len(cost) > 40 or len(currency) > 12 or len(link) > 2000:
            abort(400)
        with connect() as db:
            db.execute('UPDATE projects SET delivery=?,cost_amount=?,cost_currency=?,delivery_url=?,updated_at=? WHERE id=?', (status, cost, currency, link, time.time(), pid))
            event(db, pid, '納品情報を更新: ' + DELIVERY[status])
        flash('納品情報を保存しました。')
        return redirect(url_for('detail', pid=pid))

    @app.post('/projects/<pid>/resume')
    def resume(pid):
        project(pid)
        mode = request.form.get('mode', '')
        if mode not in ('long', 'tiktok', 'tiktok-capcut'):
            abort(400)
        base = data / 'productions' / pid
        output = base / mode
        state = output / 'production-state.json'
        clipforge, script, python = production_tools('produce_with_gemini.py')
        if not state.is_file() or state.is_symlink() or not output.resolve().is_relative_to(base.resolve()) or not script.is_file() or not python.is_file():
            flash('再接続に必要な保存済み状態またはClipForgeが見つかりません。')
            return redirect(url_for('detail', pid=pid))
        try:
            launch(base, 'resume', [python, script, '--resume', '--output', output])
            with connect() as db:
                event(db, pid, mode + ' の保存済みRunに再接続')
            flash('保存済みRunへの再接続を指示しました。処理中のコントローラーがある場合、重複起動は行いません。')
        except OSError:
            flash('再接続の起動に失敗しました。')
        return redirect(url_for('detail', pid=pid))

    @app.post('/projects/<pid>/import')
    def import_clip(pid):
        project(pid)
        mode = request.form.get('mode', '')
        if mode not in ('long', 'tiktok', 'tiktok-capcut'):
            abort(400)
        raw_source = request.form.get('clip_dir', '').strip()
        if not raw_source:
            flash('動画フォルダを指定してください。')
            return redirect(url_for('detail', pid=pid))
        source = Path(raw_source).expanduser()
        if not source.is_dir() or source.is_symlink():
            flash('動画フォルダを確認してください。')
            return redirect(url_for('detail', pid=pid))
        files = [source / name for name in ('video.mp4', 'captions.srt', 'captions.ass', 'render.json')]
        if not files[0].is_file() or files[0].is_symlink() or any(p.is_symlink() for p in files):
            flash('video.mp4が見つからないか、リンクが含まれています。')
            return redirect(url_for('detail', pid=pid))
        root = data / 'productions' / pid / mode / 'clips' / 'clips'
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = root / ('clip-import-' + uuid.uuid4().hex[:12])
        target.mkdir(mode=0o700)
        try:
            for file in files:
                if file.is_file():
                    shutil.copyfile(file, target / file.name)
            if not (target / 'render.json').exists():
                title = request.form.get('clip_title', '').strip()[:200] or source.name
                (target / 'render.json').write_text(json.dumps({'selection': {'title': title}}, ensure_ascii=False), encoding='utf-8')
        except OSError:
            shutil.rmtree(target)
            flash('動画を取り込めませんでした。')
            return redirect(url_for('detail', pid=pid))
        with connect() as db:
            event(db, pid, '既存の完成動画をコピー')
        flash('既存動画を案件へコピーしました。元ファイルはそのままです。')
        return redirect(url_for('detail', pid=pid))

    @app.route('/projects/<pid>/download', methods=['GET', 'POST'])
    def download(pid):
        row = project(pid)
        base = data / 'productions' / pid
        files = project_assets(pid)
        if request.method == 'POST':
            selected = set(request.form.getlist('clip'))
            files = [item for item in files if item['relative'] in selected]
        if not files:
            flash('納品する動画を選択してください。')
            return redirect(url_for('detail', pid=pid))
        tmp = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode='w+b')
        with connect() as db:
            edits = dict(db.execute('SELECT relative,content FROM subtitle_edits WHERE project_id=?', (pid,)).fetchall())
        with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
            for item in files:
                folder = base / item['relative']
                for name in ('video.mp4', 'captions.srt', 'captions.ass'):
                    path = folder / name
                    if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(base.resolve()):
                        bundle.write(path, item['relative'] + '/' + name,
                                     compress_type=zipfile.ZIP_STORED if name == 'video.mp4' else zipfile.ZIP_DEFLATED)
                if item['relative'] in edits:
                    bundle.writestr(item['relative'] + '/captions-edited.srt', edits[item['relative']])
            bundle.writestr('titles.json', json.dumps({'project': row['title'], 'clips': [{'file': i['relative'], 'title': i['title']} for i in files]}, ensure_ascii=False, indent=2))
        tmp.seek(0)
        return send_file(tmp, mimetype='application/zip', as_attachment=True, download_name='clipforge-delivery-' + pid[:8] + '.zip')

    return app


def re_id(value):
    return len(value) == 32 and all(c in '0123456789abcdef' for c in value)


def shutil_which(name):
    import shutil
    return shutil.which(name)


def assets(base):
    result = []
    if not base.is_dir() or base.is_symlink():
        return result
    for mode in ('long', 'tiktok', 'tiktok-capcut'):
        root = base / mode / 'clips' / 'clips'
        if not root.is_dir() or root.is_symlink() or not root.resolve().is_relative_to(base.resolve()):
            continue
        for folder in sorted(root.glob('clip-*')):
            if not folder.is_dir() or folder.is_symlink() or not folder.resolve().is_relative_to(base.resolve()):
                continue
            receipt = folder / 'render.json'
            title = folder.name
            try:
                if receipt.is_file() and not receipt.is_symlink():
                    record = json.loads(receipt.read_text(encoding='utf-8'))
                    title = str((record.get('selection') or {}).get('title', folder.name))[:500]
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            if (folder / 'video.mp4').is_file() and not (folder / 'video.mp4').is_symlink():
                subtitles = [name for name in ('captions.srt', 'captions.ass')
                             if (folder / name).is_file() and not (folder / name).is_symlink()]
                result.append({'relative': folder.relative_to(base).as_posix(), 'title': title,
                               'mode': mode, 'subtitles': subtitles})
    return result


if __name__ == '__main__':
    from waitress import serve
    print('ClipForge Delivery: http://127.0.0.1:8765', flush=True)
    serve(create_app(), host='127.0.0.1', port=8765, threads=4)
