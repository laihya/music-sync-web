from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for
import logging
import os
import shutil
from app.config import get_config, update_config, set_password, check_password, save_config
from app.database import init_db, get_failure_list, update_failure_metadata, delete_failure_record, get_db, add_processed_record
from app.watcher import start_watcher, scan_existing_files, safe_format
from app.metadata import get_metadata, compute_sha256

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.urandom(24)

log_stream = []
MAX_LOG = 500


class StreamHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        log_stream.append(msg)
        if len(log_stream) > MAX_LOG:
            log_stream.pop(0)


handler = StreamHandler()
handler.setLevel(logging.DEBUG)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(handler)


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({"error": "未登录"}), 401
        return f(*args, **kwargs)
    return decorated


@app.route('/health')
def health():
    return "OK", 200


@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login_page'))
    return send_from_directory('templates', 'index.html')


@app.route('/login')
def login_page():
    return send_from_directory('templates', 'login.html')


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    if check_password(data.get('password', '')):
        session['logged_in'] = True
        return jsonify({"status": "ok"})
    return jsonify({"error": "密码错误"}), 403


@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('logged_in', None)
    return jsonify({"status": "ok"})


@app.route('/api/config', methods=['GET'])
@login_required
def get_settings():
    return jsonify(get_config())


@app.route('/api/config', methods=['POST'])
@login_required
def update_settings():
    updates = request.json
    # 转换布尔字段
    for bk in ["enable_netease", "enable_qqmusic", "enable_kugou", "enable_musicbrainz", "enable_discogs"]:
        if bk in updates and isinstance(updates[bk], str):
            updates[bk] = updates[bk].lower() == 'true'
    if 'discogs_api_key' in updates:
        updates['discogs_api_key'] = updates['discogs_api_key'].strip()
    needs_restart = update_config(updates)
    return jsonify({"needs_restart": needs_restart})


@app.route('/api/password', methods=['POST'])
@login_required
def change_password():
    new_pass = request.json.get('password')
    if not new_pass:
        return jsonify({"error": "需要密码"}), 400
    set_password(new_pass)
    return jsonify({"status": "ok"})


@app.route('/api/failures', methods=['GET'])
@login_required
def failures():
    return jsonify(get_failure_list())


@app.route('/api/failures/<int:fid>', methods=['PUT'])
@login_required
def update_failure(fid):
    data = request.json
    update_failure_metadata(fid, data.get('artist'), data.get('title'))
    return jsonify({"status": "ok"})


@app.route('/api/failures/<int:fid>', methods=['DELETE'])
@login_required
def delete_failure(fid):
    delete_failure_record(fid)
    return jsonify({"status": "ok"})


@app.route('/api/failures/<int:fid>/retry', methods=['POST'])
@login_required
def retry_failure(fid):
    items = get_failure_list()
    record = next((i for i in items if i['id'] == fid), None)
    if not record:
        return jsonify({"error": "未找到"}), 404
    failed_path = record.get('failed_path')
    if not failed_path or not os.path.exists(failed_path):
        return jsonify({"error": "失败文件不存在"}), 404
    artist = record.get('partial_artist')
    title = record.get('partial_title')
    if not artist or not title:
        meta = get_metadata(failed_path)
        if meta:
            artist = meta.get('artist') or artist
            title = meta.get('title') or title
    if not artist or not title:
        return jsonify({"error": "无法获取元数据"}), 400

    def safe(s):
        return "".join(c for c in s if c.isalnum() or c in (' ', '-', '_', '.', ',')).strip()
    s_artist, s_title = safe(artist), safe(title)
    ext = os.path.splitext(failed_path)[1].lower()
    config = get_config()
    dir_pattern = config["dir_pattern"]
    name_pattern = config["naming_pattern"]
    dir_path = safe_format(dir_pattern, artist=s_artist, title=s_title, album="")
    file_name = safe_format(name_pattern, artist=s_artist, title=s_title, album="") + ext
    full_dir = os.path.join(config["media_dir"], dir_path) if dir_path else config["media_dir"]
    os.makedirs(full_dir, exist_ok=True)
    dest_path = os.path.join(full_dir, file_name)
    try:
        shutil.copy2(failed_path, dest_path)
        add_processed_record(failed_path, compute_sha256(failed_path), dest_path, artist, title, None, status='success')
        delete_failure_record(fid)
        orig_src = record.get('source_path')
        if orig_src:
            with get_db() as db:
                db.execute("DELETE FROM processed_files WHERE source_path=?", (orig_src,))
        return jsonify({"status": "ok", "message": f"已保存至 {dest_path}"})
    except Exception as e:
        logging.exception("重试失败: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route('/api/scan', methods=['POST'])
@login_required
def trigger_scan():
    try:
        scan_existing_files()
        return jsonify({"status": "ok", "message": "扫描已启动"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/test_discogs', methods=['POST'])
@login_required
def test_discogs_key():
    key = request.json.get('key', '').strip()
    if not key:
        return jsonify({"status": "error", "message": "Key不能为空"}), 400
    try:
        import discogs_client
        d = discogs_client.Client('music-sync/1.0', user_token=key)
        results = d.search('test', type='artist')
        if results.pages and len(results.page(1)) > 0:
            return jsonify({"status": "ok", "message": "Key有效，请点击“保存配置”以启用"})
        else:
            return jsonify({"status": "error", "message": "Key有效但无搜索结果"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"测试失败: {str(e)}"}), 400


@app.route('/api/logs')
@login_required
def get_logs():
    return jsonify(log_stream[-200:])


@app.route('/api/clean', methods=['POST'])
@login_required
def clean_data():
    target = request.json.get('target', 'all')
    import sqlite3
    db_path = os.path.join(os.environ.get("DATA_DIR", "/data"), "music_sync.db")
    try:
        conn = sqlite3.connect(db_path)
        if target in ('processed', 'all'):
            conn.execute("DELETE FROM processed_files")
        if target in ('failures', 'all'):
            conn.execute("DELETE FROM failure_log")
        if target in ('cache', 'all'):
            conn.execute("DELETE FROM metadata_cache")
        conn.commit()
        conn.close()
        return jsonify({"status": "ok", "message": f"已清理 {target} 数据"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    logging.warning("404 请求路径: %s", request.path)
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(Exception)
def handle_exception(e):
    logging.exception("未捕获异常: %s", e)
    return jsonify({"error": "服务器内部错误"}), 500


def start_web():
    config = get_config()
    port = config["webui_port"]
    init_db()
    start_watcher()
    from waitress import serve
    serve(app, host='0.0.0.0', port=port)