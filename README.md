# Reachy 英雄联盟陪玩助手

在 Windows 上运行的 Reachy Mini 陪玩原型：本体语音、前台游戏窗口观察、主人身份识别、情绪回应、HF 社区动作、英雄出装预加载和本地装备长期记忆。

开始陪玩后，直接喊“默默”或设置的名字就会应声；带问题呼叫则回答问题。主动点评仍等待游戏空隙，直接呼叫不受战斗、画面安全判断、主动发言冷却和“安静陪伴”限制。暂停收听、结束会话或机器人断连时不播放。只喊名字使用本地应答文字，无需等待聊天模型；发声仍需要语音合成服务和本体音频可用。

反应强度点击即提交后端并持久保存，后端确认后才更新选中状态。切换或重选强度会解除“暂停主动回应”；强度卡片下显示后端实际状态。姓名、声线和音量等其他调整仍需点击“保存设置”。

## 前端和后端在哪里

| 项目 | 入口 | 用途 |
| --- | --- | --- |
| 前端 | `http://127.0.0.1:8768/` | 日常操作页面 |
| 后端 | 同一地址的 `/api/…` | FastAPI 服务，不需要另开一个前端服务器 |
| 联调面板 | `http://127.0.0.1:8768/diagnostics` | 开发检查 |
| 机器人控制服务 | `http://127.0.0.1:8000` | Reachy Mini Control 的本地 daemon |
| LOL 对局数据 | `https://127.0.0.1:2999` | 游戏内只读数据，实际对局时才可能可用 |

前端源文件：`reachy_lol/index.html`、`reachy_lol/app.js`；后端入口：`reachy_lol/app.py`；语音、采集与对话调度：`reachy_lol/runtime.py`。

API 带本地 token 和来源校验，直接在新标签打开 `/api/state` 可能返回 403。请通过前端页面使用，不要因此关闭校验。

## 换电脑后的第一次启动

当前版本面向 **Windows 10/11、Python 3.12 64 位、Reachy Mini Lite**。需要联网安装依赖和首次下载动作。

1. 克隆仓库或解压源码 ZIP 到自己的电脑。
2. 安装 Python 3.12，保留 Python Launcher；安装官方 Reachy Mini Control，连接机器人并等其就绪。
3. 双击 `Setup-Companion.cmd`，或在项目目录执行：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
   ```

4. 编辑生成的 `.env`，填自己的模型 API 密钥。模板已保留本次使用的模型、服务地址与声线选择，所有密钥均为空。不要提交 `.env`。
5. 双击 `Start-Companion.cmd`，或执行：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -OpenBrowser
   ```

6. 保持后端窗口打开。进入网页“设备与连接”，点击“连接本体”，重新选择本机音频设备，检查声音，再“开始陪伴”。进入实际对局后选择游戏窗口。

如 8768 已占用，可用 `start.ps1 -Port 8770 -OpenBrowser`。脚本同时设置前后端校验端口。原开发环境曾用 8765、8766、8767，迁移版本统一默认 **8768**。

官方 Reachy Mini Control 已提供 8000 服务时，不要重复运行 `start-robot.ps1`。此脚本只是不用官方控制应用时的替代 daemon 启动方式。启动参数不自动唤醒机器人。

## 已保存的开发成果

- `reachy_lol/`：前端、后端、音频处理、游戏观察、身份与情绪逻辑。
- `reachy_skills/`：8 个 HF 仓库、34 个动作预设的目录、固定版本和工具分发器；与陪玩程序位于同一仓库，不再依赖原电脑外部目录。
- `memory/equipment.json`：706 条公开装备记录、昵称、效果与 173 名英雄索引。数据保存在本地；启动时过期则联网刷新。记录包含不同游戏模式的装备变体。
- `docs/user-guide.pdf`：三页用户指南；`docs/user-guide.md` 是可编辑文字稿。
- `tests/`：游戏调度、身份、对话过滤、知识记忆、动作等自动化测试。
- `tools/`：诊断与开发验证脚本；部分脚本会调用真实云服务、采集游戏画面或操作硬件，运行前阅读文件说明。
- `pyproject.toml`：项目与直接依赖；`requirements.lock.txt`：原开发环境完整版本快照。默认 setup 使用项目依赖，避免强制安装原环境中所有媒体组件。

不会上传 API 密钥、私人会话日志、录音、截图、虚拟环境、GitHub 登录凭据或原电脑的设备绑定。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m reachy_skills list
.\.venv\Scripts\python.exe -m reachy_skills play stella.think
```

最后一条仅预演，不操作硬件。联网验证模型可执行 `python -m tools.verify_companion_knowledge`，会产生供应商调用费用，不会播放语音或控制机器人。

原工作环境测试通过不等于在新电脑完成硬件、驱动和真实对局验收。首次迁移仍需检查本体音频、窗口采集和对局身份。

## 保存与离开公共电脑

按 [开发成果保存清单](docs/保存与迁移清单.md) 操作。至少保留 GitHub 仓库和一份带 SHA256 的离线 ZIP；只有网吧本地副本还不算备份完成。

公开数据源：[国服英雄与装备](https://game.gtimg.cn/images/lol/act/img/js/items/items.js)、[OP.GG 官方 MCP](https://github.com/opgginc/opgg-mcp)、[HF 社区资源](docs/community-resources.md)。第三方动作资源不随源码重新分发，首次运行按固定版本下载。
