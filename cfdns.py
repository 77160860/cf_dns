import re

IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")

def _parse_ipv4s_from_text(text: str):
    # 从任意文本中提取 IPv4，并做 0-255 简单校验与去重保序
    found = []
    seen = set()
    for m in re.findall(r"(?:\d{1,3}\.){3}\d{1,3}", text):
        parts = m.split(".")
        if all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            if m not in seen:
                seen.add(m)
                found.append(m)
    return found

def get_cf_speed_test_ip(timeout: int = 10, max_retries: int = 5, limit: int = 20):
    """从 HostMonit 获取优选 IP 列表（兼容 JSON/纯文本）"""
    url = "https://stock.hostmonit.com/CloudFlareYes"
    for attempt in range(1, max_retries + 1):
        try:
            log_message(f"正在从 {url} 获取优选IP... (尝试 {attempt}/{max_retries})")
            resp = requests.get(url, timeout=timeout)
            if not resp.ok:
                log_message(f"获取优选IP失败，状态码: {resp.status_code}")
                time.sleep(2)
                continue

            ips = []
            # 优先尝试 JSON
            try:
                payload = resp.json()
                # 可能是 {"data":[{ip:...}, ...]} 或 直接是列表
                candidates = []
                if isinstance(payload, dict) and "data" in payload:
                    candidates = payload.get("data") or []
                elif isinstance(payload, list):
                    candidates = payload
                else:
                    candidates = []

                for item in candidates:
                    if isinstance(item, dict):
                        ip = item.get("ip") or item.get("host") or item.get("address")
                        if isinstance(ip, str) and IPV4_RE.match(ip):
                            ips.append(ip)
                    elif isinstance(item, str) and IPV4_RE.match(item):
                        ips.append(item)
                # 去重保序
                if ips:
                    uniq = []
                    seen = set()
                    for ip in ips:
                        if ip not in seen:
                            seen.add(ip)
                            uniq.append(ip)
                    ips = uniq
            except ValueError:
                # 非 JSON 则按纯文本提取
                ips = _parse_ipv4s_from_text(resp.text)

            if ips:
                log_message(f"成功获取 {len(ips)} 个优选IP。按限制（{limit}个）返回。")
                return ips[:limit]
            else:
                log_message("返回内容未解析到有效 IPv4，继续重试。")
        except Exception as e:
            log_message(f"获取优选IP时发生异常: {e}")
        time.sleep(2)
    return None
