#!/usr/bin/env python3
"""本地 token 导出脚本"""

import json
import os
import sys
from pathlib import Path

AUTH_PATHS = [
    Path.home() / "AppData" / "Local" / "CodeBuddyExtension" / "Data" / "Public" / "auth" / "workbuddy-desktop.info",
]

def find_auth_file() -> Path:
    for path in AUTH_PATHS:
        if path.exists():
            return path
    raise FileNotFoundError(f"未找到登录态文件")

def main():
    auth_file = find_auth_file()
    print(f"📂 读取登录态文件: {auth_file}")
    with open(auth_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    uid = data.get('account', {}).get('uid', '')
    if not uid:
        print("❌ 无法读取 uid")
        sys.exit(1)
    print("\n" + "=" * 60)
    print("📋 配置说明")
    print("=" * 60)
    print(f"\n✅ WORKBUDDY_USER_ID: {uid}")
    print(f"\n⚠️  WORKBUDDY_ACCESS_TOKEN:")
    print("   accessToken 是加密的，请从浏览器开发者工具获取明文 token:")
    print("   1. 打开 WorkBuddy 客户端")
    print("   2. 按 F12 打开开发者工具")
    print("   3. 切换到 Network 标签")
    print("   4. 刷新页面或执行任意操作")
    print("   5. 找到请求 https://www.codebuddy.cn 的请求")
    print("   6. 查看 Request Headers 中的 Authorization: Bearer <token>")
    print("   7. 复制 token 值")
    print("\n" + "-" * 60)
    print("🔧 GitHub Secrets 配置")
    print("-" * 60)
    print("""
在工作仓库 Settings → Secrets and variables → Actions → New repository secret:

Secret 名称                      值
─────────────────────────────────────────────────────
WORKBUDDY_ACCESS_TOKEN      <从浏览器复制的明文 token>
WORKBUDDY_USER_ID           <上面显示的 uid>
FEISHU_WEBHOOK              <飞书群机器人 Webhook 地址>
FEISHU_WEBHOOK_SIGN         <飞书签名密钥，如无则留空>
""")
    if '--output' in sys.argv and sys.argv[sys.argv.index('--output') + 1] == 'json':
        result = {'WORKBUDDY_USER_ID': uid, 'AUTH_FILE': str(auth_file)}
        print("\n📄 JSON 格式（不含 token）:")
        print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
