---
name: parking-pay-seatbelt
display_name: 系安全带时自动查询停车缴费
description: 主驾系上安全带时，自动查询并显示停车缴费二维码
tag: 系安全带时自动查询停车缴费

trigger:
  type: event
  event: register_property_listener
  conditions:
    - field: SEAT_DRIVER_BELT_BUCKLED
      op: eq
      value: 1
  cooldown_seconds: 10

execution:
  mode: deterministic
  silent: true
  actions:
    - tool: show_parking_qr
---
主驾系上安全带时，自动查询并显示停车缴费二维码