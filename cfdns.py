import requests
import traceback
import time
import os
import json
import re

# API 密钥
CF_API_TOKEN = os.environ["CF_API_TOKEN"]
CF_ZONE_ID   = os.environ["CF_ZONE_ID"]
CF_DNS_NAME  = os.environ["CF_DNS_NAME"]

# pushplus_token（可留空）
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")

headers = {
    'Authorization': f'Bearer {CF_API_TOKEN}',
    'Content-Type': 'application/json'
}

def _extract_ipv4s(text: str):
    # 提取 IPv4 地址，去重且保持顺序
    candidates = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', text)
    def valid(ip):
        try:
            parts = [int(p) for p in ip.split('.')]
            return len(parts) == 4 and all(0 <= p <= 255 for p in parts)
        except Exception:
            return False
    seen = set()
    result = []
    for ip in candidates:
        if valid(ip) and ip not in seen:
            seen.add(ip)
            result.append(ip)
    return result

def get_cf_ips_from_cloudflareyes(url="https://raw.githubusercontent.com/gslege/CloudflareIP/refs/heads/main/cfxyz.txt", timeout=10, max_retries=5):
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200 and resp.text:
                ips = _extract_ipv4s(resp.text)
                if ips:
                    return ips
        except Exception as e:
            traceback.print_exc()
            print(f"get_cf_ips_from_cloudflareyes failed ({attempt + 1}/{max_retries}): {e}")
    return []

def list_a_records(name):
    # 只拉取该名称的 A 记录
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records'
    params = {'type': 'A', 'name': name, 'per_page': 100}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            return r.json().get('result', [])
        print('Error fetching DNS records:', r.text)
    except Exception as e:
        print(f"list_a_records exception: {e}")
    return []

def delete_dns_record(record_id):
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{record_id}'
    try:
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"cf_dns_delete success: ---- Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} ---- id：{record_id}")
            return True
        else:
            print(f"cf_dns_delete ERROR: ---- Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} ---- STATUS: {r.status_code} ---- MESSAGE: {r.text}")
            return False
    except Exception as e:
        traceback.print_exc()
        print(f"cf_dns_delete EXCEPTION: ---- Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} ---- MESSAGE: {e}")
        return False

def delete_all_a_records(name):
    records = list_a_records(name)
    ok = True
    for rec in records:
        rid = rec.get('id')
        if rid:
            ok = delete_dns_record(rid) and ok
    return ok

def create_dns_record(name, cf_ip):
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records'
    data = {
        'type': 'A',
        'name': name,
        'content': cf_ip
        # 可按需：'proxied': False, 'ttl': 120
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        if resp.status_code == 200:
            print(f"cf_dns_create success: ---- Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} ---- ip：{cf_ip}")
            return f"ip:{cf_ip} 新增 {name} 成功"
        else:
            print(f"cf_dns_create ERROR: ---- Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} ---- STATUS: {resp.status_code} ---- MESSAGE: {resp.text}")
            return f"ip:{cf_ip} 新增 {name} 失败"
    except Exception as e:
        traceback.print_exc()
        print(f"cf_dns_create EXCEPTION: ---- Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} ---- MESSAGE: {e}")
        return f"ip:{cf_ip} 新增 {name} 失败"

def push_plus(content):
    if not PUSHPLUS_TOKEN:
        print("push_plus skipped: PUSHPLUS_TOKEN is empty")
        return
    url = 'http://www.pushplus.plus/send'
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": "IP优选DNSCF推送",
        "content": content,
        "template": "markdown",
        "channel": "wechat"
    }
    body = json.dumps(data).encode('utf-8')
    headers_local = {'Content-Type': 'application/json'}
    try:
        requests.post(url, data=body, headers=headers_local, timeout=10)
    except Exception as e:
        print(f"push_plus error: {e}")

def main():
    # 1) 抓取 CloudFlareYes 页面里的 IPv4 列表
    ip_addresses = get_cf_ips_from_cloudflareyes()
    if not ip_addresses:
        print("Error: 未从 CloudFlareYes 获取到任何 IP")
        return

    # 可选：限制最大创建数量（不设置则使用全部抓到的 IP）
    max_records_env = os.getenv("CF_MAX_RECORDS")
    target_ips = ip_addresses[:int(max_records_env)] if max_records_env else ip_addresses

    # 2) 删除该名称下的全部 A 记录
    if not delete_all_a_records(CF_DNS_NAME):
        print("Error: 删除现有 A 记录时出现错误（已尽力删除继续执行）")

    # 3) 按抓到的 IP 数量逐条创建 A 记录
    results = []
    for ip in target_ips:
        results.append(create_dns_record(CF_DNS_NAME, ip))

    # 4) 推送结果
    if results:
        push_plus('\n'.join(results))

if __name__ == '__main__':
    main()
