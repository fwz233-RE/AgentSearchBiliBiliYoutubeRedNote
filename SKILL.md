---
name: content-hub
description: 多平台内容聚合抓取工具（支持 YouTube、Bilibili、小红书的搜索、抓取、字幕获取与 AI 打标）
---

# Content Hub OpenClaw Skill 

这是一个适用于 openClaw Agent 的官方技能说明文件（Skill Metadata）。通过此技能，Agent 可以自动化操作各大内容平台的数据。

## ⚠️ 重要执行原则 (CRITICAL INSTRUCTION)

作为 Agent，在执行 Content Hub 相关任务时，**强烈鼓励你直接使用编译好的可执行文件**，而不是调用 Python 源文件执行！

- **Windows 下默认路径:** `c:\Users\123\Downloads\content-hub\dist\content-hub.exe`
- 根据环境，你也可以使用相对路径 `dist\content-hub.exe` (Windows) 或 `./dist/content-hub` (macOS/Linux)

**不要** 使用诸如 `python backend/cli.py` 等命令来执行操作！务必直接调用系统可执行程序。

---

## 🛠️ 可用能力 (Capabilities)

你可以使用该 CLI 工具完成以下任务，请使用前文约定的工具路径（以下简写为 `content-hub.exe` 作为示例）：

### 1. 搜索与发现 (Search)
按关键词跨平台搜索内容（**注意：搜索多词关键词时，直接输入即可，请不要加双引号或单引号，工具会自动识别**）：
*   `content-hub.exe search youtube <关键词>`  (例如: `content-hub.exe search youtube MacBook Neo`)
*   `content-hub.exe search bilibili <关键词> --page 2`
*   `content-hub.exe search xiaohongshu <关键词> --page-size 10`

### 2. 内容抓取 (Scrape)
获取指定 URL 的元数据（并自动分析字幕/打标）：
*   单链接：`content-hub.exe scrape <URL>`
*   多链接：`content-hub.exe scrape <URL1> <URL2>`
*   不需要转写或打标：`content-hub.exe scrape <URL> --no-transcribe --no-tag`

### 3. 数据管理查看 (List & Show)
*   查看全部数据：`content-hub.exe list`
*   按平台筛选：`content-hub.exe list --platform youtube`
*   查看特定 ID 的详情（获取正文/完整信息）：`content-hub.exe show <ID>`
*   附带完整字幕查看：`content-hub.exe show <ID> --subtitle`

### 4. 数据导出与维护 (Export & Maintain)
*   导出 JSON/CSV 报表：`content-hub.exe export --format json --output <文件名>.json`
*   提取和保存字幕：`content-hub.exe subtitle <ID> --output <文件名>.txt`
*   刷新旧数据的各项指标（播放量/点赞等）：`content-hub.exe refresh <ID>`
*   删除无用数据：`content-hub.exe delete <ID>`

### 5. 音频管理 (Audio)
*   管理下载的播客音频：`content-hub.exe audio list`

## 💡 使用小贴士 (Tips for Agent)
1. 涉及文件输出时，务必使用明确的相对或绝对路径，保证自己能读取到。
2. 配置参数通过 `content-hub.exe config set <KEY> <VALUE>` 自动设置。如果没有指定 API Key 或 Cookie，仍然可以探索受限的基础能力。
3. 请始终遵循直接拉起 `exe` 执行文件这一首要原则，享受无依赖毫秒级启动的红利。
