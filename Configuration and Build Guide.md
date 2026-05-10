🛠️ Music Sync Web 完整配置与构建指南
适用版本：v3.2
适用人群：首次部署、希望快速上手的用户

一、环境要求
操作系统：Linux（推荐 Debian/Ubuntu），任何支持 Docker 的发行版均可

软件依赖：

Docker 20.10+

Docker Compose v2+

宿主机目录：需要四个真实存在且可读写的目录（下载目录只需只读权限）

用途	示例路径	权限
下载目录（存放 PT 做种文件）	/mnt/disk1/downloads	ro（只读）
媒体目录（整理后文件）	/mnt/disk1/music	rw（读写）
失败暂存区（无法识别文件）	/mnt/disk1/failed	rw
数据持久化（配置、数据库）	/home/user/music-sync-data	rw

二、项目结构
text
music-sync-web/
├── .env.example          # 环境变量模板（复制为 .env 后修改）
├── docker-compose.yml    # Docker 编排文件
├── Dockerfile            # 镜像构建文件
├── requirements.txt      # Python 依赖
├── setup.sh              # 一键部署脚本
├── README.md             # 项目总览
├── CONFIGURATION.md      # 本指南
└── app/                  # 应用源码
    ├── main.py
    ├── config.py
    ├── database.py
    ├── watcher.py
    ├── metadata.py
    ├── workflow.py
    ├── media_servers.py
    ├── web.py
    ├── templates/
    │   ├── login.html
    │   └── index.html
    └── static/
        └── style.css

三、快速部署（推荐用一键脚本）
1. 准备宿主机目录
bash
# 创建四个目录
sudo mkdir -p /mnt/disk1/downloads /mnt/disk1/music /mnt/disk1/failed /home/user/music-sync-data

# 设置读写权限（媒体、失败、数据目录必须允许 UID=1000 的用户读写）
sudo chown -R 1000:1000 /mnt/disk1/music /mnt/disk1/failed /home/user/music-sync-data
# 下载目录只需可读，通常权限设置为 755 即可
sudo chmod 755 /mnt/disk1/downloads
2. 配置环境变量
bash
cd music-sync-web
cp .env.example .env
nano .env   # 或使用 vi
在 .env 中修改以下内容：

properties
DOWNLOAD_PATH=/mnt/disk1/downloads
MEDIA_PATH=/mnt/disk1/music
FAILED_PATH=/mnt/disk1/failed
DATA_PATH=/home/user/music-sync-data

# AcoustID API Key（留空使用官方测试 Key，建议自己注册）
ACOUSTID_API_KEY=

# Discogs API Key（留空则不启用）
DISCOGS_API_KEY=

# Web 管理员密码（留空自动生成随机密码）
WEBUI_PASSWORD=
3. 执行一键部署脚本
bash
bash setup.sh
脚本会自动创建目录、设置权限、构建镜像并启动容器。完成后会打印访问地址和获取初始密码的命令。

四、手动部署步骤（不使用脚本）
1. 目录准备与权限
bash
sudo mkdir -p /mnt/disk1/downloads /mnt/disk1/music /mnt/disk1/failed /home/user/music-sync-data
sudo chown -R 1000:1000 /mnt/disk1/music /mnt/disk1/failed /home/user/music-sync-data
sudo chmod 755 /mnt/disk1/downloads
2. 配置 .env
bash
cp .env.example .env
nano .env   # 修改路径和可选 Key
3. 构建与启动
bash
docker compose up -d --build
4. 获取初始密码
bash
docker compose logs | grep "初始管理员密码"
5. 访问 Web 管理界面
text
http://你的服务器IP:8003

五、首次使用配置（Web 界面）
登录：使用上一步获取的密码登录。

刮削源设置：

🎵 AcoustID 指纹（默认启用）：无需操作，声纹匹配已可用。

🟢 国内源：默认关闭，如需启用，先点击卡片切换为“已启用”，然后展开「换源配置」填入 API 地址。

🟣 Discogs：需在 .env 中设置 DISCOGS_API_KEY，无需 Web 操作。

保存配置：点击「保存配置」按钮，看到“配置已保存”弹窗即生效。

手动触发扫描：点击「扫描下载目录中已存在的音乐文件」按钮。

六、获取 API Key（可选）
AcoustID：访问 https://acoustid.org/login → 用 GitHub / Google 登录 → Applications → Register Application → 获取 API Key → 写入 .env 中的 ACOUSTID_API_KEY。

Discogs：访问 https://www.discogs.com/settings/developers → 生成 Personal Access Token → 写入 .env 中的 DISCOGS_API_KEY。

七、常见问题
❌ 容器启动报权限错误
确保媒体、失败、数据目录属主为 1000:1000：

bash
sudo chown -R 1000:1000 /your/media /your/failed /your/data
❌ AcoustID 声纹匹配无结果
检查 fpcalc 是否正常（docker compose exec -T music-sync fpcalc -version）

官方测试 Key 有频率限制，建议申请自己的 Key

非热门歌曲可能无 AcoustID 记录，将自动降级到文本搜索

❌ 国内源不工作
确认已在 Web 界面开启对应源

确认 API URL 已填写且可连通

❌ 忘记 Web 密码
bash
docker compose logs | grep "初始管理员密码"
# 或删除数据目录下的 config.json 重启容器
rm /your/data/path/config.json
docker compose restart

❌ 没有内嵌封面
封面获取完全依赖用户自行配置的国内音乐源。
如果用户未启用这些源，或者未填写有效的 API URL，声纹匹配成功后无法自动下载封面，文件将缺少封面图片，但其他所有功能（文件整理、标签修正、媒体服务器通知等）均不受影响。
如果你希望保留封面的自动下载，至少需要配置一个国内源，并在 Web 设置中开启它。


八、一键部署脚本 setup.sh
bash
#!/bin/bash
set -e

echo "====== Music Sync Web 快速部署 ======"

# 从 .env 读取路径（若 .env 不存在则使用默认值）
if [ -f .env ]; then
    source .env
else
    cp .env.example .env
    echo "🔥 请编辑 .env 文件，填写路径和 API Key，然后重新运行本脚本。"
    exit 1
fi

DOWNLOAD_PATH="${DOWNLOAD_PATH:-/mnt/downloads}"
MEDIA_PATH="${MEDIA_PATH:-/mnt/music}"
FAILED_PATH="${FAILED_PATH:-/mnt/failed}"
DATA_PATH="${DATA_PATH:-./data}"

echo "正在创建目录..."
sudo mkdir -p "$DOWNLOAD_PATH" "$MEDIA_PATH" "$FAILED_PATH" "$DATA_PATH"

echo "正在设置权限 (UID:GID=1000)..."
sudo chown -R 1000:1000 "$MEDIA_PATH" "$FAILED_PATH" "$DATA_PATH"
sudo chmod 755 "$DOWNLOAD_PATH"

echo "正在构建并启动容器..."
docker compose up -d --build

echo ""
echo "✅ 部署完成！"
echo "请使用以下命令获取初始密码："
echo "  docker compose logs | grep '初始管理员密码'"
echo "然后访问 http://$(hostname -I | awk '{print $1}'):8003 登录管理。"
九、授权与合规声明
本项目使用 GPLv3 许可证。

不内置任何国内音乐平台的 API 地址，用户需自行获取并遵守相关服务条款。

作者对因使用本项目产生的任何版权或法律问题不承担责任。

Happy Listening! 🎶