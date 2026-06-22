---
name: cozy-nap
display_name: 惬意午休
description: 开启午休模式，放倒座椅、播放白噪音、恒温空调、设定唤醒提醒
tag: 惬意午休
one_shot: false
trigger:
  type: voice_intent
  intents: [开启午休模式, 我要午休, 我要睡一会, 我想休息一下, 午睡模式, 我睡一会儿, 我睡20分钟, 提前三分钟把我叫醒]
execution:
  mode: llm_planned
  instruction: 用户要午休。按以下步骤执行：1. 开启空调并设置为26℃恒温（hvac_power action=set_ac_power on_off=true, hvac_temperature action=set_driver_temp temperature=26）。2. 播放用户偏好的白噪音（play_song keyword="白噪音雨声"，参考 memory 中偏好，如用户喜欢雨声则 keyword="雨声白噪音"）。3. 确认午休时长（默认20分钟）和提前唤醒时间（默认3分钟）。4. 用技能创建工具创建一次性唤醒技能 nap-wakeup（cron, delay 为午休时长减去提前唤醒时间的分钟数，如默认 "17m", one_shot: true），执行内容（llm_planned）：播放轻音乐（play_song keyword="轻音乐"）、语音温和唤醒用户（如"该起床啦，短暂的休憩是为了更好地出发，下午也要加油哦"）。5. 告知用户午休环境已就绪，祝好梦。
---

## 触发条件

用户说"开启午休模式"、"我要午休"、"我睡一会儿"等。

## 执行任务

1. 开启空调，设置为 26℃ 恒温
2. 播放用户偏好的白噪音
3. 确认午休时长和提前唤醒时间
4. 创建唤醒提醒技能：到时间后播放轻音乐并语音唤醒
5. 告知用户午休环境已就绪
