---
name: entertainment-immersive
display_name: 影音游戏沉浸享
description: 开启观影或游戏沉浸模式，关闭车窗、熄灭灯光、调整座椅舒适度
tag: 影音游戏沉浸享
one_shot: false
trigger:
  type: voice_intent
  intents: [我要看电影, 我要打游戏, 进入观影模式, 进入游戏模式, 我要在车里看视频, 在车里放松玩会儿, 看会儿视频, 观影模式, 游戏模式]
execution:
  mode: llm_planned
  instruction: 用户想在车内看电影或打游戏。按以下步骤执行：1. 确认用户需求是观影还是游戏。2. 关闭所有车窗（set_window position=front_left value=11, set_window position=front_right value=11, set_window position=rear_left value=11, set_window position=rear_right value=11）。3. 关闭氛围灯减少视觉干扰（set_ambient_light action=switch value=1）。4. 启动座椅加热提升舒适度（set_seat_heat position=driver level=2）。5. 告知用户沉浸环境已准备好，尽情享受。
---

## 触发条件

用户说"我要看电影"、"进入游戏模式"、"在车里看视频"等。

## 执行任务

1. 确认用户需求（观影/游戏）
2. 关闭车窗
3. 熄灭车内灯光
4. 启动座椅舒适模式
5. 告知用户沉浸环境已就绪
