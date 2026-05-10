import sys
import logging

print("音乐同步助手启动中...", flush=True)
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

print("加载配置...", flush=True)
from app.config import load_config
load_config()

print("启动Web服务...", flush=True)
from app.web import start_web
start_web()