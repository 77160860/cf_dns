默认接口:https://ip.164746.xyz 

可选接口:
https://ip.164746.xyz/ipTop10.html 

https://stock.hostmonit.com/CloudFlareYes
#### 配置方法
1. fork本项目
2. 打开项目的settings，Actions secrets and variables，action  ，new  Repository secrets 逐个添加以下的内容
4. 添加 CF_API_TOKEN(进入cf后在域名-概述，点击获取您的api令牌，创建模板编辑dns令牌得到的才是)，CF_ZONE_ID（域名-概述里那个区域id就是），CF_DNS_NAME（你自己的域名或新子域名会自动创建），PUSHPLUS_TOKEN（PUSHPLUS消息通知。https://www.pushplus.plus/push1.html）。
#### 测试运行
返回action，打开cf_dns_push,运行run workflow。
#### 时间设定，
在项目中的.github/workflows中有个main.yml默认的是4小时执行一次。
