"""
WorkBuddy 成长中心云端自动化：每日签到打卡 + 派猫猫旅行
- 从环境变量 WB_STATE（JSON cookie）或 wb_state.json 读取登录态
- 注入浏览器后，在页面上下文中调用接口（纯 HTTP 会被 APISIX 网关 401 拦截）
- 结果通过 Server酱推送到微信
"""
import json, os, sys, argparse, urllib.request, urllib.parse, datetime

BASE = "https://www.workbuddy.cn"
PAGE = BASE + "/profile/growth-center"

JS_SCRIPT = r"""
async () => {
  const out = {};
  const req = async (method, path, body) => {
    try {
      const opt = {method, credentials:'include', headers:{'Content-Type':'application/json'}};
      if (body !== undefined && body !== null) opt.body = JSON.stringify(body);
      const r = await fetch(path, opt);
      const t = await r.text();
      let j = null; try { j = JSON.parse(t); } catch(e) {}
      return {status:r.status, json:j, raw:t.slice(0,300)};
    } catch(e) { return {error:String(e)}; }
  };

  out.profile = await req('GET','/v2/activity/growth/profile');
  out.streak = await req('GET','/activity/growth/streak');
  out.energy = await req('GET','/activity/growth/energy');
  out.heatmap = await req('GET','/activity/growth/heatmap');
  out.travel_status = await req('GET','/activity/growth/buddy/travel/status');
  out.travel_config = await req('GET','/activity/growth/buddy/travel/config');

  // 今天日期（Asia/Shanghai）
  const now = new Date();
  const sh = new Date(now.getTime() + (8*60 + now.getTimezoneOffset())*60000);
  const todayStr = sh.toISOString().slice(0,10);
  out.today = todayStr;
  let checked=false;
  try {
    const cells = out.heatmap.json?.data?.cells || [];
    const cell = cells.find(c => c.date === todayStr);
    out.today_cell = cell || null;
    checked = !!(cell && ((cell.score||0)>0 || cell.has_new_buddy));
  } catch(e){}
  out.checked_in = checked;

  // 先领奖，再判断是否派新猫
  const ts = out.travel_status.json?.data || {};
  out.travel_state_before = ts.state;
  out.daily_limit_before = !!ts.daily_limit_reached;
  out.buddy_name = '';

  if (ts.state === 'traveling' || ts.state === 'arrived') {
    out.claim = await req('POST','/activity/growth/buddy/travel/claim', {});
  } else {
    out.claim = {skipped:'no pending travel'};
  }

  out.travel_status2 = await req('GET','/activity/growth/buddy/travel/status');
  const ts2 = out.travel_status2.json?.data || {};

  if (ts2.state === 'idle' && !ts2.daily_limit_reached) {
    let locs = out.travel_config.json?.data?.locations || [];
    locs = locs.slice().sort((a,b)=>((b.reward_credit_max||0)-(a.reward_credit_max||0))||((a.duration_hours_min||0)-(b.duration_hours_min||0)));
    if (locs.length) {
      out.depart_location = locs[0];
      out.depart = await req('POST','/activity/growth/buddy/travel/depart', {location_id: locs[0].id});
    } else { out.depart = {error:'no locations'}; }
  } else {
    out.depart = {skipped:'state='+ts2.state+' daily_limit='+!!ts2.daily_limit_reached};
  }

  out.travel_status3 = await req('GET','/activity/growth/buddy/travel/status');
  out.energy_after = await req('GET','/activity/growth/energy');
  out.streak_after = await req('GET','/activity/growth/streak');
  out.buddy_info = await req('GET','/activity/growth/buddy/info');
  return out;
}
"""


def push_serverchan(title, desp, key):
    if not key:
        print("[!] 未配置 SERVERCHAN_KEY")
        return
    try:
        data = urllib.parse.urlencode({"title": title, "desp": desp}).encode()
        req = urllib.request.Request(
            f"https://sctapi.ftqq.com/{key}.send", data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=20) as r:
            print("[push]", r.status, r.read().decode("utf-8", "ignore")[:100])
    except Exception as e:
        print("[!] 推送失败:", e)


def load_state():
    raw = os.environ.get("WB_STATE", "").strip()
    if raw:
        return json.loads(raw)
    for p in ("wb_state.json", "/tmp/wb_state.json"):
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
    raise SystemExit("[!] 找不到登录态：请设置 WB_STATE 或提供 wb_state.json")


