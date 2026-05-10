import os, re, hashlib, logging, time, subprocess, json, requests, musicbrainzngs, zhconv
from difflib import SequenceMatcher
from mutagen import File
from app.config import get_config
from app.database import cache_metadata, get_cached_metadata

logging.getLogger("musicbrainzngs").setLevel(logging.WARNING)

logger = logging.getLogger("metadata")
musicbrainzngs.set_useragent("music-sync", "1.0")
musicbrainzngs.set_rate_limit(1)

INVALID_TITLE_PATTERN = re.compile(r'^track\s*\d+$', re.IGNORECASE)
FILENAME_PATTERN = re.compile(r'^(?P<title>.+?)\s*-\s*(?P<artist>.+?)(?:\s*\(.*?\))?\s*$')
HEADERS = {"User-Agent": "Mozilla/5.0"}


def compute_sha256(filepath):
    sha = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            sha.update(chunk)
    return sha.hexdigest()


def check_any_source_available():
    config = get_config()
    if config.get("enable_acoustid") and _check_url("https://api.acoustid.org"):
        return True
    if config.get("enable_netease") and _check_url("https://music.163.com"):
        return True
    if config.get("enable_qqmusic") and _check_url("https://c.y.qq.com"):
        return True
    if config.get("enable_kugou") and _check_url("https://songsearch.kugou.com"):
        return True
    if config.get("enable_discogs") and config.get("discogs_api_key") and _check_url("https://api.discogs.com"):
        return True
    return False


def _check_url(url, timeout=2):
    try:
        requests.head(url, timeout=timeout)
        return True
    except:
        return False


# ---------- 候选标签提取 ----------
def extract_candidates(filepath):
    candidates = []
    local = _read_easy_tags(filepath)
    if local:
        candidates.append(local)
    fname = os.path.splitext(os.path.basename(filepath))[0]
    match = FILENAME_PATTERN.match(fname)
    if match:
        candidates.append({
            "artist": match.group("artist").strip(),
            "title": match.group("title").strip(),
            "album": None
        })
    dirname = os.path.basename(os.path.dirname(filepath))
    if dirname:
        candidates.append({
            "artist": dirname,
            "title": fname,
            "album": None
        })
    return candidates


def _read_easy_tags(filepath):
    try:
        audio = File(filepath, easy=True)
        if not audio: return None
        artist = None
        for tag in ('artist', 'author', 'performer', 'albumartist'):
            val = audio.get(tag, [None])[0]
            if val and str(val).strip():
                artist = str(val).strip()
                break
        title = None
        for tag in ('title', 'tracktitle'):
            val = audio.get(tag, [None])[0]
            if val and str(val).strip():
                title = str(val).strip()
                break
        album = audio.get('album', [None])[0]
        if artist and title and not INVALID_TITLE_PATTERN.match(title):
            return {"artist": artist, "title": title, "album": str(album).strip() if album else None}
    except:
        pass
    return None


# ---------- 声纹匹配（AcoustID + MusicBrainz）----------
def _search_acoustid(filepath):
    FALLBACK_KEY = "I5CvINoX9AI"
    api_key = get_config().get("acoustid_api_key", "").strip()
    if not api_key:
        api_key = FALLBACK_KEY

    try:
        proc = subprocess.run(
            ["fpcalc", "-json", filepath],
            capture_output=True, text=True, timeout=15
        )
        if proc.returncode != 0:
            logger.debug("fpcalc 失败: %s", proc.stderr)
            return []
        fpcalc_data = json.loads(proc.stdout)
        fingerprint = fpcalc_data.get("fingerprint")
        duration = fpcalc_data.get("duration")
        if not fingerprint:
            return []

        params = {
            "client": api_key,
            "duration": int(duration),
            "fingerprint": fingerprint,
            "meta": "recordingids",
        }
        resp = requests.get("https://api.acoustid.org/v2/lookup", params=params, timeout=10)
        if resp.status_code == 429:
            logger.warning("AcoustID 限流，降级到文本搜索")
            return []
        if resp.status_code != 200:
            logger.debug("AcoustID API 错误: %s", resp.status_code)
            return []

        data = resp.json()
        if data.get("status") != "ok":
            return []

        for result in data.get("results", [])[:3]:
            score = result.get("score", 0)
            recordings = result.get("recordings", [])
            if not recordings:
                continue
            rec_id = recordings[0].get("id")
            if not rec_id:
                continue

            try:
                recording = musicbrainzngs.get_recording_by_id(
                    rec_id, includes=["artists", "releases"]
                )
                mb = recording.get("recording", {})
                artist = mb.get("artist-credit", [{}])[0].get("artist", {}).get("name", "")
                title = mb.get("title", "")
                album = ""
                for release in mb.get("release-list", []):
                    if release.get("status") == "Official":
                        album = release.get("title", "")
                        break
                if not album and mb.get("release-list"):
                    album = mb["release-list"][0].get("title", "")

                if artist:
                    artist = zhconv.convert(artist, "zh-cn")
                if title:
                    title = zhconv.convert(title, "zh-cn")
                if album:
                    album = zhconv.convert(album, "zh-cn")

                if artist and title:
                    return [{
                        "artist": artist,
                        "title": title,
                        "album": album,
                        "score": score,
                        "source": "acoustid"
                    }]
            except Exception as e:
                logger.debug("MusicBrainz 录音查询失败: %s", e)
                continue
        return []
    except Exception as e:
        logger.debug("AcoustID 匹配失败: %s", e)
        return []


