import os
import time
import logging
import threading
from datetime import datetime, timedelta
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from mutagen import File as MutagenFile

from app.config import get_config
from app.database import is_file_processed, add_processed_record
from app.workflow import process_with_temp
from app.media_servers import notify_servers
from app.metadata import check_any_source_available

logger = logging.getLogger("watcher")

observer = None
process_queue = []
queue_lock = threading.Lock()
processing = False
hourly_count = 0
hour_start = datetime.now()
last_notify_time = 0
processed_since_last_notify = False


def safe_format(template, artist="", title="", album=""):
    template = template.replace("{artist}", artist)
    template = template.replace("{title}", title)
    template = template.replace("{album}", album)
    return template


def file_is_ready(filepath):
    config = get_config()
    checks = int(config.get("file_stable_checks", 3))
    interval = float(config.get("file_stable_interval_sec", 2))
    temp_exts = ['.part', '.crdownload', '.!qB', '.tmp']

    dir_name = os.path.dirname(filepath)
    base_name = os.path.basename(filepath)
    for ext in temp_exts:
        if os.path.exists(os.path.join(dir_name, base_name + ext)):
            return False

    prev_size, prev_mtime = -1, -1
    for _ in range(checks):
        try:
            stat = os.stat(filepath)
            cur_size, cur_mtime = stat.st_size, stat.st_mtime
        except FileNotFoundError:
            return False
        if cur_size == prev_size and cur_mtime == prev_mtime:
            pass
        else:
            prev_size, prev_mtime = cur_size, cur_mtime
        time.sleep(interval)
    return True


class MusicHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        src_path = event.src_path
        ext = os.path.splitext(src_path)[1].lower()
        if ext not in get_config().get("allowed_extensions", []):
            return
        with queue_lock:
            if src_path not in process_queue:
                process_queue.append(src_path)


def processing_loop():
    global processing, last_notify_time, processed_since_last_notify
    processing = True
    while processing:
        try:
            # 网络检测（所有启用源）
            if not check_any_source_available():
                logger.warning("无刮削源可达，暂停30秒...")
                time.sleep(30)
                continue

            if process_queue:
                with queue_lock:
                    # 每次只取一个文件
                    item = process_queue.pop(0)
                try:
                    if not os.path.exists(item):
                        continue
                    if file_is_ready(item):
                        min_dur = int(get_config().get("min_duration_sec", 30))
                        try:
                            audio = MutagenFile(item)
                            if audio and audio.info and audio.info.length < min_dur:
                                logger.info("音频时长过短 (%ds): %s", audio.info.length, item)
                                add_processed_record(item, '', '', status='skipped')
                                continue
                        except:
                            pass
                        # 单文件处理
                        success = process_file(item)
                        if success:
                            processed_since_last_notify = True
                        # 处理完一个后稍作休息，避免瞬时压力
                        time.sleep(0.5)
                except Exception as e:
                    logger.error("处理文件异常: %s - %s", item, e)
            else:
                # 队列空，检查是否需要通知
                if processed_since_last_notify and (time.time() - last_notify_time) >= get_config().get("scan_interval", 300):
                    try:
                        notify_servers()
                        processed_since_last_notify = False
                        last_notify_time = time.time()
                    except Exception as e:
                        logger.error("通知服务器失败: %s", e)
                time.sleep(2)
        except Exception as loop_err:
            logger.error("处理循环异常: %s", loop_err)
            time.sleep(5)


def process_file(src_path):
    global hourly_count, hour_start
    config = get_config()
    now = datetime.now()
    if now - hour_start > timedelta(hours=1):
        hour_start = now
        hourly_count = 0
    if hourly_count >= config.get("max_files_per_hour", 200):
        logger.warning("已达处理上限，跳过: %s", src_path)
        return False

    success = process_with_temp(src_path, safe_format, None)
    if success:
        hourly_count += 1
    return success


def scan_existing_files():
    config = get_config()
    watch_dir = config["watch_dir"]
    allowed_exts = config.get("allowed_extensions", [])
    if not os.path.exists(watch_dir):
        return
    logger.info("开始扫描现有文件: %s", watch_dir)
    count = 0
    for root, dirs, files in os.walk(watch_dir):
        for fname in files:
            filepath = os.path.join(root, fname)
            if os.path.splitext(fname)[1].lower() not in allowed_exts:
                continue
            if is_file_processed(filepath):
                continue
            with queue_lock:
                if filepath not in process_queue:
                    process_queue.append(filepath)
                    count += 1
    logger.info("已发现 %d 个新文件，加入处理队列", count)


def start_watcher():
    global observer
    config = get_config()
    watch_dir = config["watch_dir"]
    os.makedirs(watch_dir, exist_ok=True)

    event_handler = MusicHandler()
    observer = Observer()
    observer.schedule(event_handler, watch_dir, recursive=True)
    observer.start()
    logger.info("开始监听目录: %s", watch_dir)

    threading.Thread(target=processing_loop, daemon=True).start()

    def delayed_scan():
        time.sleep(5)
        scan_existing_files()

    threading.Thread(target=delayed_scan, daemon=True).start()
    return observer


def stop_watcher():
    global observer, processing
    processing = False
    if observer:
        observer.stop()
        observer.join()