---
name: wb-buddy-gas-checkin
display_name: Buddy 加油站签到（浏览器通道）
display_name_en: Buddy Gas Station Check-in (Browser Channel)
description: "WorkBuddy『Buddy 加油站』每日积分签到（每日+100 积分）的浏览器页面上下文实现。与官方 WBIPC 通道不同，本技能通过 Playwright 启动真实浏览器、注入登录态 Cookie，在页面上下文中调用 /v2/billing/meter/daily-checkin 接口，可在云端 CI（GitHub Actions）运行、电脑不开机也能自动领。含派猫猫旅行自动化。当用户说『签到』『领100积分』『Buddy 加油站』『自动领积分』且希望云端/不开机运行时使用。"
description_zh: "WorkBuddy「Buddy 加油站」每日积分的浏览器通道签到方案。经 Playwright 启动浏览器、注入登录态后在页面上下文调用接口，不依赖桌面客户端是否开机。可在 GitHub Actions 等云端运行。附带派猫猫旅行自动化。适用于希望『电脑不开机也能每天自动领 100 积分』的场景。"
description_en: "Browser-context daily check-in for WorkBuddy Buddy Gas Station (+100 credits/day). Unlike the official WBIPC skill, this launches a real browser via Playwright, injects login-state cookies, and calls the check-in API inside the page context — so it runs on cloud CI (GitHub Actions) even when the PC is off. Includes cat-travel automation. For users who want unattended daily crediting."
category: productivity
author: auto-generated
version: 1.0.0
last_updated: 2026-10-14 11:40
changelog: "v1.0.0 首版：封装已验证可用的浏览器通道签到方案（接口 + 脚本 + 云端部署模板）"
examples_zh:
  - 帮我签到领今天的 100 积分
  - 生成一个能云端自动签到的技能
  - 电脑不开机怎么每天领加油站积分
examples_en:
  - check in and claim today's 100 credits for me
  - make a skill that auto checks-in on the cloud
agent_created: true
---

# Buddy 加油站签到（浏览器通道）

经 **Playwright 真实浏览器 + 注入登录态 Cookie**，在页面上下文中调用 WorkBuddy 官方签到接口完成每日积分领取。
与官方 `buddy-checkin` 技能的 WBIPC 通道不同，本方案**不要求桌面客户端在线**，因此可在云端 CI（如 GitHub Actions）运行，实现「电脑不开机也能每天自动领 100 积分」。

## 关键事实（已实测验证）

- 「Buddy 加油站」是 WorkBuddy **客户端左下角账号入口**里的功能，网页版成长中心看不到它，但它背后的接口是通用的 Web 接口。
- 该接口属于 `/v2/billing/meter/` 域，**与成长中心的 `/activity/growth/` 是两套独立系统**（之前一直查错方向的根因）。
- **纯 HTTP 请求会被 APISIX 网关返回 401 拦截**，必须在浏览器页面上下文内（`fetch(..., {credentials:'include'})`）调用才有效。
- 登录态关键在于 Keycloak 系 Cookie（如 `KEYCLOAK_SESSION`、`session`、`session_2` 等），需整体导出为 `WB_STATE`。

## 核心接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | `/v2/billing/meter/checkin-activity-status` | 查状态：`active`(活动是否开)、`today_checked_in`(今日是否已签)、`streak_days`(连签天数) |
| POST | `/v2/billing/meter/daily-checkin` | **领每日 100 积分**（幂等：`code=10001` 表示今日已签，等同成功，返回 `data.credit=100`） |

返回示例（成功）：
```json
{ "code": 0, "data": { "credit": 100, "streak_days": 15 } }
```

连签档位奖励（7/14/28 天）需在成长中心页面手动兑换，本技能不自动触碰，避免误操作。

## 快速开始（本地）

```bash
# 1) 准备登录态：把从浏览器导出的 Cookie 存为 wb_state.json（见下文）
# 2) 运行签到（默认仅加油站签到）
python scripts/checkin.py

# 同时派猫猫旅行
python scripts/checkin.py --mode both

# 仅派猫猫
python scripts/checkin.py --mode cat

# 配置微信通知（方糖 Server酱 SendKey）
SERVERCHAN_KEY=xxxx python scripts/checkin.py
```

依赖：Python 3 + `playwright`（已在本机托管环境安装）。Windows 可用 WorkBuddy 自带 Python
（`~/.workbuddy/binaries/python/`）。脚本自动在 Windows 用 `msedge` 通道、Linux 用 `chromium`。

## 登录态（WB_STATE）准备

浏览器通道必须带有效登录态。获取方式（一次性）：

1. 用 Playwright/手动打开 `https://www.workbuddy.cn/` 并扫码登录。
2. 登录后导出全部 Cookie（含 Keycloak 系）为 JSON 数组。
3. 存入环境变量 `WB_STATE`（JSON 字符串），或同目录 `wb_state.json` 文件。

> 注意：浏览器 Cookie 有有效期，登录态失效后需在客户端重新登录并重新导出。
> 敏感文件 `wb_state.json` 切勿提交到公开仓库。

## 云端自动运行（GitHub Actions，不开机）

`scripts/github-workflow.yml` 是一个可直接用的模板，包含：

- 每天北京时间 **9:00** 执行「领积分」（加油站签到 + 猫猫旅行奖励）
- 每天 **9:05 / 14:05** 执行「派猫猫」
- 通过 `WB_STATE`、`SERVERCHAN_KEY` 两个 Secrets 注入凭证
- 运行结果推送至微信（Server酱）

部署步骤：

1. 建私有仓库，把 `scripts/checkin.py` 放根目录，`scripts/github-workflow.yml` 改名为 `.github/workflows/daily.yml`。
2. 仓库 Settings → Secrets 添加 `WB_STATE`（Cookie JSON）与 `SERVERCHAN_KEY`。
3. 启用 Actions。之后每天自动运行，无需电脑开机。

## 脚本行为说明

- **幂等**：今日已签时 `daily-checkin` 返回 `code=10001`，脚本按「今日已签」正常处理，重复运行无副作用。
- **复核**：领取后脚本会再查一次状态确认 `today_checked_in=true`，防止「假成功」。
- **容错**：登录态失效会截图并推送告警（exit 2）；接口异常不会谎报成功。

## 与官方 buddy-checkin 技能的区别

| 维度 | 官方 buddy-checkin | 本技能 wb-buddy-gas-checkin |
| --- | --- | --- |
| 通道 | 桌面客户端 WBIPC | Playwright 浏览器页面上下文 |
| 要求 | 电脑开机 + 客户端在线 | 任意能跑浏览器的环境（含云端 CI） |
| 不开机可用 | 否 | **是**（GitHub Actions 等） |
| 适用 | 本机每日定时/开机补签 | 云端无人值守自动领 |

两套可并存，按场景选择。

## 安全约定

- 不读取/解密桌面客户端本地加密登录令牌；只使用用户主动导出的 Cookie。
- `wb_state.json` 含登录凭证，禁止提交到公开仓库或分享给他人。
- 网络访问仅限 WorkBuddy 官方接口。
