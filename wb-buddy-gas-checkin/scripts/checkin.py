"""
WorkBuddy「Buddy 加油站」每日签到 + 派猫猫旅行（浏览器通道版）

原理：
- 读取登录态 WB_STATE（环境变量 JSON，或同目录 wb_state.json）
- Playwright 启动真实浏览器，注入 Cookie，在页面上下文调用接口
  （纯 HTTP 会被 APISIX 网关 401 拦截，必须在页面内 fetch）
- 可选推送到微信（方糖 Server酱）

模式：
  --mode gas    仅加油站签到（默认）
  --mode cat    仅派猫猫旅行
  --mode both   两者都做

用法：
  python checkin.py
  python checkin.py --mode both
  SERVERCHAN_KEY=xxxx python checkin.py
"""
import json, os, sys, argparse, urllib.request, urllib.parse, datetime, base64

BASE = "https://www.workbuddy.cn"
PAGE = BASE + "/profile/growth-center"

JS_SCRIPT = r"""
async (mode) => {
  const withCat = (mode === 'cat' || mode === 'both');
  const onlyGas = (mode === 'gas' || mode === 'both');
  const out = {mode};
  const req = async (method, path, body) => {
    try {
      const opt = {method, credentials:'include', headers:{'Content-Type':'application/json'}};
      if (body !== undefined && body !== null) opt.body = JSON.stringify(body);
      const r = await fetch(path, opt);
      const t = await r.text();
      let j = null; try { j = JSON.parse(t); } catch(e) {}
      return {status:r.status, json:j, raw:t.slice(0,400)};
    } catch(e) { return {error:String(e)}; }
  };

  // ============ 加油站每日签到（每日100积分，/v2/billing 域） ============
  out.gas = {skipped:'disabled'};
  if (onlyGas) {
    const st = await req('POST','/v2/billing/meter/checkin-activity-status', {});
    const gs = st.json?.data || {};
    out.gas_active = !!gs.active;
    out.gas_today_checked = !!gs.today_checked_in;
    out.gas_streak_before = gs.streak_days;
    if (gs.active && !gs.today_checked_in) {
      out.gas = await req('POST','/v2/billing/meter/daily-checkin', {});
    } else if (!gs.active) {
      out.gas = {skipped:'activity inactive'};
    } else {
      out.gas = {skipped:'already checked in today'};
    }
  }

  // ============ 派猫猫旅行 + 领旅行奖励 ============
  out.cat = {skipped:'disabled'};
  if (withCat) {
    const ts = (await req('GET','/activity/growth/buddy/travel/status')).json?.data || {};
    out.travel_state = ts.state;
    out.daily_limit = !!ts.daily_limit_reached;
    const cfg = (await req('GET','/activity/growth/buddy/travel/config')).json?.data || {};
    if (ts.state === 'idle' && !ts.daily_limit_reached) {
      let locs = cfg.locations || [];
      locs = locs.slice().sort((a,b)=>((b.reward_credit_max||0)-(a.reward_credit_max||0)));
      if (locs.length) {
        out.depart_location = locs[0];
        out.cat = await req('POST','/activity/growth/buddy/travel/depart', {location_id:locs[0].id});
      } else { out.cat = {error:'no locations'}; }
    } else {
      out.cat = {skipped:'state='+ts.state+' daily_limit='+ts.daily_limit_reached};
    }
    // 领旅行奖励（若已到站）
    const ts2 = (await req('GET','/activity/growth/buddy/travel/status')).json?.data || {};
    if (ts2.state === 'arrived') {
      out.claim = await req('POST','/activity/growth/buddy/travel/claim', {});
    } else {
      out.claim = {skipped:'travel state='+ts2.state};
    }
  }
  return out;
}
"""


def push_serverchan(title, desp, key):
    if not key:
        return
    try:
        data = urllib.parse.urlencode({"title": title, "desp": desp}).encode()
        req = urllib.request.Request(
            f"https://sctapi.ftqq.com/{key}.send", data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=20) as r:
            print("[push]", r.status, r.read().decode("utf-8", "ignore")[:120])
    except Exception as e:
        print("[!] 推送失败:", e)


