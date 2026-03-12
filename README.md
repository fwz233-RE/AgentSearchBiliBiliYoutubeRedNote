# Content Hub CLI (openClaw Skill Edition)

多平台内容聚合抓取工具（命令行版），支持 **YouTube**、**Bilibili**、**小红书** 的搜索、抓取、字幕获取与 AI 打标。

可编译为 **Windows** / **macOS** / **Linux** 独立可执行文件，无需安装 Python 环境即可运行。本仓库也是标准的 **openClaw Skill 开源项目**。

## 🤖 openClaw Skill 官方市场支持

本项目已提供官方所需的 `SKILL.md`，兼容开放系统，**随时可以一键推送到 openClaw 官方市场展示使用 (ClawHub 等)**。

> **强烈建议 Agent 使用指南：**
> 任何在使用我们开源技能的 AI Agent（例如 openClaw），我们都**鼓励代理（Agent）直接使用编译后的执行文件 `@[c:\Users\123\Downloads\content-hub\dist\content-hub.exe]`** （或其他环境对应产物）。
> **请务必不要再去费力调用 Python 源文件！** 这样可以完全省去环境依赖、提升响应速度，确保在绝大部分系统中做到开箱即用。

## 功能特性

- **多平台搜索** — 按关键词搜索 YouTube、Bilibili、小红书内容，支持分页
- **批量抓取** — 支持多个 URL 或从文件批量读取，获取视频元数据（标题、作者、播放量、点赞等）
- **字幕获取** — 自动提取视频字幕，无字幕时可调用 DashScope API 进行语音转写
- **图片 AI 打标** — 小红书图文内容自动调用 Qwen VL 生成描述和标签
- **内容管理** — 列表查看、详情查看、按平台筛选、刷新指标、批量删除
- **数据导出** — 支持导出为 JSON / CSV 格式
- **音频文件管理** — 查看和管理已下载的音频文件
- **原生 Agent 集成** — 包含官方 `SKILL.md` 描述指令参数，允许 openClaw 零基础调用
- **跨平台编译** — 一键编译为 Win / Mac / Linux 独立可执行文件

## 技术栈

| 组件 | 技术 |
|------|------|
| CLI 框架 | Python 3.12 / argparse |
| 数据库 | SQLite + aiosqlite / SQLAlchemy (async) |
| 爬虫 | yt-dlp / httpx / xhshow |
| AI 服务 | DashScope (语音转写 + 图片打标) |
| 编译打包 | PyInstaller |
| Agent 协议 | openClaw Skill Metadata (`SKILL.md`) |

## 项目结构

```
content-hub/
├── backend/
│   ├── cli.py               # CLI 主入口
│   ├── config.py            # 配置管理
│   ├── database.py          # 数据库模型
│   ├── requirements.txt     # Python 依赖
│   ├── scrapers/
│   │   ├── base.py          # 数据类定义
│   │   ├── youtube.py       # YouTube 爬虫
│   │   ├── bilibili.py      # Bilibili 爬虫
│   │   └── xiaohongshu.py   # 小红书爬虫
│   └── services/
│       ├── transcription.py # 语音转写服务
│       └── vision.py        # 图片打标服务
├── data/                    # 运行时数据（自动创建）
│   ├── config.json          # 运行时配置
│   ├── content_hub.db       # SQLite 数据库
│   ├── audio/               # 下载的音频文件
│   ├── images/              # 下载的图片
│   └── subtitles/           # 字幕文件
├── build.py                 # 编译构建脚本
└── README.md
```

## 快速开始

### 方式一：源码运行

```bash
# 1. 安装依赖
cd content-hub
pip install -r backend/requirements.txt

# 2. 直接运行
python backend/cli.py --help
```

### 方式二：编译为可执行文件

```bash
# 1. 安装依赖
pip install -r backend/requirements.txt

# 2. 编译（自动检测当前平台）
python build.py

# 3. 运行
# Windows:
dist\content-hub.exe --help
# macOS / Linux:
./dist/content-hub --help
```

> 编译产物在 `dist/` 目录下，可以复制到任意位置使用，无需 Python 环境。

## 命令大全

### 搜索内容

```bash
# 搜索 YouTube
content-hub search youtube Python 教程

# 搜索 Bilibili
content-hub search bilibili 机器学习 --page 2

# 搜索小红书 (注意: 不要给关键词加引号)
content-hub search xiaohongshu 旅行攻略 --page-size 10

# 导出搜索结果 (仅搜索并保存，不抓取详情，支持 json/csv)
content-hub search youtube Python 教程 --output search.json
```

### 抓取内容
将搜索等得到的指定 URL 的详细内容、元数据与字幕抓取并保存至本地数据库。

