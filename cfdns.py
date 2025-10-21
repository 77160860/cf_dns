# 从 stock.hostmonit.com 获取IP ---
import requests
import traceback
import time
import os
import json
from bs4 import BeautifulSoup # 必须导入这个库来解析网页

# --- 从环境变量获取配置 ---
try:
CF_API_TOKEN = os.environ["CF_API_TOKEN"]
CF_ZONE_ID = os.environ["CF_ZONE_ID"]
CF_DNS_NAME = os.environ["CF_DNS_NAME"]
# PUSHPLUS_TOKEN 是可选的
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN")
except KeyError as e:
print(f"错误：环境变量 {e} 未设置，请在 GitHub Secrets 中配置。")
exit(1)

# --- Cloudflare API 配置 ---
headers = {
'Authorization': f'Bearer {CF_API_TOKEN}',
'Content-Type': 'application/json'
}

# --- 函数定义 ---

def log_message(message):
"""带时间戳的日志记录"""
print(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] {message}")

def get_cf_speed_test_ip(timeout=10, max_retries=5, limit=20):
"""从 stock.hostmonit.com 获取优选IP列表"""
# 目标IP源URL
url = 'https://stock.hostmonit.com/CloudFlareYes'
for attempt in range(max_retries):
try:
log_message(f"正在从 {url} 获取优选IP... (尝试 {attempt + 1}/{max_retries})")
response = requests.get(url, timeout=timeout)

if response.status_code == 200:
# 使用BeautifulSoup解析HTML
soup = BeautifulSoup(response.text, 'lxml')
# 找到id为'result'的textarea
textarea = soup.find('textarea', id='result')

if textarea:
# 获取textarea中的文本内容，并按行分割
ips_text = textarea.get_text()
# 按行分割，并去除每个IP地址前后可能存在的空格
ips = [ip.strip() for ip in ips_text.strip().split('\n') if ip.strip()]

log_message(f"成功获取 {len(ips)} 个优选IP。")

# 限制返回的IP数量，取前 limit 个
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

time.sleep(2) # 等待2秒后重试
return None


def get_dns_record_ids(name):
"""获取指定名称的所有DNS记录ID"""
url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records?type=A&name={name}'
try:
response = requests.get(url, headers=headers)
if response.status_code == 200:
records = response.json().get('result', [])
record_ids = [rec['id'] for rec in records]
log_message(f"找到 {len(record_ids)} 条关于 {name} 的已存在DNS记录。")
return record_ids
else:
log_message(f"获取DNS记录时出错: {response.status_code} - {response.text}")
return []
except Exception as e:
log_message(f"获取DNS记录时发生异常: {e}")
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
'ttl': 60,  # 使用较短的TTL，60秒，以确保快速更新
'proxied': False # 通常优选IP需要设置为DNS Only模式
}
try:
response = requests.post(url, headers=headers, json=data)
if response.status_code == 200:
log_message(f"成功为 {name} 创建新的DNS记录，指向 -> {ip}")
return f"为 {name} 指向 {ip} [成功]"
else:
log_message(f"为 {name} 创建指向 {ip} 的记录失败: {response.status_code} - {response.text}")
return f"为 {name} 指向 {ip} [失败]"
except Exception as e:
log_message(f"创建DNS记录时发生异常: {e}")
return f"为 {name} 指向 {ip} [异常]"

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
requests.post(url, json=data)
log_message("PushPlus消息已发送。")
except Exception as e:
log_message(f"PushPlus消息发送异常: {e}")

# --- 主函数 ---
def main():
log_message("--- 开始执行Cloudflare优选IP DNS更新任务 ---")

# 1. 获取最新优选IP
new_ips = get_cf_speed_test_ip()
if not new_ips:
log_message("未能获取到优选IP，任务终止。")
push_plus("未能获取到优选IP，请检查IP源或网络连接。")
return

# 2. 获取当前域名已有的DNS记录ID
existing_record_ids = get_dns_record_ids(CF_DNS_NAME)

# 3. 删除所有旧的记录
if existing_record_ids:
log_message("开始删除旧的DNS记录...")
for record_id in existing_record_ids:
delete_dns_record(record_id)
else:
log_message("没有找到需要删除的旧记录。")

# 4. 创建所有新的记录
log_message("开始创建新的DNS记录...")
push_results = []
for ip in new_ips:
result = create_dns_record(CF_DNS_NAME, ip)
push_results.append(result)

# 5. 发送推送通知
summary = f"**DNS更新完成**\n\n域名: `{CF_DNS_NAME}`\n\n**操作详情:**\n" + "\n".join(f"- {res}" for res in push_results)
push_plus(summary)

log_message("--- 任务执行完毕 ---")

if __name__ == '__main__':
main()
