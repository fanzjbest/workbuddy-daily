#!/usr/bin/env python3
"""
WorkBuddy 每日签到 + 派猫猫旅行自动化脚本
支持 GitHub Actions 云端运行，结果推送飞书
"""

import json
import os
import sys
import hmac
import hashlib
import base64
import urllib.request
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))


def get_env(name: str, default: str = None) -> str:
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


def api_post(url: str, headers: dict, body: dict = None, timeout: int = 30) -> dict:
    data = json.dumps(body).encode('utf-8') if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def api_get(url: str, headers: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers=headers, method='GET')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def build_headers(access_token: str) -> dict:
    uid = get_env('WORKBUDDY_USER_ID')
    if not uid:
        raise ValueError("缺少 WORKBUDDY_USER_ID 环境变量")
    return {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}',
        'X-User-Id': uid,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    }


def checkin_status(headers: dict) -> dict:
    return api_post('https://www.codebuddy.cn/v2/billing/meter/checkin-activity-status', headers)


def do_checkin(headers: dict) -> dict:
    return api_post('https://www.codebuddy.cn/v2/billing/meter/daily-checkin', headers)


def travel_status(headers: dict) -> dict:
    return api_get('https://www.workbuddy.cn/activity/growth/buddy/travel/status', headers)


def travel_claim(headers: dict) -> dict:
    return api_post('https://www.workbuddy.cn/activity/growth/buddy/travel/claim', headers)


def travel_depart(headers: dict, location_id: int = 1) -> dict:
    return api_post('https://www.workbuddy.cn/activity/growth/buddy/travel/depart', headers, body={'location_id': location_id})


def push_feishu(webhook_url: str, sign: str, text: str) -> bool:
    timestamp = str(int(datetime.now().timestamp()))
    string_to_sign = timestamp + '\n' + sign
    hmac_code = hmac.new(sign.encode('utf-8'), string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
    signature = base64.b64encode(hmac_code).decode('utf-8')
    data = {'timestamp': timestamp, 'sign': signature if sign else '', 'msg_type': 'text', 'content': {'text': text}}
    try:
        req = urllib.request.Request(webhook_url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8')).get('code') == 0
    except Exception as e:
        print(f"飞书推送失败: {e}")
        return False


def run():
    access_token = get_env('WORKBUDDY_ACCESS_TOKEN')
    if not access_token:
        print("❌ 缺少 WORKBUDDY_ACCESS_TOKEN 环境变量")
        sys.exit(1)

    masked_token = access_token[:8] + "..." if len(access_token) > 8 else "***"
    print(f"🔑 Token: {masked_token}")
    headers = build_headers(access_token)

    checkin_ok = False
    checkin_msg = ""
    travel_ok = False
    travel_msg = ""
    all_errors = []

    print("\n" + "=" * 50)
    print("🤖 WorkBuddy 每日任务")
    print(f"⏰ {datetime.now(BJT).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # 签到
    print("\n📋 [签到] 开始...")
    try:
        status = checkin_status(headers)
        code = status.get('code')
        data = status.get('data', {})
        if code == 0:
            if data.get('today_checked') or data.get('checkin_record'):
                checkin_msg = "✅ 今天已签到，无需重复操作"
                checkin_ok = True
            else:
                result = do_checkin(headers)
                code2 = result.get('code')
                if code2 in (0, 10001):
                    credit = result.get('data', {}).get('credit', 100)
                    streak = result.get('data', {}).get('streak', 0)
                    checkin_msg = f"✅ 签到成功！+{credit}积分，连签{streak}天"
                    checkin_ok = True
                else:
                    checkin_msg = f"⚠️ 签到异常 code={code2}"
        else:
            checkin_msg = f"⚠️ 状态查询异常 code={code}"
        print(f"   {checkin_msg}")
    except Exception as e:
        checkin_msg = f"❌ 签到失败: {e}"
        all_errors.append(("签到", str(e)))
        print(f"   {checkin_msg}")

    # 旅行
    print("\n🐱 [旅行] 开始...")
    try:
        status = travel_status(headers)
        code = status.get('code')
        data = status.get('data', {})
        if code != 0:
            travel_msg = f"⚠️ 查询异常 code={code}"
            print(f"   {travel_msg}")
        else:
            state = data.get('state', '')
            daily_limit = data.get('daily_limit_reached', False)
            if daily_limit:
                travel_msg = "⚠️ 今日旅行次数已达上限"
                travel_ok = True
            elif state == 'idle':
                claim_result = travel_claim(headers)
                if claim_result.get('code') == 0:
                    credit = claim_result.get('data', {}).get('credit', 0)
                    travel_msg = f"🎁 领取奖励 +{credit}积分"
                    travel_ok = True
                else:
                    travel_msg = "ℹ️ 暂无可领取奖励"
                    travel_ok = True
                if travel_ok:
                    depart_result = travel_depart(headers)
                    if depart_result.get('code') == 0:
                        loc = depart_result.get('data', {}).get('location', {}).get('name', '未知')
                        travel_msg += f"\n🐱 已派出前往: {loc}"
                        travel_ok = True
                    else:
                        travel_msg += "\n⚠️ 派出失败"
                        all_errors.append(("派出", str(depart_result.get('msg'))))
            elif state == 'traveling':
                travel_msg = "🐱 猫猫正在旅行中..."
                travel_ok = True
            elif state == 'arrived':
                travel_msg = "🐱 猫猫已到达，下次运行将领取"
                travel_ok = True
            else:
                travel_msg = f"ℹ️ 状态: {state}"
                travel_ok = True
        print(f"   {travel_msg}")
    except Exception as e:
        travel_msg = f"❌ 旅行失败: {e}"
        all_errors.append(("旅行", str(e)))
        print(f"   {travel_msg}")

    # 汇总
    print("\n" + "=" * 50)
    print("📊 执行结果")
    print("=" * 50)
    print(f"签到: {'✅' if checkin_ok else '❌'} {checkin_msg}")
    print(f"旅行: {'✅' if travel_ok else '⚠️'} {travel_msg}")
    if all_errors:
        print(f"\n⚠️ 错误项 ({len(all_errors)}):")
        for task, err in all_errors:
            print(f"  - {task}: {err}")
    else:
        print("\n🎉 全部正常")

    # 推送飞书
    webhook_url = get_env('FEISHU_WEBHOOK')
    if webhook_url:
        sign = get_env('FEISHU_WEBHOOK_SIGN', '')
        now_str = datetime.now(BJT).strftime('%Y-%m-%d %H:%M')
        message = f"🤖 WorkBuddy 每日任务报告\n⏰ {now_str}\n\n"
        message += f"📋 签到: {checkin_msg}\n\n"
        message += f"🐱 旅行: {travel_msg}\n"
        if all_errors:
            message += "\n⚠️ 错误项:\n"
            for task, err in all_errors:
                message += f"  - {task}: {err}\n"
        else:
            message += "\n🎉 全部任务完成"
        print(f"\n📤 推送飞书...")
        push_feishu(webhook_url, sign, message)
    else:
        print("\nℹ️ 未配置 FEISHU_WEBHOOK，跳过推送")

    sys.exit(0 if checkin_ok else 1)


if __name__ == '__main__':
    run()