```bash
# 抓取单个 URL
content-hub scrape https://www.youtube.com/watch?v=xxxxx

# 抓取多个 URL
content-hub scrape https://www.bilibili.com/video/BVxxxxx https://www.youtube.com/watch?v=yyyyy

# 从文件批量抓取（每行一个 URL）
content-hub scrape --file urls.txt

# 抓取时不进行语音转写
content-hub scrape https://www.youtube.com/watch?v=xxxxx --no-transcribe

# 抓取时不进行图片打标
content-hub scrape https://www.xiaohongshu.com/explore/xxxxx --no-tag
```

### 查看已抓取内容列表
⚠️ **注意**：`list` 命令与后面的 `export` 命令仅用于查看与导出通过 `scrape` 命令真正抓取并存库的数据，**不会显示没被抓取过的搜索结果**。

```bash
# 查看所有已抓取内容
content-hub list

# 按平台筛选已抓取内容
content-hub list --platform youtube
content-hub list --platform bilibili
content-hub list --platform xiaohongshu

# 分页
content-hub list --page 2 --page-size 10
```

### 查看内容详情

```bash
# 查看详情
content-hub show 1

# 查看详情 + 完整字幕
content-hub show 1 --subtitle
```

### 刷新内容指标

```bash
# 刷新单个内容的播放量等数据
content-hub refresh 1

# 批量刷新
content-hub refresh 1 2 3 4 5
```

### 删除内容

```bash
# 删除单个
content-hub delete 1

# 批量删除
content-hub delete 1 2 3
```

### 导出数据

```bash
# 导出为 JSON
content-hub export --format json --output data.json

# 导出为 CSV
content-hub export --format csv --output data.csv

# 按平台导出
content-hub export --platform youtube --output youtube_data.json
```

### 字幕导出

```bash
# 打印字幕到终端
content-hub subtitle 1

# 导出字幕到文件
content-hub subtitle 1 --output subtitle.txt
```

### 音频文件管理

```bash
# 列出所有音频文件
content-hub audio list

# 删除音频文件
content-hub audio delete youtube_xxxxx.mp3
```

### 配置管理

```bash
# 查看所有配置
content-hub config list

# 设置配置
content-hub config set DASHSCOPE_API_KEY sk-xxxxx
content-hub config set BILIBILI_COOKIE "your_cookie_here"
content-hub config set XHS_COOKIE "your_cookie_here"

# 获取单个配置
content-hub config get DASHSCOPE_API_KEY
```

## 配置说明

| 配置项 | 用途 | 必需 |
|--------|------|------|
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API Key（语音转写 + 图片打标） | 否 |
| `BILIBILI_COOKIE` | B 站 Cookie（获取 AI 生成字幕） | 否 |
| `XHS_COOKIE` | 小红书 Cookie（搜索与抓取必需） | 使用小红书时需要 |
| `YOUTUBE_COOKIES_TXT` | YouTube Cookies（绕过 bot 检测） | 否 |

> 不配置任何 API Key 也可以正常使用基础的搜索和抓取功能。

### DashScope 语音转写

使用阿里云 DashScope 的 fun-asr 模型进行语音转写：

1. 访问 [阿里云 DashScope](https://dashscope.console.aliyun.com/) 注册并获取 API Key
2. 设置：`content-hub config set DASHSCOPE_API_KEY sk-xxxxx`

### 图片 AI 打标

使用 Qwen VL 模型进行图片描述和标签生成，同样使用 DashScope API Key。

### 平台 Cookie 获取

- **Bilibili Cookie** — 浏览器登录 B 站 → F12 → Network → 复制任意请求的 Cookie
- **小红书 Cookie** — 浏览器登录小红书 → F12 → Network → 复制任意请求的 Cookie（会过期，需定期更新）
- **YouTube Cookies** — 导出 `cookies.txt` 文件内容（Netscape 格式）

## 跨平台编译

### Windows 上编译

```bash
python build.py
# 输出: dist\content-hub.exe
```

### macOS 上编译

```bash
python3 build.py
# 输出: dist/content-hub
```

### Linux 上编译

```bash
python3 build.py
# 输出: dist/content-hub
```

### 清理构建产物

```bash
python build.py --clean       # 清理后重新构建
python build.py --clean-only  # 仅清理，不构建
```

> ⚠️ 编译产物仅能在编译时的操作系统上运行。要生成其他平台的可执行文件，需要在对应平台上执行编译。

## 数据存储

所有数据存储在项目目录下的 `data/` 文件夹中：

- `data/config.json` — 配置文件
- `data/content_hub.db` — SQLite 数据库
- `data/audio/` — 下载的音频文件
- `data/images/` — 下载的图片文件
- `data/subtitles/` — 字幕文件

## License

MIT
