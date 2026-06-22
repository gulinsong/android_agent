---
name: post-workout-relax
display_name: 运动后放松
description: 运动结束后根据车内温度调节环境、播放轻缓音乐、语音安抚鼓励
tag: 运动后放松
one_shot: false
trigger:
  type: voice_intent
  intents: [刚打完球, 运动结束了, 锻炼好累, 健身完了, 打开放松模式, 刚跑完步, 刚运动完, 帮我放松一下, 今天的运动结束了, 有点冷帮我调整一下]
execution:
  mode: llm_planned
  instruction: 用户刚运动完需要放松。按以下步骤执行：1. 查询车内温度（get_cabin_temperature），根据温度决策：温度低于20℃则开启空调升温（hvac_power action=set_ac_power on_off=true, hvac_temperature action=set_driver_temp temperature=25）；温度高于28℃则打开车窗通风（set_window position=front_left value=5, set_window position=front_right value=5）；温度适中则保持不变。2. 播放轻缓放松音乐（play_song keyword="轻音乐放松" play_type=play_list），参考 memory 中用户音乐偏好，如有喜欢的轻缓音乐优先播放。3. 语音给予情绪安抚和鼓励，如"辛苦啦，刚刚的运动超棒的～现在好好放松休憩一下，让身体慢慢舒缓下来吧"。
---

## 触发条件

用户说"刚打完球"、"运动结束了"、"锻炼好累"、"帮我放松一下"等运动结束相关表达。

## 执行任务

1. 查询车内温度，根据温度调节空调或开窗通风
2. 播放轻缓放松音乐，优先用户偏好
3. 语音安抚鼓励用户