def to_pw(cookies):
    out = []
    for c in cookies:
        d = {"name": c["name"], "value": c["value"],
             "domain": c["domain"], "path": c.get("path", "/")}
        if c.get("expires", -1) and c["expires"] > 0:
            d["expires"] = c["expires"]
        if c.get("httpOnly"):
            d["httpOnly"] = True
        if c.get("secure"):
            d["secure"] = True
        ss = (c.get("sameSite") or "Lax")
        d["sameSite"] = ss if ss in ("Lax", "Strict", "None") else "Lax"
        out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true", default=True)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    key = os.environ.get("SERVERCHAN_KEY", "")
    state = load_state()
    result = {}

    with sync_playwright() as p:
        launch_kw = dict(headless=args.headless,
                         args=["--no-sandbox", "--disable-dev-shm-usage"])
        launch_kw["channel"] = "msedge" if os.name == "nt" else "chromium"
        browser = p.chromium.launch(**launch_kw)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 1000}, locale="zh-CN",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"))
        ctx.add_cookies(to_pw(state))
        page = ctx.new_page()

        page.goto(PAGE, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(6000)

        if "/login" in page.url:
            print("[!] 登录态失效（被跳转到登录页）", file=sys.stderr)
            page.screenshot(path="login_required.png")
            push_serverchan("WorkBuddy 自动任务失败",
                            "登录态已失效，需要重新登录。\n"
                            "请联系 AI 重新生成登录态（wb_state.json）。", key)
            ctx.close()
            sys.exit(2)

        result = page.evaluate(JS_SCRIPT)
        page.screenshot(path="result.png", full_page=True)
        ctx.close()

    def dg(x, *ks, d=None):
        # 兼容：x 可能是 {status,json:{data:...}}，也可能是已取出的 data
        cur = x
        if isinstance(cur, dict) and "json" in cur:
            cur = cur["json"]
        if isinstance(cur, dict) and cur.get("code") == 0 and "data" in cur:
            cur = cur["data"]
        for k in ks:
            if not isinstance(cur, dict):
                return d
            cur = cur.get(k)
        return cur if cur is not None else d

    streak = dg(result.get("streak_after"), "streak") or {}
    energy = dg(result.get("energy_after")) or {}
    profile = dg(result.get("profile")) or {}
    ts3 = dg(result.get("travel_status3")) or {}
    buddy = dg(result.get("buddy_info"), "buddy") or {}

    print("=" * 58)
    print("WorkBuddy 成长中心自动任务")
    print("=" * 58)
    print(f"日期        : {result.get('today')}")
    print(f"等级        : Lv.{profile.get('level')}  (任务 {profile.get('completed')}/{profile.get('total')})")
    print(f"今日签到    : {'已打卡 ✅' if result.get('checked_in') else '未打卡'}")
    print(f"连登天数    : {streak.get('days')} 天")
    print(f"能量        : {energy.get('balance')}")
    print(f"猫咪        : {buddy.get('name')} ({buddy.get('rarity')})")

    lines = [f"**WorkBuddy 每日任务** — {result.get('today')}",
             f"- 等级 Lv.{profile.get('level')}",
             f"- 签到: {'已打卡 ✅' if result.get('checked_in') else '未打卡'}",
             f"- 连登 {streak.get('days')} 天",
             f"- 猫咪: {buddy.get('name')}"]

    print("\n--- 派猫猫旅行 ---")
    print(f"操作前: state={result.get('travel_state_before')} 今日已用={result.get('daily_limit_before')}")
    claim = result.get("claim", {})
    depart = result.get("depart", {})

    if claim.get("status") == 200:
        print("领取旅行奖励: 成功 ✅")
        lines.append("- 旅行奖励: 已领取 ✅")
    elif "skipped" in claim:
        print(f"领取旅行奖励: 跳过（{claim['skipped']}）")
    else:
        print(f"领取旅行奖励: {claim.get('raw') or claim.get('error')}")
        lines.append(f"- 旅行奖励: {claim.get('raw') or claim.get('error')}")

    print(f"操作后: state={result.get('travel_state_after')}")
    if depart.get("status") == 200:
        loc = result.get("depart_location", {})
        print(f"派出新猫: 成功 → {loc.get('name')} (id={loc.get('id')}) ✅")
        lines.append(f"- 派猫猫: 已出发 ✅「{loc.get('name')}」")
    elif "skipped" in depart:
        print(f"派出新猫: 跳过（{depart['skipped']}）")
        lines.append(f"- 派猫猫: 今日已旅行过，跳过")
    else:
        print(f"派出新猫: {depart.get('raw') or depart.get('error')}")
        lines.append(f"- 派猫猫: {depart.get('raw') or depart.get('error')}")

    print(f"最终状态: {ts3.get('state')}  能量: {energy.get('balance')}")
    print("=" * 58)
    push_serverchan("WorkBuddy 每日任务完成", "\n".join(lines), key)
    print("[OK] 完成")


if __name__ == "__main__":
    main()