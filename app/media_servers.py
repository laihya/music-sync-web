import time
import requests
import logging
from app.config import get_config

logger = logging.getLogger("media_servers")
_last_scan_time = 0


def notify_servers():
    global _last_scan_time
    config = get_config()
    interval = config.get("scan_interval", 300)
    now = time.time()
    if now - _last_scan_time < interval:
        return
    _last_scan_time = now

    servers = config.get("servers", [])
    for srv in servers:
        if not srv.get("enabled", True):
            continue
        srv_type = srv.get("type", "jellyfin")
        url = srv.get("url", "").rstrip("/")
        api_key = srv.get("api_key", "")
        try:
            if srv_type in ("jellyfin", "emby"):
                resp = requests.post(
                    f"{url}/Library/Refresh",
                    headers={"X-MediaBrowser-Token": api_key},
                    timeout=10
                )
                if resp.status_code in (200, 204):
                    logger.info("已通知 %s (%s) 扫描", srv.get("name"), srv_type)
                else:
                    logger.warning("通知 %s 失败: %d %s", srv.get("name"), resp.status_code, resp.text[:100])
            elif srv_type == "plex":
                resp = requests.get(
                    f"{url}/library/sections/{srv.get('library_id', '')}/refresh",
                    headers={"X-Plex-Token": api_key},
                    timeout=10
                )
                if resp.status_code == 200:
                    logger.info("已通知 Plex (%s) 扫描", srv.get("name"))
                else:
                    logger.warning("Plex 扫描失败: %d", resp.status_code)
        except Exception as e:
            logger.error("通知 %s 异常: %s", srv.get("name"), e)