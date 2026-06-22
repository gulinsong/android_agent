---
name: overspeed-reminder
display_name: 超速提醒
description: 车速超过120km/h时用温柔语气提醒用户注意安全
tag: 超速提醒
one_shot: false
trigger:
  type: event
  event: register_property_listener
  conditions:
    - field: PERF_VEHICLE_SPEED
      op: gt
      value: 120
  cooldown_seconds: 300
execution:
  mode: llm_planned
  instruction: 当前车速已超过120km/h。你用温柔、关切的语气提醒用户注意安全，不要说教或命令式口吻。语气像关心用户的朋友，简短一两句即可，如"现在速度有点快了哦，慢一点也没关系的，安全最重要~"。每次提醒的措辞要有变化，避免重复。不要提及具体车速数值，也不要长篇大论。
---

## 触发条件

车速超过 120 km/h 时触发，冷却时间 5 分钟。

## 执行任务

1. 用温柔、关切的语气提醒用户当前车速偏快
2. 简短提醒注意行车安全，不说教、不命令
