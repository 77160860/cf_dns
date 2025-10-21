import requests
import traceback
import time
import os
import json
import re

# API 密钥
CF_API_TOKEN    = os.environ["CF_API_TOKEN"]
CF_ZONE_ID      = os.environ["CF_ZONE_ID"]
CF_DNS_NAME     = os.environ["CF_DNS_NAME"]

# pushplus_token
PUSHPLUS_TOKEN  = os.environ["PUSHPLUS_TOKEN"]

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

def get_cf_ips_from_cloudflareyes(url="https://cf.090227.xyz/CloudFlareYes", timeout=10, max_retries=5):
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

# 获取 DNS 记录
def get_dns_records(name):
    def_info = []
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records'
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        records = response.json().get('result', [])
        for record in records:
            if record.get('name') == name:
                def_info.append(record.get('id'))
        return def_info
    else:
        print('Error fetching DNS records:', response.text)
        return []

# 更新 DNS 记录
def update_dns_record(record_id, name, cf_ip):
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{record_id}'
    data = {
        'type': 'A',
        'name': name,
        'content': cf_ip
        # 如需代理或 TTL，可按需增加：'proxied': False, 'ttl': 120
    }

    try:
        response = requests.put(url, headers=headers, json=data)
        if response.status_code == 200:
            print(f"cf_dns_change success: ---- Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} ---- ip：{cf_ip}")
            return f"ip:{cf_ip} 解析 {name} 成功"
        else:
            print(f"cf_dns_change ERROR: ---- Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} ---- STATUS: {response.status_code} ---- MESSAGE: {response.text}")
            return f"ip:{cf_ip} 解析 {name} 失败"
    except Exception as e:
        traceback.print_exc()
        print(f"cf_dns_change EXCEPTION: ---- Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} ---- MESSAGE: {e}")
        return f"ip:{cf_ip} 解析 {name} 失败"

# 消息推送
def push_plus(content):
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
    # 从 CloudFlareYes 页面抓取优选 IP（IPv4）
    ip_addresses = get_cf_ips_from_cloudflareyes()
    if not ip_addresses:
        print("Error: 未从 CloudFlareYes 获取到任何 IP")
        return

    dns_records = get_dns_records(CF_DNS_NAME)
    if not dns_records:
        print("Error: No DNS records found for", CF_DNS_NAME)
        return

    # 保持数量一致：不要超过 DNS 记录数量
    num_ips = min(len(ip_addresses), len(dns_records))

    push_plus_content = []
    for index in range(num_ips):
        ip_address = ip_addresses[index]
        # 执行 DNS 变更
        dns = update_dns_record(dns_records[index], CF_DNS_NAME, ip_address)
        push_plus_content.append(dns)

    if push_plus_content:
        push_plus('\n'.join(push_plus_content))

if __name__ == '__main__':
    main()
