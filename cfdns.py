import os
import re
import json
import time
import traceback
import requests

# 环境变量（缺失时给出清晰错误）
def require_env(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing env var: {key}")
    return val

# 必需环境变量
CF_API_TOKEN   = require_env("CF_API_TOKEN")
CF_ZONE_ID     = require_env("CF_ZONE_ID")
CF_DNS_NAME    = require_env("CF_DNS_NAME")
# 可选：未设置则跳过 PushPlus 推送
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")

# 可选增强项：拉取 Hostmonit 的备用 URL / 代理 / 兜底 IP
CFY_URLS_ENV = os.getenv("CFY_URLS", "").strip()
CFY_PROXY    = os.getenv("CFY_PROXY", "").strip()
FALLBACK_IPS = os.getenv("FALLBACK_IPS", "").strip()

API_BASE = "https://api.cloudflare.com/client/v4"
REQ_TIMEOUT = 10

headers = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json",
}

# IPv4 校验
ipv4_re = re.compile(r"^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$")
def is_ipv4(s: str) -> bool:
    return bool(ipv4_re.match(s.strip()))

def parse_ipv4_from_text(text: str):
    ips = re.findall(
        r"\b(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b",
        text or ""
    )
    cleaned, seen = [], set()
    for ip in (i.strip() for i in ips):
        if ip and is_ipv4(ip) and ip not in seen:
            cleaned.append(ip)
            seen.add(ip)
    return cleaned

def get_cf_speed_test_ip(timeout=10, max_retries=5):
    """
    从 stock.hostmonit 获取优选 IP 列表，尽量规避 403。
    - 支持自定义 URL 列表（CFY_URLS）
    - 支持出站代理（CFY_PROXY）
    - 失败时可用 FALLBACK_IPS 兜底
    返回去重后的 IPv4 列表（保序）。
    """
    if CFY_URLS_ENV:
        urls = [u.strip() for u in CFY_URLS_ENV.split(",") if u.strip()]
    else:
        urls = [
            "https://stock.hostmonit.com/CloudFlareYes",
            "http://stock.hostmonit.com/CloudFlareYes",
        ]

    session = requests.Session()
    browser_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://stock.hostmonit.com/CF-IP/",
        "Origin": "https://stock.hostmonit.com",
        "Connection": "keep-alive",
        "X-Requested-With": "XMLHttpRequest",
    }

    proxies = None
    if CFY_PROXY:
        proxies = {"http": CFY_PROXY, "https": CFY_PROXY}

    last_err = None
    for attempt in range(1, max_retries + 1):
        for url in urls:
            try:
                r = session.get(
                    url,
                    headers=browser_headers,
                    timeout=timeout,
                    allow_redirects=True,
                    proxies=proxies,
                )
                if r.status_code != 200 or not r.text:
                    raise RuntimeError(f"HTTP {r.status_code}")

                ips = []

                # 优先尝试 JSON（常见：{"status":"success","data":[{"ip":"x.x.x.x",...}] }）
                try:
                    data = r.json()
                    if isinstance(data, dict):
                        items = (
                            data.get("data")
                            or data.get("ips")
                            or data.get("result")
                            or data.get("list")
                            or []
                        )
                        if isinstance(items, list):
                            for item in items:
                                if isinstance(item, dict):
                                    val = item.get("ip") or item.get("host") or item.get("address") or ""
                                    if val:
                                        ips.append(val)
                                elif isinstance(item, str):
                                    ips.append(item)
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                val = item.get("ip") or item.get("host") or item.get("address") or ""
                                if val:
                                    ips.append(val)
                            elif isinstance(item, str):
                                ips.append(item)
                except ValueError:
                    # 非 JSON，走文本回退
                    pass

                # 文本回退：从响应中提取 IPv4
                if not ips:
                    ips = parse_ipv4_from_text(r.text)

                # 规范化去重保序
                cleaned, seen = [], set()
                for ip in (i.strip() for i in ips):
                    if ip and is_ipv4(ip) and ip not in seen:
                        cleaned.append(ip)
                        seen.add(ip)

                if cleaned:
                    return cleaned
                else:
                    raise RuntimeError("no IPv4 parsed")
            except Exception as e:
                last_err = e
                print(f"get_cf_speed_test_ip failed ({attempt}/{max_retries}) url={url}: {e}")
                continue
        time.sleep(1)

    # 若完全失败，尝试 FALLBACK_IPS
    if FALLBACK_IPS:
        fallback_list = parse_ipv4_from_text(FALLBACK_IPS.replace(",", " "))
        if fallback_list:
            print("使用 FALLBACK_IPS 兜底。")
            return fallback_list

    if last_err:
        traceback.print_exc()
    return []

