"""
WorkBuddy 成长中心云端自动化：派猫猫旅行 + 领旅行奖励
- 从环境变量 WB_STATE（JSON cookie）读取登录态
- 注入浏览器后，在页面上下文中调用接口（纯 HTTP 会被 APISIX 网关 401 拦截）
- 结果通过 Server酱推送到微信

两种运行模式（由 GitHub Actions 两个 workflow 分别调度）：
  --mode depart   仅派猫猫（每天 1~2 次）
  --mode claim    仅领积分（每天 1 次，猫到站后）
  --mode both     两者都做（默认，兼容手动运行）

每次运行后会把精简结果写回仓库 last_run.json（仅 Actions 环境），便于排查。
"""
import json, os, sys, argparse, urllib.request, urllib.parse, base64, datetime

BASE = "https://www.workbuddy.cn"
PAGE = BASE + "/profile/growth-center"

JS_SCRIPT = r"""
async (mode) => {
  const doClaim  = (mode !== 'depart');
  const doDepart = (mode !== 'claim');
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

  out.profile = await req('GET','/v2/activity/growth/profile');
  out.streak  = await req('GET','/activity/growth/streak');
  out.energy  = await req('GET','/activity/growth/energy');
  out.heatmap = await req('GET','/activity/growth/heatmap');
  out.travel_status  = await req('GET','/activity/growth/buddy/travel/status');
  out.travel_config  = await req('GET','/activity/growth/buddy/travel/config');
  out.buddy_info = await req('GET','/activity/growth/buddy/info');

  const now = new Date();
  const sh = new Date(now.getTime() + (8*60 + now.getTimezoneOffset())*60000);
  const todayStr = sh.toISOString().slice(0,10);
  out.today = todayStr;
  try {
    const cells = out.heatmap.json?.data?.cells || [];
    const cell = cells.find(c => c.date === todayStr);
    out.checked_in = !!(cell && ((cell.score||0)>0 || cell.has_new_buddy));
  } catch(e){ out.checked_in = false; }

  const shTs = (sec) => {
    if (!sec) return '';
    return new Date((sec + 8*3600) * 1000).toISOString().slice(0,16).replace('T',' ');
  };

  const ts = out.travel_status.json?.data || {};
  out.travel_state_before = ts.state;
  out.daily_limit_before  = !!ts.daily_limit_reached;
  out.arrive_at_txt = shTs(ts.arrive_at);
  out.depart_at_txt = shTs(ts.depart_at);

  // ============ 领奖：仅当猫猫已到站（arrived）才有效 ============
  out.claim = {skipped:'claim disabled in this mode'};
  if (doClaim) {
    if (ts.state === 'arrived') {
      out.claim = await req('POST','/activity/growth/buddy/travel/claim', {});
    } else if (ts.state === 'traveling') {
      out.claim = {skipped:'buddy still traveling, arrive at ' + (out.arrive_at_txt||'?')};
    } else {
      // idle 时兜底尝试一次，兼容后端记录未及时清理
      const r = await req('POST','/activity/growth/buddy/travel/claim', {});
      out.claim = (r.status === 200) ? r : {skipped:'no unclaimed travel'};
    }
  }

  // ============ 派猫：仅当 idle 且今日额度未用 ============
  out.depart = {skipped:'depart disabled in this mode'};
  if (doDepart) {
    const ts2 = (await req('GET','/activity/growth/buddy/travel/status')).json?.data || {};
    out.travel_state2 = ts2.state;
    out.daily_limit2  = !!ts2.daily_limit_reached;
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
  }

  out.energy_after = await req('GET','/activity/growth/energy');
  out.travel_status3 = await req('GET','/activity/growth/buddy/travel/status');
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
            print("[push]", r.status, r.read().decode("utf-8", "ignore")[:120])
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


def gh_put(token, repo, path, content, branch="main"):
    """把内容写回仓库（覆盖），用于记录运行结果，便于排查。"""
    if not token or not repo:
        return
    api = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    body = {"message": f"run log: {path}", "content": base64.b64encode(content.encode("utf-8")).decode(), "branch": branch}
    try:
        with urllib.request.urlopen(urllib.request.Request(api, headers=headers), timeout=20) as r:
            sha = json.loads(r.read()).get("sha")
        if sha:
            body["sha"] = sha
    except Exception:
        pass
    try:
        urllib.request.urlopen(urllib.request.Request(api, data=json.dumps(body).encode(), headers=headers, method="PUT"), timeout=20)
        print("[log] 已写回", path)
    except Exception as e:
        print("[!] 写回失败:", e)


def append_log(token, repo, path, line, branch="main"):
    """把一行 JSON 追加到仓库的 jsonl 文件（用于跨天历史）。"""
    if not token or not repo:
        return
    api = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    old = ""
    try:
        with urllib.request.urlopen(urllib.request.Request(api, headers=headers), timeout=20) as r:
            j = json.loads(r.read())
            import base64 as _b
            old = _b.b64decode(j["content"]).decode("utf-8", "ignore")
            sha = j.get("sha")
    except Exception:
        sha = None
    new_content = (old + line + "\n").encode("utf-8")
    body = {"message": f"log append: {path}", "content": base64.b64encode(new_content).decode(), "branch": branch}
    if sha:
        body["sha"] = sha
    try:
        urllib.request.urlopen(urllib.request.Request(api, data=json.dumps(body).encode(), headers=headers, method="PUT"), timeout=20)
        print("[log] 已追加", path)
    except Exception as e:
        print("[!] 追加失败:", e)


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
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--mode", choices=["both", "depart", "claim"], default="both")
    ap.add_argument("--always-notify", action="store_true")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    key = os.environ.get("SERVERCHAN_KEY", "")
    state = load_state()
    result = {}

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
                            "登录态已失效，需要重新登录。请联系 AI 重新生成登录态。", key)
            ctx.close()
            sys.exit(2)
        result = page.evaluate(JS_SCRIPT, args.mode)
        page.screenshot(path="result.png", full_page=True)
        ctx.close()

    streak = dg(result.get("streak"), "streak") or {}
    energy = dg(result.get("energy_after")) or {}
    profile = dg(result.get("profile")) or {}
    ts3 = dg(result.get("travel_status3")) or {}
    buddy = dg(result.get("buddy_info"), "buddy") or {}
    claim = result.get("claim", {})
    depart = result.get("depart", {})

    print("=" * 58)
    print(f"WorkBuddy 自动任务 [{args.mode}]")
    print("=" * 58)
    print(f"日期   : {result.get('today')}")
    print(f"等级   : Lv.{profile.get('level')}  连登 {streak.get('days')} 天")
    print(f"能量   : {energy.get('balance')}")
    print(f"猫咪   : {buddy.get('name')} ({buddy.get('rarity')})")
    print(f"旅行态 : {result.get('travel_state_before')}  今日已派={result.get('daily_limit_before')}")

    lines = [f"**WorkBuddy 任务[{args.mode}]** — {result.get('today')}",
             f"- 等级 Lv.{profile.get('level')} / 连登 {streak.get('days')} 天 / 能量 {energy.get('balance')}",
             f"- 猫咪: {buddy.get('name')}  状态: {result.get('travel_state_before')}"]

    # ---- 领奖 ----
    if args.mode != "depart":
        print("\n--- 领积分 ---")
        if biz_ok(claim):
            cr = (claim.get("json") or {}).get("data") or {}
            gain = cr.get("reward_credit") or cr.get("credit") or "?"
            print(f"领取旅行奖励: 成功 ✅  到账 {gain} 积分")
            lines.append(f"- 🎁 旅行奖励已领取：**+{gain} 积分** ✅")
        elif "skipped" in claim:
            print(f"领取旅行奖励: 跳过（{claim['skipped']}）")
            lines.append(f"- 领积分: 跳过（{claim['skipped']}）")
        else:
            print(f"领取旅行奖励: {claim.get('raw') or claim.get('error')}")
            lines.append(f"- 领积分: {claim.get('raw') or claim.get('error')}")
        if result.get("travel_state_before") == "traveling":
            print(f"猫咪旅途中，预计 {result.get('arrive_at_txt')} 到站（北京）")
            if not biz_ok(claim):
                lines.append(f"- ⏳ 猫咪旅途中，预计 {result.get('arrive_at_txt')} 到站后会自动领")

    # ---- 派猫 ----
    if args.mode != "claim":
        print("\n--- 派猫猫 ---")
        if biz_ok(depart):
            loc = result.get("depart_location", {})
            print(f"派出新猫: 成功 → {loc.get('name')} (id={loc.get('id')}) ✅")
            lines.append(f"- 派猫猫: 已出发 ✅「{loc.get('name')}」")
        elif "skipped" in depart:
            print(f"派出新猫: 跳过（{depart['skipped']}）")
            lines.append(f"- 派猫猫: {depart['skipped']}")
        else:
            print(f"派出新猫: {depart.get('raw') or depart.get('error')}")
            lines.append(f"- 派猫猫: {depart.get('raw') or depart.get('error')}")

    print(f"最终状态: {ts3.get('state')}  能量: {energy.get('balance')}")
    print("=" * 58)

    # 通知策略：claim/depart 模式强制推送（用户要看到结果）；both 模式仅在确有动作时推送
    did_something = biz_ok(claim) or biz_ok(depart)
    force = args.always_notify or args.mode in ("claim", "depart")
    if force or did_something:
        push_serverchan(f"WorkBuddy [{args.mode}]", "\n".join(lines), key)
    else:
        print("[push] 无新动作，不推送")

    # 写回运行结果（追加历史），便于跨天排查 claim 是否真的命中
    if os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"):
        log = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": args.mode,
            "state": result.get("travel_state_before"),
            "daily_limit": result.get("daily_limit_before"),
            "claim_status": claim.get("status") if isinstance(claim, dict) else str(claim),
            "claim_raw": (claim.get("raw") or claim.get("json") if isinstance(claim, dict) else None),
            "depart_status": (depart.get("status") if isinstance(depart, dict) else str(depart)),
            "depart_raw": (depart.get("raw") or depart.get("json") if isinstance(depart, dict) else None),
            "energy": energy.get("balance"),
        }
        append_log(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"],
                   "run_log.jsonl", json.dumps(log, ensure_ascii=False))
    print("[OK] 完成")


if __name__ == "__main__":
    main()
