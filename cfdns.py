import requests
import traceback
import time
import os
import json
from bs4 import BeautifulSoup

# --- 使用 try...except 块安全地读取配置 ---
try:
    # 必需的环境变量 (已正确缩进)
    CF_API_TOKEN = os.environ["CF_API_TOKEN"]
    CF_ZONE_ID = os.environ["CF_ZONE_ID"]
    CF_DNS_NAME = os.environ["CF_DNS_NAME"]
    # 可选的环境变量
    PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN")
except KeyError as e:
    print(f"错误：必需的环境变量 {e} 未设置，请检查配置。")
    exit(1)

headers = {
    'Authorization': f'Bearer {CF_API_TOKEN}',
    'Content-Type': 'application/json'
}

def log_message(message):
    """带时间戳的日志记录函数"""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def get_cf_speed_test_ip(timeout=10, max_retries=5, limit=20):
    """从 stock.hostmonit.com 获取优选IP列表"""
    url = 'https://stock.hostmonit.com/CloudFlareYes'
    for attempt in range(max_retries):
        try:
            log_message(f"正在从 {url} 获取优选IP... (尝试 {attempt + 1}/{max_retries})")
            response = requests.get(url, timeout=timeout)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'lxml')
                textarea = soup.find('textarea', id='result')

                if textarea:
                    ips_text = textarea.get_text()
                    ips = [ip.strip() for ip in ips_text.strip().split('\n') if ip.strip()]
                    log_message(f"成功获取 {len(ips)} 个优选IP。")
                    
                    limited_ips = ips[:limit]
                    log_message(f"按限制（{limit}个）返回IP列表。")
                    return limited_ips
                else:
                    log_message("在页面中未找到ID为'result'的textarea元素。")
            else:
                log_message(f"获取优选IP失败，状态码: {response.status_code}")
        except Exception as e:
            log_message(f"获取优选IP时发生异常: {e}")
            traceback.print_exc()
        time.sleep(2)
    return None

def get_dns_record_ids(name):
    """获取指定名称的所有A记录ID"""
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records?type=A&name={name}'
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            records = response.json().get('result', [])
            record_ids = [rec['id'] for rec in records]
            log_message(f"找到 {len(record_ids)} 条关于 {name} 的已存在DNS记录。")
            return record_ids
        else:
            log_message(f"获取DNS记录ID时出错: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        log_message(f"获取DNS记录ID时发生异常: {e}")
        return []

def delete_dns_record(record_id):
    """删除指定的DNS记录"""
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{record_id}'
    try:
        response = requests.delete(url, headers=headers)
        if response.status_code == 200:
            log_message(f"成功删除旧的DNS记录: {record_id}")
            return True
        else:
            log_message(f"删除DNS记录 {record_id} 失败: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        log_message(f"删除DNS记录时发生异常: {e}")
        return False

def create_dns_record(name, ip):
    """创建新的A类型DNS记录"""
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records'
    data = {
        'type': 'A',
        'name': name,
        'content': ip,
        'ttl': 60,
        'proxied': False
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            log_message(f"成功为 {name} 创建新DNS记录，指向 -> {ip}")
            return f"为 {name} 指向 {ip} [创建成功]"
        else:
            log_message(f"为 {name} 创建指向 {ip} 的记录失败: {response.status_code} - {response.text}")
            return f"为 {name} 指向 {ip} [创建失败]"
    except Exception as e:
        log_message(f"创建DNS记录时发生异常: {e}")
        return f"为 {name} 指向 {ip} [创建异常]"

def push_plus(content):
    """通过PushPlus发送消息"""
    if not PUSHPLUS_TOKEN:
        log_message("未配置 PUSHPLUS_TOKEN，跳过消息推送。")
        return

    url = 'http://www.pushplus.plus/send'
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": "Cloudflare优选IP更新通知",
        "content": content,
        "template": "markdown"
    }
    try:
        response = requests.post(url, json=data)
        if response.json().get('code') == 200:
            log_message("PushPlus消息已发送。")
        else:
            log_message(f"PushPlus消息发送失败: {response.text}")
    except Exception as e:
        log_message(f"PushPlus消息发送异常: {e}")

def main():
    log_message("--- 开始执行Cloudflare优选IP DNS更新任务 (删除并重建模式) ---")

    new_ips = get_cf_speed_test_ip()
    if not new_ips:
        log_message("未能获取到优选IP，任务终止。")
        push_plus("未能获取到优选IP，请检查IP源或网络连接。")
        return

    existing_record_ids = get_dns_record_ids(CF_DNS_NAME)
    delete_count = 0
    if existing_record_ids:
        log_message("--- 开始删除阶段 ---")
        for record_id in existing_record_ids:
            if delete_dns_record(record_id):
                delete_count += 1
        log_message(f"--- 删除阶段结束，共删除了 {delete_count} 条记录 ---")
    else:
        log_message("没有找到需要删除的旧记录。")

    log_message("--- 开始创建阶段 ---")
    push_results = []
    create_count = 0
    for ip in new_ips:
        result = create_dns_record(CF_DNS_NAME, ip)
        push_results.append(result)
        if "成功" in result:
            create_count += 1
    log_message(f"--- 创建阶段结束，共创建了 {create_count} 条记录 ---")

    summary = (
        f"**DNS更新完成 (删除并重建)**\n\n"
        f"域名: `{CF_DNS_NAME}`\n"
        f"删除了 {delete_count} 条旧记录\n"
        f"创建了 {create_count} 条新记录\n\n"
        f"**操作详情:**\n" + "\n".join(f"- {res}" for res in push_results)
    )
    push_plus(summary)

    log_message("--- 任务执行完毕 ---")

if __name__ == '__main__':
    main()

