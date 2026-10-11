# WorkBuddy 每日签到 + 派猫猫旅行

每天自动完成 WorkBuddy「Buddy 加油站」签到领积分和派猫猫旅行，结果推送到飞书。

## 功能说明

- **签到**：查询今日签到状态，未签到则自动执行，幂等安全
- **派猫猫旅行**：先领取已到家的旅行奖励，再派出新旅行（每天仅限一次）
- **飞书推送**：将签到和旅行结果分别推送到飞书群

## 接口说明（已验证）

| 功能 | 方法 | 地址 |
|------|------|------|
| 签到状态 | POST | https://www.codebuddy.cn/v2/billing/meter/checkin-activity-status |
| 执行签到 | POST | https://www.codebuddy.cn/v2/billing/meter/daily-checkin |
| 旅行状态 | GET | https://www.workbuddy.cn/activity/growth/buddy/travel/status |
| 旅行领取 | POST | https://www.workbuddy.cn/activity/growth/buddy/travel/claim |
| 旅行派出 | POST | https://www.workbuddy.cn/activity/growth/buddy/travel/depart |

## 部署步骤

### 1. 获取登录凭证

**从浏览器获取 accessToken（推荐）**

1. 打开 WorkBuddy 客户端
2. 按 F12 打开开发者工具
3. 切换到 Network 标签
4. 刷新页面或执行任意操作
5. 找到请求 https://www.codebuddy.cn 的请求
6. 查看 Request Headers 中的 `Authorization: Bearer <token>`
7. 复制 token 值

**运行本地脚本获取 uid**

```bash
python export_tokens.py
```

> ⚠️ **安全提醒**：accessToken 等同于登录密码，请勿提交到仓库或公开场合。

### 2. 配置 GitHub Secrets

仓库页面 → Settings → Secrets and variables → Actions → New repository secret

| Secret 名称 | 必填 | 说明 |
|------------|------|------|
| `WORKBUDDY_ACCESS_TOKEN` | ✅ | 从浏览器复制的明文 token |
| `WORKBUDDY_USER_ID` | ✅ | 从 export_tokens.py 获取的 uid |
| `FEISHU_WEBHOOK` | ✅ | 飞书群机器人 Webhook 地址 |
| `FEISHU_WEBHOOK_SIGN` | 可选 | 飞书签名密钥 |

### 3. 飞书群机器人配置

1. 打开飞书群 → 设置 → 群机器人 → 添加机器人 → 自定义机器人
2. 复制 Webhook 地址

## 运行时间

默认北京时间每天 **上午 10:00** 执行（UTC 02:00）

如需调整，编辑 `.github/workflows/daily.yml` 中的 cron 字段。

## 执行逻辑

```
查询签到状态
  ├─ 已签到 → 跳过
  └─ 未签到 → 执行签到

查询旅行状态
  ├─ 今日已满 → 跳过
  ├─ 旅行中 → 等待
  ├─ 已到达 → 领取奖励 → 派出新旅行
  └─ 空闲 → 派出新旅行
```

## 安全设计

- accessToken 仅存于 GitHub Secrets，代码中通过环境变量读取
- 日志中脱敏显示 token（仅展示前 8 位）
- 不存储本地登录态文件
- 使用 HTTPS 加密传输
- 飞书推送失败不影响主流程