def get_dns_records(name: str, rtype: str = "A"):
    """
    精确按名称与类型拉取 DNS 记录，返回记录字典列表（包含 id、name、type、ttl、proxied 等）
    """
    url = f"{API_BASE}/zones/{CF_ZONE_ID}/dns_records"
    params = {"type": rtype, "name": name, "per_page": 100}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=REQ_TIMEOUT)
        if r.ok:
            data = r.json()
            if data.get("success"):
                return data.get("result", [])
            else:
                print("获取 DNS 记录失败:", data)
        else:
            print("获取 DNS 记录 HTTP 错误:", r.status_code, r.text)
    except Exception:
        traceback.print_exc()
    return []

def update_dns_record(record: dict, ip: str):
    """
    根据已有记录字典更新 IP，保留原有属性，返回人类可读字符串结果
    """
    record_id = record["id"]
    url = f"{API_BASE}/zones/{CF_ZONE_ID}/dns_records/{record_id}"

    payload = {
        "type": record.get("type", "A"),
        "name": record["name"],
        "content": ip,
        "ttl": record.get("ttl", 1),            # 1 表示自动
        "proxied": record.get("proxied", False) # 保留原状态
    }

    try:
        r = requests.put(url, headers=headers, json=payload, timeout=REQ_TIMEOUT)
        ok = False
        if r.ok:
            try:
                body = r.json()
                ok = body.get("success", False)
            except ValueError:
                ok = False

        if ok:
            print(f"cf_dns_change success: {time.strftime('%Y-%m-%d %H:%M:%S')} ip:{ip}")
            return f"ip:{ip} 解析 {record['name']} 成功"
        else:
            print(f"cf_dns_change ERROR: {time.strftime('%Y-%m-%d %H:%M:%S')} status={r.status_code} body={r.text}")
            return f"ip:{ip} 解析 {record['name']} 失败"
    except Exception:
        traceback.print_exc()
        return f"ip:{ip} 解析 {record['name']} 失败"

def push_plus(content: str):
    if not content:
        return
    if not PUSHPLUS_TOKEN:
        print("PUSHPLUS_TOKEN 未设置，跳过 PushPlus 推送。")
        return
    url = "http://www.pushplus.plus/send"
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": "IP优选DNSCF推送",
        "content": content,
        "template": "markdown",
        "channel": "wechat",
    }
    try:
        r = requests.post(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=REQ_TIMEOUT
        )
        if not r.ok:
            print("pushplus failed:", r.status_code, r.text)
    except Exception:
        traceback.print_exc()

def main():
    # 获取最新优选 IP 列表
    ip_addresses = get_cf_speed_test_ip()
    if not ip_addresses:
        print("未获取到有效 IP，终止。")
        return

    # 获取目标域名的 A 记录
    dns_records = get_dns_records(CF_DNS_NAME, "A")
    if not dns_records:
        print("错误：未找到域名的 A 记录：", CF_DNS_NAME)
        return

    # 逐个更新（按最小数量对齐）
    num_ips = min(len(ip_addresses), len(dns_records))
    msgs = []
    for i in range(num_ips):
        ip = ip_addresses[i].strip()
        msg = update_dns_record(dns_records[i], ip)
        msgs.append(msg)

    push_plus("\n".join(msgs))

if __name__ == "__main__":
    main()
