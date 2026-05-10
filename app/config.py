import os, json, logging, secrets, bcrypt

CONFIG_DIR = os.environ.get("DATA_DIR", "/data")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "watch_dir": "/downloads",
    "media_dir": "/media",
    "failed_dir": "/failed",
    "scan_interval": 300,
    "min_duration_sec": 30,
    "max_files_per_hour": 200,
    "file_stable_checks": 3,
    "file_stable_interval_sec": 2,
    "allowed_extensions": [".mp3", ".flac", ".m4a", ".ogg", ".wma", ".aac", ".wav", ".ape", ".wv", ".alac"],
    "lossless_extensions": [".flac", ".wav", ".ape", ".wv", ".alac"],
    "enable_netease": False,
    "enable_qqmusic": False,
    "enable_kugou": False,
    "enable_discogs": False,
    "discogs_api_key": os.environ.get("DISCOGS_API_KEY", ""),
    "enable_acoustid": True,
    "acoustid_api_key": os.environ.get("ACOUSTID_API_KEY", ""),
    "netease_api_url": "",
    "qqmusic_api_url": "",
    "kugou_api_url": "",
    "webui_port": 8003,
    "webui_password_hash": None,
    "log_level": "INFO",
    "naming_pattern": "{artist} - {title}",
    "dir_pattern": "{artist}",
    "servers": []
}

config = {}
logger = logging.getLogger("config")

def load_config():
    global config
    if not os.path.exists(CONFIG_FILE):
        config = DEFAULT_CONFIG.copy()
        save_config()
    else:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            if k not in config:
                config[k] = v
        save_config()

    config["watch_dir"] = os.environ.get("WATCH_DIR", config["watch_dir"])
    config["media_dir"] = os.environ.get("MEDIA_DIR", config["media_dir"])
    config["failed_dir"] = os.environ.get("FAILED_DIR", config["failed_dir"])
    config["webui_port"] = int(os.environ.get("WEBUI_PORT", config["webui_port"]))
    env_dk = os.environ.get("DISCOGS_API_KEY")
    if env_dk is not None:
        config["discogs_api_key"] = env_dk
    env_ak = os.environ.get("ACOUSTID_API_KEY")
    if env_ak is not None:
        config["acoustid_api_key"] = env_ak

    env_pass = os.environ.get("WEBUI_PASSWORD")
    if env_pass:
        config["webui_password_hash"] = bcrypt.hashpw(env_pass.encode(), bcrypt.gensalt()).decode()
    elif not config.get("webui_password_hash"):
        random_pass = secrets.token_urlsafe(12)
        config["webui_password_hash"] = bcrypt.hashpw(random_pass.encode(), bcrypt.gensalt()).decode()
        print(f"*** 初始Web密码: {random_pass} ***")
        logger.warning(f"初始管理员密码: {random_pass}")
        save_config()

    for int_key in ["scan_interval", "min_duration_sec", "max_files_per_hour",
                    "file_stable_checks", "file_stable_interval_sec", "webui_port"]:
        if int_key in config:
            config[int_key] = int(config[int_key])

    config["enable_discogs"] = bool(config.get("discogs_api_key", "").strip())

    apply_log_level()
    return config

def save_config():
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def update_config(updates):
    global config
    needs_restart = []
    # 恢复默认 URL（如果留空）
    for api_key in ["netease_api_url", "qqmusic_api_url", "kugou_api_url"]:
        if api_key in updates and not updates[api_key].strip():
            updates[api_key] = DEFAULT_CONFIG[api_key]

    for k, v in updates.items():
        # 忽略已删除的配置项
        if k == "enable_musicbrainz":
            continue
        if k in ["scan_interval","min_duration_sec","max_files_per_hour",
                 "file_stable_checks","file_stable_interval_sec","webui_port"]:
            try: v = int(v)
            except: pass
        if k in ("watch_dir","media_dir","failed_dir","data_dir"):
            needs_restart.append(k)
        config[k] = v

    if "discogs_api_key" in updates:
        config["enable_discogs"] = bool(config["discogs_api_key"].strip())

    save_config()
    if "log_level" in updates:
        apply_log_level()
    return needs_restart

def apply_log_level():
    level = config.get("log_level", "INFO").upper()
    logging.getLogger().setLevel(getattr(logging, level, logging.INFO))
    logging.getLogger("watchdog").setLevel(logging.WARNING)

def get_config():
    return config

def set_password(new_password):
    config["webui_password_hash"] = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    save_config()

def check_password(password):
    stored = config.get("webui_password_hash")
    if not stored: return False
    return bcrypt.checkpw(password.encode(), stored.encode())