# ---------- 封面补全（用国内源，需用户配置URL）----------
def _fetch_cover(artist, title):
    config = get_config()
    if config.get("enable_netease"):
        url = config.get("netease_api_url", "").strip()
        if url:
            try:
                resp = requests.post(url, data={"s": f"{artist} {title}", "type": 1, "limit": 1},
                                    headers={"Referer": "https://music.163.com", **HEADERS}, timeout=8)
                data = resp.json()
                songs = data.get("result", {}).get("songs", [])
                if songs:
                    cover = songs[0].get("al", {}).get("picUrl")
                    if cover:
                        return cover + "?param=500y500"
            except:
                pass
    if config.get("enable_qqmusic"):
        url = config.get("qqmusic_api_url", "").strip()
        if url:
            try:
                params = {"w": f"{artist} {title}", "format": "json", "n": 1}
                resp = requests.get(url, params=params, headers={"Referer": "https://y.qq.com", **HEADERS}, timeout=8)
                data = resp.json()
                songs = data.get("data", {}).get("song", {}).get("list", [])
                if songs:
                    albummid = songs[0].get("albummid", "")
                    if albummid:
                        return f"https://y.gtimg.cn/music/photo_new/T002R500x500M000{albummid}.jpg"
            except:
                pass
    if config.get("enable_kugou"):
        url = config.get("kugou_api_url", "").strip()
        if url:
            try:
                params = {"keyword": f"{artist} {title}", "page": 1, "pagesize": 1}
                resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
                data = resp.json()
                songs = data.get("data", {}).get("lists", [])
                if songs:
                    cover = songs[0].get("AlbumImg", "")
                    if cover:
                        return cover
            except:
                pass
    return None


# ---------- 文本刮削源（URL必须由用户在Web配置中提供，不留备用URL）----------
def _search_netease(keyword):
    url = get_config().get("netease_api_url", "").strip()
    if not url:
        return []
    try:
        data = {"s": keyword, "type": 1, "limit": 3}
        resp = requests.post(url, data=data, headers={"Referer": "https://music.163.com", **HEADERS}, timeout=8)
        result = resp.json()
        songs = result.get("result", {}).get("songs", [])
        results = []
        for s in songs:
            results.append({
                "artist": s["ar"][0]["name"],
                "title": s["name"],
                "album": s["al"]["name"],
                "cover_url": s["al"]["picUrl"] + "?param=500y500",
                "release_date": None,
                "source": "netease"
            })
        return results
    except Exception as e:
        return []


def _search_qqmusic(keyword):
    url = get_config().get("qqmusic_api_url", "").strip()
    if not url:
        return []
    try:
        params = {"w": keyword, "format": "json", "n": 3}
        resp = requests.get(url, params=params, headers={"Referer": "https://y.qq.com", **HEADERS}, timeout=8)
        result = resp.json()
        songs = result.get("data", {}).get("song", {}).get("list", [])
        results = []
        for s in songs:
            results.append({
                "artist": s["singer"][0]["name"],
                "title": s["songname"],
                "album": s.get("albumname", ""),
                "cover_url": f"https://y.gtimg.cn/music/photo_new/T002R500x500M000{s['albummid']}.jpg",
                "release_date": None,
                "source": "qqmusic"
            })
        return results
    except Exception as e:
        return []


def _search_kugou(keyword):
    url = get_config().get("kugou_api_url", "").strip()
    if not url:
        return []
    try:
        params = {"keyword": keyword, "page": 1, "pagesize": 3}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        result = resp.json()
        songs = result.get("data", {}).get("lists", [])
        results = []
        for s in songs:
            results.append({
                "artist": s["SingerName"],
                "title": s["SongName"],
                "album": s.get("AlbumName", ""),
                "cover_url": s.get("AlbumImg", ""),
                "release_date": None,
                "source": "kugou"
            })
        return results
    except Exception as e:
        return []


def _search_discogs(api_key, artist, title):
    try:
        import discogs_client
        d = discogs_client.Client('music-sync/3.0', user_token=api_key)
        res = d.search(f"{artist} {title}", type='release')
        results = []
        if res.pages > 0:
            for item in res.page(1)[:3]:
                artists = [a.name for a in item.artists]
                results.append({"artist": ", ".join(artists), "title": item.title, "source": "discogs"})
        return results
    except:
        return []


