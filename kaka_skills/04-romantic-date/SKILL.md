---
name: romantic-date
display_name: 浪漫约会大作战
description: 规划约会行程、导航至活动地点，设置浪漫氛围欢迎约会对象上车
tag: 浪漫约会大作战
one_shot: false
trigger:
  type: voice_intent
  intents: [今天约会, 我要去约会, 和女朋友约会, 和男朋友约会, 一起去约会, 我一会儿接她出去玩, 我今天要去约会]
execution:
  mode: llm_planned
  instruction: 用户要去约会。按以下步骤执行：1. 确认约会活动：若用户已提及活动内容（如火锅、剧本杀、博物馆），确认即可；若未提及，根据用户描述搜索推荐活动（web_search），让用户选择。2. 确认活动地点：若用户已提及地点，用 text_search_poi 搜索确认；若未提及，根据活动内容搜索附近相关地点（text_search_poi），推荐给用户。3. 询问是否需要添加途经点（如先接约会对象、买花等），若需要则搜索对应地点。4. 以活动地点为目的地规划导航路线（plan_route_then_start_navigation，途经点按需添加）。5. 获取并播报路况（get_navigation_status），询问是否现在出发。6. 询问约会对象的称呼和音乐偏好。7. 询问约会对象会从哪个车门上车（副驾/左后/右后）。8. 用技能创建工具创建一次性欢迎技能 date-welcome（event: register_property_listener, conditions: 根据用户回答的车门选择对应字段——副驾用 DOOR_FR_STATUS eq 1，左后用 DOOR_RL_STATUS eq 1，右后用 DOOR_RR_STATUS eq 1, one_shot: true, cooldown_seconds: 60），执行内容：用自定义称呼语音欢迎（如"欢迎漂亮小姐落座，一路温馨相伴"）、开启氛围灯浪漫色调（set_ambient_light action=switch value=2, set_ambient_light action=color value=17）、播放浪漫音乐（play_song keyword=用户偏好或"浪漫情歌"）。
---

## 触发条件

用户提及约会相关话题，如"今天约会"、"和女朋友出去玩"等。

## 执行任务

1. 确认约会活动内容，必要时搜索推荐
2. 确认活动地点，搜索推荐
3. 询问是否需要添加途经点
4. 规划导航路线，播报路况
5. 确认约会对象称呼和音乐偏好
6. 询问约会对象会从哪个车门上车
7. 创建车门触发欢迎技能：对应车门打开时，语音欢迎、调浪漫氛围灯、播放浪漫音乐
