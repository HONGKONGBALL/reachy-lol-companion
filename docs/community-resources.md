# Reachy Mini 社区资源与接入状态

核对日期：2026-09-24。搜索覆盖 HF 的 `reachy_mini_community_moves` 标签和相关
Spaces，并读取候选仓库文件清单与源码。按情绪表达用途、具体轨迹格式和调用方式选取。

## 已接入：开发者预设动作

8 个社区仓库的 34 个动作见 [README 社区目录](../README.md) 和
[注册表](../reachy_skills/community.py)。这些是真正通过 `play_expression_skill` 接入
执行器的动作；上游文件保留原始轨迹，本项目只做来源索引与语义映射。

8 个仓库在所选版本的数据卡中均标记 Apache-2.0。精确 commit 在注册表中，结构校验
结果在 [报告](community-validation.json)。中文情绪标签按文件名或描述整理，尚未实机评估。
生成库只取标准 recorded-move `.json`；`.clip.json`、`.meta.json`、`.thread.json`
不是可直接交给 RecordedMove 的轨迹。加载动作不需要安装整套对话应用。

实际检查发现 `ShivanshVikram/happy-dance` 的 `attention-1` 和 `attention-2`
标有 `audio_only` 且 `set_target_data` 为空，已经排除。接入的是有轨迹的
`attention` 和 `attention-3`，没有把音频预设伪装成机器人动作。

## 社区现成应用：复用参考，未安装整套应用

这些项目已经实现情绪触发或 agent 工具调用，适合复用行为策略。部分底层使用官方
轨迹，但提供了开发者自己的触发和调度逻辑。以下应用未注册成本项目的可执行 skill ID。

| 项目 | 已核对的现成功能 / 源码入口 | 如何用于已有上层 agent |
| --- | --- | --- |
| [mindmodelai/reachy-mini-elevenlabs](https://huggingface.co/spaces/mindmodelai/reachy-mini-elevenlabs) | [EmotionDetector](https://huggingface.co/spaces/mindmodelai/reachy-mini-elevenlabs/blob/5e586369c6d18d86c2ca1f0f86d73ede199035c0/reachy_mini_elevenlabs/emotion_detector.py) 提供文本模式匹配、置信度门槛、动作冷却和 `analyze_and_act` | 适合从 agent 回复中自动触发表达。整套应用需要 ElevenLabs agent；抽取策略需适配执行器，并补充中文关键词 |
| [8bitkick/reachy_mini_reactions](https://huggingface.co/spaces/8bitkick/reachy_mini_reactions) | [Animation](https://huggingface.co/spaces/8bitkick/reachy_mini_reactions/blob/7636771cbd7f4669aa9a9e9fd87fedc70c0c740e/reachy_mini_reactions/tools/animation.py) 有 `play_from_text`、`start`、`stop`；该模块加载官方 RecordedMoves | 适合文本响应驱动身体反馈；需适配动画线程和音频依赖，不是即插即用的 MCP 包 |
| [johannwest/chappie-robot](https://huggingface.co/spaces/johannwest/chappie-robot) | [emotions.py](https://huggingface.co/spaces/johannwest/chappie-robot/blob/4f33f27a8450e2b0ff4d3f48b2d63f672ebbe8ca/src/chappie_robot/emotions.py) 提供情绪意图解析、动作别名、`EmotionQueueMove` 队列封装；README 描述 OpenClaw 集成 | 上层是 OpenClaw 时可评估整套具身应用；只需要动作时可复用其解析和调度模式。完整应用需要 gateway 和语音服务配置 |
| [Enricx/reachy_mini_gpt_live](https://huggingface.co/spaces/Enricx/reachy_mini_gpt_live) | [工具源码](https://huggingface.co/spaces/Enricx/reachy_mini_gpt_live/blob/26d9b2327fd0b31071e0615964acdd593393f907/reachy_mini_gpt_live/tools.py) 与 README 描述情绪、舞蹈、视线和人格 profile 调用 | 适合实时语音 agent；整套应用有其语音服务和 SDK 版本依赖，不能仅复制工具名就执行 |

本次未复制这些应用源码，也未配置外部服务凭证；接入的是上面的社区动作数据。

## 其他已发现的资源

- [Anne-Charlotte/reachy-songs](https://huggingface.co/datasets/Anne-Charlotte/reachy-songs)：歌曲配套动作，适合表演扩展，当前未接入。
- [tfrere/reachy-mini-moves](https://huggingface.co/datasets/tfrere/reachy-mini-moves)：存在 `curious-nod` 和 Blender timeline 示例；本次所读数据卡没有 license 字段，登记为候选，未复制或接入。
- [RemiFabre/secret-handshake](https://huggingface.co/datasets/RemiFabre/secret-handshake)：目录包含 collision 测试及 default 命名文件，不能仅凭仓库名断言是可用问候 skill，当前未接入。
- [社区动作标签入口](https://huggingface.co/datasets?other=reachy_mini_community_moves)：继续发现开发者预设。核对具体文件，避免把 Reachy 2 数据、训练集或对话应用误当作 Reachy Mini 可播放轨迹。