# ---------- 置信度评分 ----------
def score_match(candidate, result):
    if not candidate: return 0.0
    artist_cand = candidate.get("artist", "").strip().lower()
    title_cand = candidate.get("title", "").strip().lower()
    artist_res = result.get("artist", "").strip().lower()
    title_res = result.get("title", "").strip().lower()
    if not artist_res or not title_res: return 0.0
    artist_sim = SequenceMatcher(None, artist_cand, artist_res).ratio()
    title_sim = SequenceMatcher(None, title_cand, title_res).ratio()
    score = 0.4 * artist_sim + 0.6 * title_sim
    source_weight = {
        "acoustid": 1.5, "netease": 1.0, "qqmusic": 0.95,
        "kugou": 0.85, "discogs": 0.8
    }
    return score * source_weight.get(result.get("source", ""), 0.8)


# ---------- 主元数据获取（指纹优先）----------
def get_metadata(filepath):
    config = get_config()
    sha = compute_sha256(filepath)
    cached = get_cached_metadata(sha)
    if cached:
        return cached

    if not check_any_source_available():
        logger.warning("无刮削源可达，暂停")
        return None

    # ========== 第 1 优先级：音频指纹 ==========
    if config.get("enable_acoustid"):
        acoustid_results = _search_acoustid(filepath)
        if acoustid_results:
            best = max(acoustid_results, key=lambda x: x.get("score", 0))
            if best.get("score", 0) > 0.8:
                logger.info("指纹匹配成功: %s - %s (得分 %.2f)", best["artist"], best["title"], best["score"])
                cover_url = best.get("cover_url")
                if not cover_url:
                    cover_url = _fetch_cover(best["artist"], best["title"])
                final = {
                    "artist": best["artist"],
                    "title": best["title"],
                    "album": best.get("album"),
                    "cover_url": cover_url,
                    "release_date": best.get("release_date"),
                    "source": "acoustid"
                }
                cache_metadata(sha, filepath, final["artist"], final["title"], final.get("album"), final["source"])
                return final

    # ========== 第 2 优先级：本地标签 / 文件名 ==========
    candidates = extract_candidates(filepath)
    best_candidate = candidates[0] if candidates else {"artist": "", "title": ""}
    keyword = f"{best_candidate.get('artist', '')} {best_candidate.get('title', '')}".strip()
    if not best_candidate.get("artist") or not best_candidate.get("title"):
        for c in candidates[1:]:
            if c.get("artist") and c.get("title"):
                keyword = f"{c['artist']} {c['title']}"
                best_candidate = c
                break
    if not keyword:
        logger.debug("无有效搜索关键词")
        return None

    # ========== 第 3 优先级：多源文本搜索（URL由用户配置） ==========
    source_status = {}
    if config.get("enable_netease"):
        source_status["netease"] = {"results": _search_netease(keyword)}
        time.sleep(0.5)
    if config.get("enable_qqmusic"):
        source_status["qqmusic"] = {"results": _search_qqmusic(keyword)}
        time.sleep(0.5)
    if config.get("enable_kugou"):
        source_status["kugou"] = {"results": _search_kugou(keyword)}
        time.sleep(0.5)
    if config.get("enable_discogs") and config.get("discogs_api_key"):
        source_status["discogs"] = {"results": _search_discogs(config["discogs_api_key"], best_candidate["artist"], best_candidate["title"])}
        time.sleep(0.5)

    log_parts = []
    global_best_score = -1
    global_best_match = None
    global_best_source = None

    for src_name, status in source_status.items():
        if not status["results"]:
            log_parts.append(f"{src_name}=无结果")
            continue
        best_src_score = 0
        best_src_match = None
        for r in status["results"]:
            s = score_match(best_candidate, r)
            if s > best_src_score:
                best_src_score = s
                best_src_match = r
        log_parts.append(f"{src_name}={best_src_score:.2f}")
        if best_src_score > global_best_score:
            global_best_score = best_src_score
            global_best_match = best_src_match
            global_best_source = src_name

    logger.info("文本刮削打分: %s", ", ".join(log_parts))

    if not global_best_match or global_best_score < 0.8:
        logger.info("最佳文本得分低于0.8，刮削失败")
        return None

    logger.info("选用 %s (得分 %.2f)", global_best_source, global_best_score)

    final = {
        "artist": global_best_match["artist"],
        "title": global_best_match["title"],
        "album": global_best_match.get("album"),
        "cover_url": global_best_match.get("cover_url"),
        "release_date": global_best_match.get("release_date"),
        "source": global_best_source
    }
    cache_metadata(sha, filepath, final["artist"], final["title"], final.get("album"), final["source"])
    return final