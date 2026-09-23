# Reachy 英雄联盟陪玩助手

让 Reachy Mini 在《英雄联盟》对局中陪你聊天、接住吐槽，并用动作回应。本项目面向 Windows 本地运行，结合 Reachy Mini、游戏内只读数据和可选的云端语音与 AI 服务。

## 功能

- **语音对话：**开始陪玩后，可直接喊“默默”或设置的搭子名字；“陌陌”等常见同音转写也能识别。对局中明显的吐槽和甩锅，在“热闹一点”模式下无需唤醒词。
- **三档陪伴强度：**“安静陪伴”“恰到好处”和“热闹一点”。点击后立即提交后端，确认成功才更新选中状态。“热闹一点”允许战斗中短回应，主动间隔为 8 秒。短暂静音和暂停采集分别控制。
- **情绪支持：**回应优先照顾玩家当下的感受，不会抓住气话逐字纠正，也不会在每次阵亡时机械地重复安慰。
- **对局观察：**通过英雄联盟 Live Client Data 的本地只读接口读取当前对局信息，并分析你选定且位于前台的游戏窗口。可以确认本局英雄与阵营，预加载本局英雄的出装资料。
- **装备记忆：**本地包含英雄联盟装备、常见外号和效果。出装建议来自 OP.GG，按本局英雄及分路加载；查询不可用时，助手仍可查本地装备资料。
- **Reachy Mini 动作：**包含 Hugging Face 社区动作的固定版本目录和执行工具，可根据情绪回应触发动作。动作文件在首次运行时按需下载；社区应用资源与接入情况见[社区资源说明](docs/community-resources.md)。

## 页面与服务

| 服务 | 地址 | 作用 |
| --- | --- | --- |
| 陪玩页面与后端 | http://127.0.0.1:8768/ | 前端和 FastAPI 后端由同一个本地服务提供。 |
| 诊断页面 | http://127.0.0.1:8768/diagnostics | 检查本地服务和机器人设备。 |
| Reachy Mini Control | http://127.0.0.1:8000/ | 官方桌面控制软件启动的本地机器人服务。 |
| Live Client Data | https://127.0.0.1:2999/ | 英雄联盟对局期间提供的本地只读接口。 |

主要代码位于 `reachy_lol/`；社区动作工具位于 `reachy_skills/`；装备资料位于 `memory/equipment.json`。机器人接入依赖独立安装的 Reachy Mini Control，本仓库不包含该桌面软件。

## 环境要求

- Windows 10 或 11，64 位。
- Python 3.12 64 位和 Python Launcher（`py` 命令）。
- Reachy Mini 与官方 [Reachy Mini Control](https://pollen-robotics-reachy-mini.hf.space/download)。
- 联网安装 Python 依赖、下载动作和查询在线出装资料。
- 要使用云端语音识别、对话、语音合成和画面理解，需在本机配置兼容服务及其 API 凭证。没有这些服务时，应用可以启动，但完整语音陪玩不可用。

## 安装与启动

```powershell
git clone https://github.com/HONGKONGBALL/reachy-lol-companion.git
cd reachy-lol-companion
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

也可以在文件管理器中运行 `Setup-Companion.cmd`。安装完成后，在项目根目录创建或编辑 `.env`，填写自己的模型服务信息，再启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -OpenBrowser
```

也可以运行 `Start-Companion.cmd`。保持启动窗口打开，然后访问 [http://127.0.0.1:8768/](http://127.0.0.1:8768/)。停止时在服务窗口按 `Ctrl+C`。

第一次连接时，先打开 Reachy Mini Control 并确认机器人就绪，再在陪玩页面点击“连接本体”。之后选择本机音频设备、测试声音，并点击“开始陪伴”。进入对局后让英雄联盟窗口保持前台。结束或暂停陪伴后，语音采集会按页面操作停止。

如果端口 8768 已被其他程序占用，可换用 8770：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -Port 8770 -OpenBrowser
```

**不要同时启动两个机器人后台。**Reachy Mini Control 已占用 8000 端口时，不要再运行 `start-robot.ps1`；后者只在不使用官方 Control 桌面应用时，作为替代后台使用。

## 配置云端服务

`.env.example` 提供配置模板。可以为画面理解、聊天、语音识别和语音合成分别指定服务，也可以使用同一个 OpenAI 兼容服务。配置项包括 `VISION_*`、`CHAT_*`、`ASR_*` 和 `TTS_*`。每一类服务的地址和密钥需要成对填写；两者留空时，沿用公共 `MODEL_BASE_URL` 和 `MODEL_API_KEY`。

示例模板默认将语音识别和合成设为百炼提供商。根据自己的服务修改 `ASR_PROVIDER`、`TTS_PROVIDER`、接口地址、模型名与 API Key。`VOICE_*` 项配置具体音色；音色必须受所选 TTS 平台和模型支持。填写密钥后，在页面刷新配置并确认四项服务均显示已配置。

`.env`、本机的 `preferences.json`、设备配置、游戏画面和本地会话记录不会提交到 Git。**不要将含密钥的 `.env` 上传或分享。**选择启用云端功能时，对话语音或所选游戏画面会按需发送给你配置的模型服务；请按该服务商的政策评估数据保留方式。

## 项目结构

| 路径 | 内容 |
| --- | --- |
| `reachy_lol/app.py`、`app.js`、`index.html` | 本地 API、前端交互和页面。 |
| `reachy_lol/runtime.py` | 语音、对话、对局观察、回复调度和本体连接。 |
| `reachy_lol/cloud.py` | 模型接口、语音对话和游戏事实分析。 |
| `reachy_lol/opgg.py`、`match_research.py` | 本局英雄、装备知识及在线出装资料预加载。 |
| `reachy_skills/` | HF 社区动作索引、动作加载和播放工具。 |
| `memory/equipment.json` | 本地装备名称、外号、效果和英雄索引。 |
| `docs/user-guide.pdf` | 三页用户指南；同目录 Markdown 为可编辑版本。 |
| `docs/保存与迁移清单.md` | 网吧或其他公共电脑的保存、迁移与离开清单。 |
| `tests/` | 对话、游戏状态、设备连接和前端模式同步等自动化测试。 |

## 开发命令

安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

运行自动化测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/test_mode_sync.cjs
```

浏览已接入的动作或预演一个动作：

```powershell
.\.venv\Scripts\python.exe -m reachy_skills list
.\.venv\Scripts\python.exe -m reachy_skills play stella.think
```

动作命令默认只预演，不控制真实机器人。部分 `tools/` 脚本会调用收费云端服务、读取真实游戏画面或操作硬件；运行前请查看对应脚本内容。

## 文档与数据来源

- [用户指南](docs/user-guide.pdf) · [可编辑版本](docs/user-guide.md)
- [保存与迁移清单](docs/保存与迁移清单.md)
- [HF 社区动作和授权说明](docs/community-resources.md)
- [英雄联盟装备数据](https://game.gtimg.cn/images/lol/act/img/js/items/items.js)
- [OP.GG MCP](https://github.com/opgginc/opgg-mcp)

当前整理的装备资料包含 706 条公开装备记录和 173 名英雄索引；游戏版本、模式与分路会影响出装建议。HF 动作使用固定来源版本，第三方动作文件不会直接随本仓库重新分发。
