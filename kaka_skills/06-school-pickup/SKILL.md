---
name: school-pickup
display_name: 宝贝放学接驾
description: 用户提及接孩子放学时，规划导航路线，准备车内环境，迎接孩子上车
tag: 宝贝放学接驾
one_shot: false
trigger:
  type: voice_intent
  intents: [我要去接孩子, 一会儿接孩子, 去接宝贝放学, 接孩子放学, 去学校接孩子, 该接孩子了, 要去接娃]
execution:
  mode: llm_planned
  instruction: 用户要接孩子放学。按以下步骤执行：1. 搜索学校位置（参考 memory，无则询问用户），规划导航路线，播报预计时间和路况，询问是否出发；用户确认后发起导航。2. 询问孩子会坐哪个位置（副驾/左后/中后/右后），记住用户回答的座位位置。3. 用技能创建工具创建一次性技能 school-pickup-arrival-prep（event: register_navi_listener, conditions: REMAIN_TIME lte 600, one_shot: true, cooldown_seconds: 300），到达前约10分钟时启动对应位置座椅加热（set_seat_heat），语音提醒"马上就要接到宝贝了哦"并告知用户已准备就绪。4. 用 write_skill 创建一次性座椅传感技能 school-pickup-child-sensor（event: register_property_listener, conditions: 根据用户回答的座位位置选择对应安全带字段——副驾用 SEAT_PSNGR_BELT_BUCKLED eq 1，左后用 SEAT_RL_BELT_BUCKLED eq 1，中后用 SEAT_RC_BELT_BUCKLED eq 1，右后用 SEAT_RR_BELT_BUCKLED eq 1, one_shot: true, cooldown_seconds: 60），触发后欢快语音问候孩子（如"小宝贝回来啦，我们准备回家咯～"）。
---

## 触发条件

用户主动提及接孩子放学，如"一会儿我要去接孩子"、"去学校接孩子"等。

## 执行任务

1. 搜索孩子学校位置，规划导航路线
2. 播报预计行驶时间与路况，询问是否出发，确认后发起导航
3. 询问孩子会坐在哪个位置（副驾/左后/中后/右后）
4. 创建到达前准备技能：距目的地约 10 分钟时，启动座椅加热并提醒用户
5. 创建孩子上车座椅传感技能：对应座位安全带系上时触发语音问候
