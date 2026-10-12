#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 每日签到 + 派猫猫旅行 自动化脚本
运行环境: GitHub Actions 云端 runner（无本机登录态）
结果推送: 微信 Server酱（方糖），零安装
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))

# =====================================================================
# 接口地址：以浏览器实际抓到的为准，不要乱猜。
# 抓到后（1）直接发给我，我替你填进下面的常量；或
# （2）在仓库 Settings -> Secrets 里设 WB_CHECKIN_STATUS_URL 等覆盖。
# 留空则脚本会明确提示“接口未配置”，不会瞎跑。
# =====================================================================
CHECKIN_STATUS_URL = os.environ.get('WB_CHECKIN_STATUS_URL', '')
CHECKIN_DO_URL     = os.environ.get('WB_CHECKIN_DO_URL', '')
TRAVEL_STATUS_URL  = os.environ.get('WB_TRAVEL_STATUS_URL', '')
TRAVEL_CLAIM_URL   = os.environ.get('WB_TRAVEL_CLAIM_URL', '')
TRAVEL_DEPART_URL  = os.environ.get('WB_TRAVEL_DEPART_URL', '')


def get_env(name: str, default: str = None) -> str:
    """读取环境变量；支持 base64 包装的密钥（Actions 里可勾选加密）。"""
    val = os.environ.get(name, default)
    if not val:
        return val
    try:
        decoded = base64.b64decode(val).decode('utf-8')
        if decoded and len(decoded) > len(val):
            return decoded
    except Exception:
        pass
    return val


def http_json(url: str, headers: dict, body: dict = None, method: str = 'POST', timeout: int = 30) -> dict:
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode('utf-8')
    try:
        return json.loads(raw)
    except Exception:
        return {'_raw': raw}


def build_headers(access_token: str) -> dict:
    uid = get_env('WORKBUDDY_USER_ID')
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) WorkBuddyDaily/1.0',
    }
    if uid:
        headers['X-User-Id'] = uid
    return headers


# ---------------------- 推送：微信 Server酱（方糖） ----------------------
def push_serverchan(key: str, title: str, desp: str) -> bool:
    """Server酱推送。key 形如 SCTxxxxxxxx.send 或完整 SendKey。"""
    key = key.strip()
    if key.endswith('.send'):
        send_key = key
    else:
        send_key = f"{key}.send"
    url = f"https://sctapi.ftqq.com/{send_key}"
    payload = urllib.parse.urlencode({'title': title, 'desp': desp}).encode('utf-8')
    req = urllib.request.Request(
        url, data=payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode('utf-8'))
        ok = result.get('code') == 0
        print(f"   Server酱推送: {'✅' if ok else '⚠️'} {result.get('message', '')}")
        return ok
    except Exception as e:
        print(f"   Server酱推送失败: {e}")
        return False


