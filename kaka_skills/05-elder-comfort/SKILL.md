---
name: elder-comfort
display_name: 长辈舒适行
description: 带父母出行时调整车辆为最舒适模式，启动后排座椅加热，规划出行路线
tag: 长辈舒适行
one_shot: false
trigger:
  type: voice_intent
  intents: [带父母出门, 带爸妈出去, 接父母, 带父母出去玩, 把车调成适合父母的模式, 父母要坐车, 带爸妈出去玩, 一会儿带父母出门]
execution:
  mode: llm_planned
  instruction: 用户要带父母出行。按以下步骤执行：1. 调整后排座椅环境：启动后排左右座椅加热（set_seat_heat position=rear_left level=2, set_seat_heat position=rear_right level=2），告知用户已调整为舒适模式。2. 如用户提及出行目的地，使用 text_search_poi 搜索并规划导航路线（plan_route_then_start_navigation），播报路况和预计时间，询问是否出发。3. 询问父母会坐在哪些位置（副驾/左后/中后/右后），记住用户回答。4. 用技能创建工具创建一次性座椅传感技能 parent-aboard-sensor（event: register_property_listener, conditions: 根据用户回答的父母座位位置选择对应安全带字段——副驾用 SEAT_PSNGR_BELT_BUCKLED eq 1，左后用 SEAT_RL_BELT_BUCKLED eq 1，中后用 SEAT_RC_BELT_BUCKLED eq 1，右后用 SEAT_RR_BELT_BUCKLED eq 1, one_shot: true, cooldown_seconds: 60），触发后执行：亲切语音问候父母、获取并播报路况（get_navigation_status）、调整空调出风口避开头部吹脚部（hvac_fan action=set_blow_direction blow_direction=foot）。
---

## 触发条件

用户提及带父母/长辈出行，如"带父母出门"、"一会儿带爸妈出去玩"等。

## 执行任务

1. 启动后排座椅加热，调整车辆为舒适模式
2. 如有目的地，规划导航路线并播报路况
3. 询问父母会坐在哪些位置（副驾/左后/中后/右后）
4. 创建座椅传感技能：对应座位安全带系上时触发问候、播报路况、调整空调出风口
