# 🎵 Music Sync Web

**一个自动监听下载目录、智能刮削音乐元数据并整理至媒体库的开源工具。**

---

[![Docker](https://img.shields.io/badge/Docker-✔-blue)](https://www.docker.com)
[![Python](https://img.shields.io/badge/Python-3.11-green)](https://python.org)
[![License](https://img.shields.io/badge/License-GPLv3-yellow)](LICENSE)

> **当前版本：v3.2**  
> **适用场景**：PT 做种保护、Jellyfin/Emby/Plex 媒体库自动化整理  
> **核心原则**：源文件只读、声纹优先、文本多源兜底、Web 可视化管理  
> **⚠️ 合规声明**：本项目默认不内置任何国内音乐平台的 API 地址，所有国内源均处于关闭状态。用户如需启用，必须自行查询并填入合法的 API 端点地址，并遵守相关服务条款。本项目作者不提供、不维护、不担保任何第三方 API 的可用性及合法性。

---

## 📋 目录

- [功能概览](#功能概览)
- [工作流程](#工作流程)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [Web 界面](#web-界面)
- [刮削源详解](#刮削源详解)
- [声纹匹配](#声纹匹配)
- [封面功能](#封面功能)
- [常见问题](#常见问题)
- [开发计划](#开发计划)
- [免责声明](#免责声明)
- [许可](#许可)

---

## 🚀 功能概览

- 🎧 **文件监听**：递归监控下载目录，完整性检测（大小+修改时间稳定），支持临时下载文件过滤
- 🧠 **智能刮削**：
  - 🎵 **声纹优先**：通过 AcoustID 指纹匹配 MusicBrainz，获取高精度元数据
  - 📝 **文本兜底**：用户自行配置的国内源和 Discogs 多源顺序搜索，评分择优
- 🖼️ **封面内嵌**：自动下载高分辨率封面，写入音频文件
- 🏷️ **标签写入**：修正艺术家、歌名、专辑、发行日期等信息
- 📂 **目录整理**：按艺术家（可自定义模板）自动创建目录，无损优先替换低质文件
- 🔔 **媒体服务器通知**：处理完成后自动通知 Jellyfin/Emby/Plex 扫描库
- 🖥️ **Web 管理界面**：中文面板，支持配置、刮削源开关、失败文件处理、实时日志
- 📦 **单容器部署**：Docker Compose 一键启动，资源占用低

---

## ⚙️ 工作流程

1. **文件监听** → 新文件加入处理队列（受每小时上限限制）
2. **复制到临时目录** → 保护源文件，所有修改都在临时副本上进行
3. **获取元数据**：
   - 先检查缓存
   - 启用声纹匹配时，提取音频指纹 → AcoustID 查找录音 ID → MusicBrainz 获取完整信息
   - 若声纹失败，使用内嵌标签+文件名生成关键词，顺序调用用户配置的文本刮削源（国内源 → Discogs）
   - 多源评分，选最高分（需 ≥0.8），若声纹成功则直接采用声纹结果
4. **写入标签** → 将正确元数据（含封面）写回临时文件
5. **移动文件** → 按模板移动到媒体目录，自动创建艺术家目录，无损优先替换
6. **通知媒体服务器** → 队列清空且至少有一个文件处理成功后，节流通知扫描
7. **失败处理** → 无法获取元数据的文件复制到失败区，可在 Web 界面手动修正重试

---

## 🛠 快速开始

### 环境要求

- Docker 20.10+
- Docker Compose v2+
- 宿主机需要映射的目录（下载目录、媒体目录、失败暂存区、数据目录）

### 部署步骤

1. **克隆项目**

    ```bash
    git clone https://github.com/laihya/music-sync-web.git
    cd music-sync-web
    ```

2. **配置环境变量**

    ```bash
    cp .env.example .env
    nano .env   # 编辑路径和可选 Key
    ```

    `.env` 文件示例：

    ```properties
    DOWNLOAD_PATH=/mnt/downloads
    MEDIA_PATH=/mnt/music
    FAILED_PATH=/mnt/failed
    DATA_PATH=./data

    ACOUSTID_API_KEY=
    DISCOGS_API_KEY=
    WEBUI_PASSWORD=
    ```

3. **设置目录权限**

    ```bash
    sudo mkdir -p /mnt/disk1/downloads /mnt/disk1/music /mnt/disk1/failed /home/user/music-sync-data
    sudo chown -R 1000:1000 /mnt/disk1/music /mnt/disk1/failed /home/user/music-sync-data
    sudo chmod 755 /mnt/disk1/downloads
    ```

4. **构建并启动**

    ```bash
    docker compose up -d --build
    ```

5. **获取初始密码**

    ```bash
    docker compose logs | grep "初始管理员密码"
    ```

6. **访问 Web 界面**

    ```text
    http://你的服务器IP:8003
    ```

---

## ⚙️ 配置说明

### docker-compose.yml 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WATCH_DIR` | `/downloads` | 监听的下载目录（容器内） |
| `MEDIA_DIR` | `/media` | 媒体目标目录 |
| `FAILED_DIR` | `/failed` | 失败暂存区 |
| `DATA_DIR` | `/data` | 数据持久化目录（配置、数据库） |
| `WEBUI_PORT` | `8003` | Web 服务端口 |
| `WEBUI_PASSWORD` | (随机) | 管理员密码，留空则自动生成 |
| `DISCOGS_API_KEY` | (空) | Discogs 个人访问令牌，填写后自动启用 Discogs |
| `ACOUSTID_API_KEY` | (空) | AcoustID API Key，留空则使用官方测试 Key `I5CvINoX9AI` |
| `TZ` | `Asia/Shanghai` | 时区 |

### 卷挂载

| 容器内路径 | 宿主机路径 | 权限 | 说明 |
|-----------|------------|------|------|
| `/downloads` | 你的下载目录 | `ro` | 只读，保护 PT 做种文件 |
| `/media` | 你的媒体目录 | `rw` | 处理后文件存放位置 |
| `/failed` | 你的失败暂存区 | `rw` | 无法处理的文件存放处 |
| `/data` | 你的数据目录 | `rw` | 存放 `config.json` 和 `music_sync.db` |

> **权限注意**：宿主机目录属主需为 UID:GID 1000:1000（可在 compose 中通过 `user: "1000:1000"` 设置）。

### 热更新支持的配置项
- 刮削源开关、扫描间隔、时长阈值、处理上限、扩展名、无损扩展名、日志级别
- 命名模板、目录模板、媒体服务器列表
- 国内源 API URL（在 Web 界面换源配置中修改后即时生效）

### 需重启容器的配置项
- 监听目录、媒体目录、失败目录、Web 端口

---

## 🖥️ Web 界面

### 功能一览

| 页面 | 功能 |
|------|------|
| **配置** | 系统参数、刮削源开关、换源 URL、目录/文件名模板、日志级别 |
| **媒体服务器** | 添加/删除 Jellyfin/Emby/Plex |
| **失败文件** | 查看失败原因，手动修改元数据后重试 |
| **实时日志** | 自动轮询（每 2 秒），显示最近 200 条日志 |
| **数据清理** | 分别清理已处理/失败/缓存记录 |
| **密码修改** | 在线修改管理员密码 |

### 刮削源卡片（Web 配置页）
- 🎵 **AcoustID 指纹**（默认启用）— 声纹匹配入口
- 🟢 **国内源**（默认关闭，需用户自行启用并填写 API 地址）
- 🟣 **Discogs**：由环境变量 `DISCOGS_API_KEY` 自动管理，卡片仅显示状态，不可手动切换

> 点击卡片即可切换启用/禁用。国内源在启用前，请务必在“换源配置”中填入正确的 API URL，否则该源将返回空结果。

---

## 🎵 刮削源详解

| 源 | 类型 | 默认启用 | 权重 | 备注 |
|----|------|----------|------|------|
| **AcoustID** | 声纹 | ✅ | 1.5 | 通过 fpcalc 提取指纹，匹配 MusicBrainz 录音 |
| **国内源** | 文本 | ❌ (用户配置) | 1.0 | 国内曲库首选，需提供 API URL |
| **Discogs** | 文本 | ❌ (需 Key) | 0.8 | 外语歌曲补充，由环境变量注入 Token |

> 🛑 **重要**：国内源均为非官方 API，本项目不提供任何内置端点。用户必须自行获取合法的 API 地址并在 Web 配置中填入，否则这些源不会生效。Discogs 需要使用自己的个人访问令牌并通过环境变量 `DISCOGS_API_KEY` 注入。

---

## 🎙️ 声纹匹配

声纹匹配是本项目的核心特色之一，流程如下：

1. **提取指纹**：`fpcalc -json <file>`，输出音频的 Chromaprint 指纹和时长
2. **查找 AcoustID**：携带指纹和 API Key 请求 `api.acoustid.org/v2/lookup`
3. **获取 MusicBrainz 元数据**：使用返回的录音 ID 调用 `musicbrainzngs.get_recording_by_id`
4. **简繁转换**：自动将繁体中文转为简体

**优点**：
- 完全独立于文件名和标签，即使文件标签全乱也能准确识别
- 准确性高（通常 >0.9 分）

**限制**：
- 依赖 AcoustID 数据库，部分新歌或小众歌曲可能无记录
- 免费 API Key 有请求频率限制

**启用方式**：在 Web 界面的“AcoustID 指纹”卡片中切换为启用状态（默认开启）。  
如需使用自己的 AcoustID Key，请在 `.env` 中配置 `ACOUSTID_API_KEY=你的Key`；留空则自动使用官方测试 Key `I5CvINoX9AI`。

---

## 🖼️ 封面功能

封面获取**完全依赖**用户自行配置的国内音乐源（如网易云音乐、QQ音乐、酷狗音乐）。  
如果用户未启用这些源或 API URL 为空，声纹匹配成功后无法自动下载封面，文件将缺少封面图片，但其他所有功能（文件整理、标签修正、媒体服务器通知等）均不受影响。

✅ 若需封面自动下载，请务必在 Web 设置中**开启至少一个国内源**并填入正确的 API 地址。

---

## ❓ 常见问题

<details>
<summary>Q：下载目录是只读的，为什么文件还能移动？</summary>

A：源文件始终保留，处理时先复制到容器内临时目录，所有修改都在副本上进行，最后将最终文件移至媒体库，源文件完好。
</details>

<details>
<summary>Q：为什么国内源默认关闭？</summary>

A：出于版权合规考虑，本项目不内置任何国内音乐平台的 API 地址。用户需自行获取合法的接口地址。
</details>

<details>
<summary>Q：如何添加国内源？</summary>

A：在 Web 界面“配置”中，先开启对应源的卡片，然后在“换源配置”中填入有效的 API URL，保存配置后即刻生效。
</details>

<details>
<summary>Q：声纹匹配需要额外配置吗？</summary>

A：不需要。声纹匹配默认使用官方测试 Key `I5CvINoX9AI`，免费可用。如需提高稳定性，可前往 AcoustID 官网免费注册一个 Key，并在 `.env` 中配置 `ACOUSTID_API_KEY=你的Key`。
</details>

<details>
<summary>Q：支持哪些音频格式？</summary>

A：默认支持 `.mp3`, `.flac`, `.m4a`, `.ogg`, `.wma`, `.aac`, `.wav`, `.ape`, `.wv`, `.alac`，可在 Web 配置中修改。
</details>

<details>
<summary>Q：忘记 Web 密码怎么办？</summary>

```bash
# 查看日志
docker compose logs | grep "初始管理员密码"
# 或重置
rm /your/data/path/config.json
docker compose restart
```
</details>

<details>
<summary>Q：容器启动报权限错误？</summary>

```bash
sudo chown -R 1000:1000 /your/media /your/failed /your/data
```
</details>

---

## 📅 开发计划

- [x] v3.2 声纹优先+文本兜底+Discogs 自动配置
- [ ] v3.3 失败文件自动重试、日志分级高亮
- [ ] v3.4 智能封面选择、流派标签刮削
- [ ] v4.0 内置播放器、接入本地小爱同学

---

## ⚠️ 免责声明

> 本项目仅供个人学习研究技术使用，严禁任何形式的商业用途，包括但不限于售卖、牟利，不得使用本代码进行任何形式的牟利/贩卖/传播。  
> 本项目数据来源原理是从各官方音乐平台的公开服务中拉取数据，因此本项目不对数据的准确性负责。使用本项目的过程中可能会产生版权数据，对于这些版权数据，本项目不拥有它们的所有权，为了避免侵权，使用者务必在 24 小时内清除使用本项目过程中所产生的版权数据。  
> 本项目完全免费，仅供个人私下范围研究交流学习技术使用，并开源发布于 GitHub 面向全世界人用作对技术的学习交流，本项目不对项目内的技术可能存在违反当地法律法规的行为作保证，禁止在违反当地法律法规的情况下使用本项目，对于使用者在明知或不知当地法律法规不允许的情况下使用本项目所造成的任何违法违规行为由使用者承担，本项目不承担由此造成的任何直接、间接、特殊、偶然或结果性责任。  
> 项目仅提供工具框架，用户自行配置的第三方 API 若涉及侵权（如非官方 / 盗版接口），责任由用户自行承担。用户配置的 API 需确保符合对应平台的服务条款，禁止用于商业用途 / 大规模爬取数据，如侵权，责任由用户自行承担。  
> 若你使用了本项目，将代表你接受以上声明。

---

## 📜 许可

本项目基于 [GPLv3 License](LICENSE) 进行许可。  
**重要：** 使用者必须遵守各自地区的法律法规，本项目作者对因不当使用本项目而产生的任何法律后果不承担责任。

---

**Happy Listening! 🎶**