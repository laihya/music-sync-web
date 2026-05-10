import os, time, shutil, tempfile, logging, gc, requests
from mutagen import File as MutagenFile
from mutagen.id3 import ID3, APIC
from mutagen.flac import Picture, FLAC
from app.config import get_config
from app.metadata import get_metadata, compute_sha256
from app.database import add_processed_record, is_file_processed, add_failure_record

logger = logging.getLogger("workflow")


def process_with_temp(src_path, safe_format_func, notify_callback):
    config = get_config()
    media_dir = config["media_dir"]
    if is_file_processed(src_path):
        return False

    tmp_dir = tempfile.mkdtemp(prefix="music_sync_")
    tmp_file = os.path.join(tmp_dir, os.path.basename(src_path))
    sha = None
    try:
        shutil.copy2(src_path, tmp_file)

        meta = get_metadata(tmp_file)
        if not meta or not meta.get("artist") or not meta.get("title"):
            _move_to_failed(src_path, "无法获取有效元数据")
            add_processed_record(src_path, compute_sha256(tmp_file), '', status='failed')
            return False

        artist, title, album = meta["artist"], meta["title"], meta.get("album")
        cover_url = meta.get("cover_url")
        release_date = meta.get("release_date")

        def safe(s):
            return "".join(c for c in s if c.isalnum() or c in (' ', '-', '_', '.', ',')).strip()

        s_artist, s_title, s_album = safe(artist), safe(title), safe(album or "")

        if not s_artist or not s_title:
            _move_to_failed(src_path, "处理后名称为空", meta)
            add_processed_record(src_path, compute_sha256(tmp_file), '', status='failed')
            return False

        # 写标签（在临时文件上）
        try:
            audio = MutagenFile(tmp_file, easy=True)
            if audio is not None:
                audio["artist"] = artist
                audio["title"] = title
                if album:
                    audio["album"] = album
                if release_date:
                    try:
                        audio["date"] = str(release_date)[:10]
                    except:
                        pass
                audio.save()

                if cover_url:
                    try:
                        cover_data = requests.get(cover_url, timeout=10).content
                        if tmp_file.lower().endswith('.flac'):
                            flac = FLAC(tmp_file)
                            pic = Picture()
                            pic.type = 3
                            pic.mime = 'image/jpeg'
                            pic.data = cover_data
                            flac.add_picture(pic)
                            flac.save()
                        elif tmp_file.lower().endswith('.mp3'):
                            id3 = ID3(tmp_file)
                            id3.add(APIC(3, 'image/jpeg', 3, 'Front cover', cover_data))
                            id3.save()
                    except Exception as e:
                        logger.warning("封面写入失败: %s", e)
            else:
                logger.warning("无法写入标签: %s", tmp_file)
        except Exception as tag_err:
            logger.warning("标签写入错误: %s", tag_err)

        # 构建目标路径
        dir_pattern = config.get("dir_pattern", "{artist}")
        name_pattern = config.get("naming_pattern", "{artist} - {title}")
        dir_path = safe_format_func(dir_pattern, artist=s_artist, title=s_title, album=s_album).strip()
        file_name = safe_format_func(name_pattern, artist=s_artist, title=s_title, album=s_album).strip() + os.path.splitext(src_path)[1].lower()

        full_dir = os.path.join(media_dir, dir_path) if dir_path else media_dir
        os.makedirs(full_dir, exist_ok=True)
        dest_path = os.path.join(full_dir, file_name)

        # 无损替换逻辑
        lossless_exts = config.get("lossless_extensions", [])
        current_is_lossless = os.path.splitext(src_path)[1].lower() in lossless_exts
        base = os.path.splitext(dest_path)[0]
        for existing_ext in config.get("allowed_extensions", []):
            existing_path = base + existing_ext
            if os.path.exists(existing_path) and existing_path != dest_path:
                existing_is_lossless = existing_ext in lossless_exts
                if current_is_lossless and not existing_is_lossless:
                    os.remove(existing_path)
                    logger.info("替换低质量文件: %s", existing_path)
                elif not current_is_lossless and existing_is_lossless:
                    logger.info("已存在无损文件，跳过: %s", existing_path)
                    # 提前记录哈希（使用现有文件）
                    sha = compute_sha256(existing_path)
                    add_processed_record(src_path, sha, existing_path, artist, title, album)
                    return True
                else:
                    if existing_path != dest_path:
                        os.remove(existing_path)

        # 移动临时文件到最终位置
        shutil.move(tmp_file, dest_path)
        # 使用目标路径计算哈希，确保数据一致性
        sha = compute_sha256(dest_path)
        logger.info("已处理: %s -> %s", src_path, dest_path)

        # 记录成功
        add_processed_record(src_path, sha, dest_path, artist, title, album)

        # 清理大对象，帮助 GC（可选）
        del audio, meta, cover_data
        gc.collect()

        return True

    except Exception as e:
        logger.exception("临时目录处理异常: %s", e)
        _move_to_failed(src_path, f"处理异常: {str(e)}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _move_to_failed(src_path, reason, meta=None):
    config = get_config()
    failed_dir = config["failed_dir"]
    os.makedirs(failed_dir, exist_ok=True)
    base = os.path.basename(src_path)
    failed_path = os.path.join(failed_dir, f"{int(time.time())}_{base}")
    try:
        shutil.copy2(src_path, failed_path)
        logger.info("已复制到失败区: %s", failed_path)
    except:
        failed_path = None
    art, tit, alb = None, None, None
    if meta:
        art, tit, alb = meta.get("artist"), meta.get("title"), meta.get("album")
    add_failure_record(src_path, failed_path, reason, art, tit, alb)