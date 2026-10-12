# WorkBuddy 每日签到 + 派猫猫旅行（云端自动版）

每天**北京时间 10:00** 自动完成 WorkBuddy「Buddy 加油站」签到领积分 + 派猫猫旅行，
结果推送到**微信**（方糖 Server酱，零安装）。

运行环境：GitHub Actions 免费定时任务，云端 runner 执行，不需要你电脑常开。

---

## 设计要点（对应你的要求）

1. **每天定时一次**：`cron: '0 2 * * *'`（UTC 02:00 = 北京 10:00），一次跑完签到 + 旅行。
2. **旅行逻辑**：先领已到家的奖励 → 再判能不能派新一趟 → 今天派过就跳过（接口返回 `daily_limit_reached` 即停）。
3. **微信分开推送**：签到和旅行状态分两段写清楚。
4. **旅行失败不影响签到**：各自独立 try，签到成功就算成功，退出码只看签到。
5. **安全**：token 从 `WORKBUDDY_ACCESS_TOKEN` secret 读取，日志里只显示前 8 位，明文不进仓库/不进日志。
6. **解释器**：workflow 里用 `command -v python` 动态取，不写死版本号。
7. **接口以实际为准**：下面 4 个接口地址是「占位」，必须抓你浏览器里的真实 URL 填（见下）。

---

## 你需要做的两件事（都是点一下）

> token 被 WorkBuddy 用本机 Windows 凭证加密锁死，脚本抠不出来，所以必须你本人从浏览器取一次。

### A. 取 token + 抓真实接口（一次，在 Chrome/Edge 里）
1. 用 **Chrome 或 Edge** 打开 WorkBuddy 网页版并登录。
2. 新开一个标签页打开 https://sct.ftqq.com/ ，用**微信扫码**登录，复制页面上的 **SendKey**。
3. 回到 WorkBuddy 页面，按 **F12** → 点 **Network（网络）**。
4. 做**签到**动作 → 在网络列表里找一个发给 `codebuddy.cn` / `workbuddy` 的请求：
   - 右键 → Copy → **Copy URL**（这就是签到接口，给我）
   - 看 **Headers（标头）** → `Authorization: Bearer xxxxx`，复制整段 `xxxxx`（这就是 token，给我）
5. 做**派猫猫旅行**动作 → 同样复制那个请求的 **Copy URL**（给我）。
6. 把「SendKey、token、签到 URL、旅行 URL」一起发给我。

### B. 我替你收尾
收到后我会：
- 把 4 个接口地址写进代码；
- 通过 GitHub API 把 `WORKBUDDY_ACCESS_TOKEN`、`WORKBUDDY_USER_ID`、`SERVERCHAN_KEY` 配进仓库 Secrets；
- 手动触发一次验证，然后每天 10:00 自动跑。

---

## 仓库 Secrets（我配好后会自动填，你也可以自己看）

| Secret | 说明 |
|--------|------|
| `WORKBUDDY_ACCESS_TOKEN` | 你的 token（A.4 复制的） |
| `WORKBUDDY_USER_ID` | 你的 uid（已确认：`57dfb65f-4707-445a-8fc2-06c866913e7f`） |
| `SERVERCHAN_KEY` | 方糖 SendKey（A.2 复制的） |
| `WB_CHECKIN_STATUS_URL` 等 4 个 | 真实接口地址（A.4/A.5 抓的，可选，不填就由我写进代码） |

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `workbuddy_daily.py` | 主脚本：签到 + 旅行 + 微信推送（仅标准库） |
| `.github/workflows/daily.yml` | GitHub Actions 定时任务 |
| `export_tokens.py` | 早期尝试的本地导出脚本（当前不需要） |
