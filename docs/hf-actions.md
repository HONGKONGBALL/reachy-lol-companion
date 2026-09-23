# Reachy Mini 社区情绪 skills


接入 **8 个社区仓库、34 个开发者预设 skills**，同时保留原有 10 类官方情绪接口
（16 个基础动作）。包括项目级 skill、函数工具 schema、Python 分发器和 CLI。
直接复用开发者录制或生成后保存的轨迹，无需训练模型。

## 社区开发者预设：已接入

| 作者 / 仓库 | 可调用例子 | 收录内容 |
| --- | --- | --- |
| [Anne-Charlotte/new-emotions](https://huggingface.co/datasets/Anne-Charlotte/new-emotions) | `anne.chill`、`anne.surprise`、`anne.waiting` | 放松、惊讶、陪伴、等待等 11 个动作 |
| [stellaaaa/thinking-animations](https://huggingface.co/datasets/stellaaaa/thinking-animations) | `stella.think`、`stella.double_nod` | 思考、天线摆动、点头等 5 个动作 |
| [tfrere/reachy-mini-generated-moves](https://huggingface.co/datasets/tfrere/reachy-mini-generated-moves) | `generated.joy`、`generated.shy_celebrate` | 已生成保存的 10 个情绪动作 |
| [HTurlet15/reachy-alive](https://huggingface.co/datasets/HTurlet15/reachy-alive) | `alive.sneeze`、`alive.hiccup` | 喷嚏、打嗝 |
| [tfrere/reachy-personalities](https://huggingface.co/datasets/tfrere/reachy-personalities) | `personality.change` | 人格切换过渡动作 |
| [apirrone/marionette-moves](https://huggingface.co/datasets/apirrone/marionette-moves) | `apirrone.secret_dance` | 开发者录制的舞蹈 |
| [ShivanshVikram/happy-dance](https://huggingface.co/datasets/ShivanshVikram/happy-dance) | `shivansh.attention`、`shivansh.attention3` | 按实际轨迹收录的两个注意力动作 |
| [Anne-Charlotte/pirate-character](https://huggingface.co/datasets/Anne-Charlotte/pirate-character) | `pirate.laugh`、`pirate.arr` | 海盗角色的笑声和语气动作 |

精确来源、版本、文件路径在 [community.py](../reachy_skills/community.py)。支持根目录和
`data/`、`moves/` 子目录；每个社区预设固定到一个 commit，配套音效可选。
中文情绪标签按文件名或描述整理，尚未实机评估。完整目录执行 `list` 查询。

```bash
# 预演，不联网、不需要 SDK、不连接机器人
python -m reachy_skills play stella.think
python -m reachy_skills play generated.joy
python -m reachy_skills play alive.sneeze --sound

# 安装依赖、预加载社区资源；preload 不连接机器人
python -m pip install -e ".[robot]"
python -m reachy_skills preload --community --sound

# 连接已准备好的机器人，播放指定开发者动作
python -m reachy_skills play stella.think --live --host reachy-mini.local
```

上层 agent 复用同一控制器，工具调用可以是：

```python
from reachy_skills import TOOL_SCHEMAS, ExpressionTools, load_community_library

library = load_community_library(with_audio=False)  # agent 启动前执行一次
# 复用你已有的 ReachyMini 长连接 robot：
tools = ExpressionTools(robot, library, dry_run=False)
# 注册 TOOL_SCHEMAS 后，在 async agent 回调中分发：
result = await tools.call_tool("play_expression_skill", {"skill_id": "stella.think"})
```

按需加载可传 `load_community_library(["stella.think", "generated.joy"])`。
若需要配套音效，加载时传 `with_audio=True`；请求已有但未加载的音轨会返回错误。
同时使用官方库时，用 `CombinedLibrary(RecordedMoves(DATASET), load_community_library())`
作为控制器的 library。两类动作共用互斥和停止处理，重叠调用返回 `busy`。
`list_expression_skills` 中的 `available=False` 表示该动作尚未加载。

本项目提供 5 个工具：`list_expression_skills`、`play_expression_skill`、
`express_emotion`、`stop_expression`、`expression_status`。
更多现成情绪触发、人格、对话及调度应用见 [社区资源说明](community-resources.md)，
文档明确区分已经接入的动作和仅作复用参考的完整应用。

联网校验所有社区文件及固定版本（不连接硬件）：

```bash
python -m reachy_skills.verify_community --report docs/community-validation.json
```

[校验报告](community-validation.json) 记录文件 SHA256、时长和样本数，检查轨迹结构
及音轨存在性，不代表硬件可达性、音频内容或情绪感知效果已经验证。
新增其他开发者预设时，向 `community.py` 的 `SOURCES` / `_PRESETS` 添加仓库版本和
实际文件路径，再运行校验。加载器不限制为官方作者。

## 官方基础动作：兼容原接口

| emotion | 场景 | variant=0 | variant=1 |
| --- | --- | --- | --- |
| listen | 专注倾听 | attentive1 | attentive2 |
| think | 思考、等待结果 | thoughtful1 | thoughtful2 |
| happy | 开心 | cheerful1 | — |
| celebrate | 庆祝、完成任务 | enthusiastic1 | success1 |
| confused | 没理解、需要澄清 | confused1 | — |
| surprised | 惊讶 | surprised1 | surprised2 |
| sad | 难过、失落 | sad1 | downcast1 |
| reassure | 安抚对方 | calming1 | — |
| agree | 理解和同意 | understanding2 | — |
| greet | 打招呼 | welcoming1 | welcoming2 |

这些语义名是本项目的映射。variant 是备选动作，不是物理幅度或情绪强度。

## 官方基础接口快速使用

Python 3.10+，在本项目根目录执行。列举和预演仅使用标准库，不连接机器人、不下载数据：

```bash
python -m reachy_skills list
python -m reachy_skills schema
python -m reachy_skills express happy
python -m reachy_skills express think --variant 1
```

在运行工具的机器上安装 SDK，并提前缓存动作库：

```bash
python -m pip install -e ".[robot]"
python -m reachy_skills preload
```

SDK 最低版本为 1.8.4，以支持当前库的 Ogg/Opus 音效。控制器还会检查
`async_play_move` / `cancel_move` 接口是否存在；不满足时升级 SDK。
首次 preload 需要访问 Hugging Face，后续使用 SDK 的本地缓存。

连接已启动、已准备好执行动作的机器人 daemon：

```bash
python -m reachy_skills express happy --live --host reachy-mini.local
python -m reachy_skills express greet --live --host 192.168.1.42 --sound
```

默认明确使用网络连接；在机器人本机运行时可选 `--connection-mode localhost_only`。
地址需替换成实际主机名或 IP。脚本不会自动启动 daemon 或唤醒机器人。
CLI 是一次性执行；agent 集成应使用下面的长连接方式。

## 官方库的完整 agent 示例（可与社区库合并）

`TOOL_SCHEMAS` 使用常见的 Chat Completions function tool 格式。
其他框架可读取其中的函数名、description 和 JSON Schema 注册工具。
本项目没有绑定某一个 LLM 厂商，也未启动 MCP/HTTP 服务。

```python
import asyncio
import json

from reachy_mini import ReachyMini
from reachy_mini.motion.recorded_move import RecordedMoves
from reachy_skills import DATASET, TOOL_SCHEMAS, ExpressionTools

library = RecordedMoves(DATASET)  # agent 启动前加载一次

async def agent_session(robot):
    tools = ExpressionTools(robot, library, dry_run=False)
    # 将 TOOL_SCHEMAS 注册给上层 agent。
    # 收到函数调用后，解析 arguments，再分发：
    name = "express_emotion"
    arguments = json.loads('{"emotion":"happy","sound":false}')
    result = await tools.call_tool(name, arguments)
    print(result)  # 把结果作为 tool result 返回给 agent

with ReachyMini(host="reachy-mini.local", connection_mode="network") as robot:
    asyncio.run(agent_session(robot))
```

没有机器人时，把控制器替换为 `ExpressionTools()` 即可预演。

接口：

- `list_expression_skills()`：列出动作和变体；加载过库后还会报告动作是否存在。
- `express_emotion(emotion, variant=0, sound=False)`：异步等待动作完成。
- `stop_expression()`：请求停止本控制器当前动作，返回 `stop_requested` 或 `idle`。
- `expression_status()`：查看当前状态。

同一机器人复用一个控制器，全部调用在同一个持久 asyncio 事件循环内完成。
同一时间仅播放一个动作，重叠调用返回 `busy`；本版不排队、不自动抢占。
如需在播放期间停止，应让上层以独立 asyncio task 调用 express，事件循环继续
接收 stop/status。调用 `stop_expression` 后等待原任务退出，再启动下一个动作。
SDK 的初始姿态过渡可能有短暂阻塞，停止并非硬件急停。

```python
playback = asyncio.create_task(tools.call_tool("express_emotion", {"emotion": "think"}))
# 在同一个事件循环中，后续用户打断事件可以执行：
# await tools.call_tool("stop_expression", {})
# result = await playback
```

状态区分：`dry_run` 仅预演；`completed` 为 SDK 播放完成；`stopped` 为已请求停止
且播放函数退出；`busy` 为动作未执行；`error` 为参数、动作缺失或播放错误。
当 TTS 播放时，建议关闭动作音效。已有视线跟随或其他动作进程时，需要上层统一
调度头部控制；本控制器的互斥不覆盖其他实例或进程。

## Hugging Face 来源与扩展

资料核对日期：2026-09-24。

| 资源 | 用途 | 本项目状态 |
| --- | --- | --- |
| [官方情绪库](https://huggingface.co/datasets/pollen-robotics/reachy-mini-emotions-library) | 81 个情绪/社交动作，JSON 轨迹及音效，Apache-2.0 | 已接入其中 10 类语义、16 个动作 |
| [官方舞蹈库](https://huggingface.co/datasets/pollen-robotics/reachy-mini-dances-library) | 19 个纯动作舞蹈，Apache-2.0 | 扩展候选，尚未接入 |
| [官方对话应用 tools](https://huggingface.co/spaces/pollen-robotics/reachy_mini_conversation_app/tree/main/src/reachy_mini_conversation_app/tools) | play_emotion / stop_emotion 等 agent 工具组织参考 | 参考链接，未复制应用代码 |
| [SDK 动作播放示例](https://huggingface.co/docs/reachy_mini/examples/recorded_moves) | RecordedMoves 的加载与播放 | 实现依据 |
| [SDK 控制接口](https://huggingface.co/docs/reachy_mini/en/API/reachymini) | async_play_move、音效开关、cancel_move | 实现依据 |

动作文件由 SDK 按需下载，本仓库不重新分发动作数据。上游 main 可能更新；
`preload` 可检测已选动作是否仍存在，但不是版本锁定或实机验证。

## 验证

```bash
python -m unittest discover -s tests -v
```

测试使用假机器人验证参数约束、动作互斥、停止、取消、失败恢复和工具分发。
预演与测试不代表已经在实际 Reachy Mini 上验证。