def push_feishu(webhook_url: str, sign: str, text: str) -> bool:
    import hmac, hashlib, base64
    timestamp = str(int(datetime.now().timestamp()))
    string_to_sign = timestamp + '\n' + sign
    hmac_code = hmac.new(sign.encode('utf-8'), string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
    signature = base64.b64encode(hmac_code).decode('utf-8')
    data = {'timestamp': timestamp, 'sign': signature if sign else '',
            'msg_type': 'text', 'content': {'text': text}}
    try:
        req = urllib.request.Request(webhook_url, data=json.dumps(data).encode('utf-8'),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8')).get('code') == 0
    except Exception:
        return False


def notify(title: str, desp: str) -> None:
    key = get_env('SERVERCHAN_KEY')
    if key:
        push_serverchan(key, title, desp)
        return
    webhook = get_env('FEISHU_WEBHOOK')
    if webhook:
        sign = get_env('FEISHU_WEBHOOK_SIGN', '')
        push_feishu(webhook, sign, desp)


# ---------------------- 业务：签到 ----------------------
def do_checkin_flow(headers: dict) -> tuple:
    """返回 (成功bool, 状态描述str)。"""
    if not CHECKIN_STATUS_URL or not CHECKIN_DO_URL:
        return False, "⚠️ 签到接口未配置（WB_CHECKIN_STATUS_URL / WB_CHECKIN_DO_URL）"
    try:
        status = http_json(CHECKIN_STATUS_URL, headers, method='POST')
        print(f"   [调试] 签到状态返回: {json.dumps(status, ensure_ascii=False)[:300]}")
        data = status.get('data', {}) or {}
        # 已签到判断（不同接口字段名不同，做多字段兼容）
        already = data.get('today_checked') or data.get('checked') or data.get('checkin_record')
        if already:
            return True, "✅ 今天已签到，无需重复"
        res = http_json(CHECKIN_DO_URL, headers, body={})
        print(f"   [调试] 签到动作返回: {json.dumps(res, ensure_ascii=False)[:300]}")
        rdata = res.get('data', {}) or {}
        credit = rdata.get('credit') or rdata.get('points') or rdata.get('reward') or 0
        streak = rdata.get('streak') or rdata.get('continuous_days') or 0
        if res.get('code') in (0, 10001, None) and (res.get('code') != 1):
            return True, f"✅ 签到成功！+{credit}积分，连签{streak}天"
        return True, f"✅ 已提交签到（code={res.get('code')}）"
    except Exception as e:
        return False, f"❌ 签到失败: {e}"


# ---------------------- 业务：派猫猫旅行 ----------------------
def do_travel_flow(headers: dict) -> tuple:
    """先领已到家的积分，再判断是否派新的一趟；今天派过就别派。"""
    if not TRAVEL_STATUS_URL:
        return False, "⚠️ 旅行接口未配置（WB_TRAVEL_STATUS_URL 等）"
    try:
        status = http_json(TRAVEL_STATUS_URL, headers, method='GET')
        print(f"   [调试] 旅行状态返回: {json.dumps(status, ensure_ascii=False)[:300]}")
        data = status.get('data', {}) or {}
        state = str(data.get('state', data.get('status', ''))).lower()
        daily_done = data.get('daily_limit_reached') or data.get('today_dispatched') or data.get('already_sent_today')

        if daily_done:
            return True, "✅ 今天已经派过啦，不再派"

        # 先领已到家的奖励
        claimed = ""
        if TRAVEL_CLAIM_URL:
            claim = http_json(TRAVEL_CLAIM_URL, headers, method='POST', body={})
            print(f"   [调试] 领取返回: {json.dumps(claim, ensure_ascii=False)[:200]}")
            cdata = claim.get('data', {}) or {}
            credit = cdata.get('credit') or cdata.get('reward') or 0
            if claim.get('code') in (0, None):
                claimed = f"🎁 领取到家奖励 +{credit}积分\n"

        # 再判断是否派新的一趟（idle/可派 才派）
        if state in ('idle', 'home', 'arrived', '可出发', '') and TRAVEL_DEPART_URL:
            depart = http_json(TRAVEL_DEPART_URL, headers, method='POST', body={'location_id': 1})
            print(f"   [调试] 派出返回: {json.dumps(depart, ensure_ascii=False)[:200]}")
            ddata = depart.get('data', {}) or {}
            loc = ddata.get('location', {}).get('name') if isinstance(ddata.get('location'), dict) else ddata.get('location') or '新地点'
            if depart.get('code') in (0, None):
                return True, (claimed + f"🐱 已派出新的一趟 → {loc}").strip()
            return True, (claimed + "⚠️ 派出接口返回异常，但领取已完成").strip()

        return True, (claimed + f"🐱 当前状态: {state or '未知'}，暂不新派").strip() or "✅ 旅行检查完成"
    except Exception as e:
        return False, f"❌ 旅行失败: {e}"


def run():
    access_token = get_env('WORKBUDDY_ACCESS_TOKEN')
    if not access_token:
        print("❌ 缺少 WORKBUDDY_ACCESS_TOKEN（请在仓库 Secrets 配置）")
        sys.exit(1)

    masked = access_token[:8] + "..." if len(access_token) > 8 else "***"
    print(f"🔑 Token: {masked}")
    headers = build_headers(access_token)

    print("\n" + "=" * 52)
    print("🤖 WorkBuddy 每日任务")
    print(f"⏰ {datetime.now(BJT).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 52)

    # 签到（独立 try，失败不影响结论）
    print("\n📋 [签到] 开始...")
    checkin_ok, checkin_msg = False, ""
    try:
        checkin_ok, checkin_msg = do_checkin_flow(headers)
    except Exception as e:
        checkin_msg = f"❌ 签到异常: {e}"
    print(f"   {checkin_msg}")

    # 旅行（独立 try，失败不影响签到结论）
    print("\n🐱 [旅行] 开始...")
    travel_ok, travel_msg = False, ""
    try:
        travel_ok, travel_msg = do_travel_flow(headers)
    except Exception as e:
        travel_msg = f"❌ 旅行异常: {e}"
    print(f"   {travel_msg}")

    print("\n" + "=" * 52)
    print("📊 执行结果")
    print("=" * 52)
    print(f"签到: {'✅' if checkin_ok else '❌'} {checkin_msg}")
    print(f"旅行: {'✅' if travel_ok else '⚠️'} {travel_msg}")

    # 推送（微信 Server酱）
    now_str = datetime.now(BJT).strftime('%Y-%m-%d %H:%M')
    desp = f"⏰ {now_str}\n\n"
    desp += f"📋 **签到**：{checkin_msg}\n\n"
    desp += f"🐱 **旅行**：{travel_msg}\n"
    print("\n📤 推送结果...")
    notify("🤖 WorkBuddy 每日任务", desp)

    # 签到成功即算成功（旅行失败不拖累）
    sys.exit(0 if checkin_ok else 1)


if __name__ == '__main__':
    run()
