---
name: counting-stars
display_name: 数星星
description: 开启观星模式，启动座椅加热、打开车窗、熄灭灯光、播放氛围音乐
tag: 数星星
one_shot: false
trigger:
  type: voice_intent
  intents: [我想看星星, 观星模式, 躺在车里看星星, 帮我布置观星, 今晚星星很不错, 看星星]
execution:
  mode: llm_planned
  instruction: 用户想在车内看星星。按以下步骤执行：1. 启动座椅加热（set_seat_heat position=driver level=2），若有其他乘客也启动对应座椅加热。2. 打开车窗让用户能看到星空（set_window position=front_left value=10, set_window position=front_right value=10）。3. 关闭氛围灯减少车内光源干扰（set_ambient_light action=switch value=1）。4. 播放氛围感音乐（play_song keyword="星空氛围轻音乐" play_type=play_list）。5. 告知用户观星环境已准备好，享受星空。
---

## 触发条件

用户说"我想看星星"、"躺在车里看星星"、"帮我布置观星"等。

## 执行任务

1. 启动座椅加热
2. 打开车窗
3. 关闭车内灯光，减少光源干扰
4. 播放氛围感音乐
5. 告知用户观星环境已就绪
