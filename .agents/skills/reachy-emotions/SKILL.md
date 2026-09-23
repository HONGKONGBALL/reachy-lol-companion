---
name: reachy-emotions
description: 使用 Hugging Face 社区开发者的情绪、思考、陪伴和角色动作预设控制 Reachy Mini，并将这些 skills 接入上层 agent。
---

# Reachy Mini 情绪表达

本项目在 `reachy_skills/expressions.py` 提供工具实现。先读项目根目录的
[README](../../../README.md) 获取安装和 agent 接入方式。

- 用 `list_expression_skills` 查询 `community_skills`，按情绪、动作描述和来源选择
  开发者预设。8 个社区仓库的目录位于 `reachy_skills/community.py`，无需局限于官方库。
- 调用 `play_expression_skill(skill_id, sound=False)` 播放社区动作。例如
  `stella.think` 表达思考，`generated.joy` 表达喜悦，`anne.chill` 表达放松，
  `alive.sneeze` 增加拟生命感。中文语义按文件名或描述整理，尚未实机评估效果。
- 运行 agent 前用 `load_community_library()` 预加载社区轨迹，若需音效传入
  `with_audio=True`。用 `CombinedLibrary` 与现有官方 `RecordedMoves` 合并。
  `available=False` 表示未加载该动作，不要把目录收录等同于可执行。
- 调用 `express_emotion(emotion, variant=0, sound=False)` 表达一次情绪。
  `variant` 是备选动作的下标，不表示强度，也不修改电机角度。
- 官方语义接口 `express_emotion` 保留兼容性。根据上下文选合适的社区或官方动作，
  不必每句话都动。
- 与 TTS 一起使用时通常保持 `sound=False`，避免动作音效盖住语音。
- 同一机器人复用一个 `ExpressionTools` 实例和同一个 asyncio 事件循环。
  两种播放工具都等待播放结束、共用动作互斥；返回 `busy` 时不要密集重试或堆积过时动作。
- `stop_expression` 请求停止；调用 `expression_status` 确认控制器重新空闲。
  它只管理此实例的动作，不是机器人急停，也不能停止其他进程的控制。
- 预演返回 `dry_run`，不能向用户声称机器人已经动作；只有实机调用返回
  `completed` 才表示 SDK 播放完成，仍不代表视觉或硬件反馈验证。
- CLI 的 `python -m reachy_skills play stella.think` 默认只预演；连接已运行的
  daemon 执行动作时使用 `--live --host <机器人地址>`。无须下载模型权重。

社区应用和可复用模块见 [社区资源说明](../../../docs/community-resources.md)，其中标注
「应用参考」的内容尚未接入本控制器，不要声称已经安装或可以直接调用。
此 skill 本身不提供 MCP 服务；上层系统可直接
注册 `TOOL_SCHEMAS`，并把函数调用分发给 `ExpressionTools.call_tool`。
