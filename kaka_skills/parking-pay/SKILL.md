---
name: parking-pay
display_name: 停车缴费
description: 用户想要停车缴费时，自动查询并显示停车缴费二维码
tag: 停车缴费

trigger:
  type: voice_intent
  intents:
    - 停车缴费
    - 我要缴费
    - 缴停车费
    - 停车场缴费
    - 扫码缴费

execution:
  mode: llm_planned
---
用户想要停车缴费时，显示停车缴费二维码