def load_state():
    raw = os.environ.get("WB_STATE", "").strip()
    if raw:
        return json.loads(raw)
    for p in (os.path.join(os.path.dirname(__file__), "wb_state.json"),
              os.path.join(os.getcwd(), "wb_state.json"),
              "/tmp/wb_state.json"):
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
    raise SystemExit("[!] 找不到登录态：请设置 WB_STATE 环境变量或提供 wb_state.json")


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


def biz_ok(r):
    return isinstance(r, dict) and r.get("status") == 200 \
        and isinstance(r.get("json"), dict) and r["json"].get("code") == 0


def dg(x, *ks, d=None):
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["gas", "cat", "both"], default="gas")
    ap.add_argument("--headless", action="store_true", default=True)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    key = os.environ.get("SERVERCHAN_KEY", "")
    state = load_state()

    with sync_playwright() as p:
        launch_kw = dict(headless=args.headless, args=["--no-sandbox", "--disable-dev-shm-usage"])
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
            print("[!] 登录态失效", file=sys.stderr)
            page.screenshot(path="login_required.png")
            push_serverchan("WorkBuddy 自动任务失败",
                            "登录态已失效，需要重新登录并导出 Cookie。", key)
            ctx.close()
            sys.exit(2)
        result = page.evaluate(JS_SCRIPT, args.mode)
        ctx.close()

    lines = [f"**WorkBuddy 任务[{args.mode}]**"]
    print("=" * 56)
    print(f"WorkBuddy 自动任务 [{args.mode}]")
    print("=" * 56)

    # ---- 加油站 ----
    if args.mode != "cat":
        print("\n--- 加油站签到 ---")
        gas = result.get("gas", {})
        if biz_ok(gas):
            gd = (gas.get("json") or {}).get("data") or {}
            gain = gd.get("credit", "?")
            print(f"签到成功 ✅  +{gain} 积分  连签 {gd.get('streak_days')} 天")
            lines.append(f"- ⛽ 加油站签到：**+{gain} 积分** ✅（连签 {gd.get('streak_days')} 天）")
        elif "skipped" in gas:
            print(f"跳过（{gas['skipped']}）")
            if gas['skipped'] != 'already checked in today':
                lines.append(f"- ⛽ 加油站签到: 跳过（{gas['skipped']}）")
        else:
            print(f"失败: {gas.get('raw') or gas.get('error')}")
            lines.append(f"- ⛽ 加油站签到: {gas.get('raw') or gas.get('error')}")

    # ---- 派猫猫 ----
    if args.mode != "gas":
        print("\n--- 派猫猫 ---")
        cat = result.get("cat", {})
        if biz_ok(cat):
            loc = result.get("depart_location", {})
            print(f"派猫成功 → {loc.get('name')} ✅")
            lines.append(f"- 派猫猫: 已出发 ✅「{loc.get('name')}」")
        elif "skipped" in cat:
            print(f"跳过（{cat['skipped']}）")
            lines.append(f"- 派猫猫: {cat['skipped']}")
        else:
            print(f"失败: {cat.get('raw') or cat.get('error')}")
            lines.append(f"- 派猫猫: {cat.get('raw') or cat.get('error')}")
        claim = result.get("claim", {})
        if biz_ok(claim):
            cr = (claim.get("json") or {}).get("data") or {}
            gain = cr.get("reward_credit") or cr.get("credit") or "?"
            print(f"领旅行奖励 ✅ +{gain} 积分")
            lines.append(f"- 🎁 旅行奖励: **+{gain} 积分** ✅")
        elif isinstance(claim, dict) and "skipped" in claim:
            print(f"旅行奖励: {claim['skipped']}")

    print("=" * 56)

    did = any(biz_ok(result.get(k, {})) for k in ("gas", "cat", "claim"))
    if key and (did or args.mode in ("gas", "cat", "both")):
        push_serverchan(f"WorkBuddy [{args.mode}]", "\n".join(lines), key)
    print("[OK] 完成")


if __name__ == "__main__":
    main()
