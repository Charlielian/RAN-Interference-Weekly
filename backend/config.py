# -*- coding: utf-8 -*-
"""
全局配置模块
"""
import os
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    # 打包为 exe 后的运行目录（可执行文件所在目录）
    BASE_DIR = Path(sys.executable).parent.resolve()
    # PyInstaller 解压临时目录（静态资源等挂载点）
    RESOURCE_DIR = Path(getattr(sys, '_MEIPASS', BASE_DIR)).resolve()
else:
    BASE_DIR = Path(__file__).parent.parent.resolve()
    RESOURCE_DIR = BASE_DIR

# 目录配置（存储于用户运行目录，方便查看生成文件与配置）
COOKIE_DIR = os.path.join(BASE_DIR, "cookies")
CAPTCHA_DIR = os.path.join(BASE_DIR, "captcha_images")
LOG_DIR = os.path.join(BASE_DIR, "logs")
DATA_DIR = os.path.join(BASE_DIR, "data")
SOURCE_DIR = os.path.join(DATA_DIR, "source")
SOURCE_4G_DIR = os.path.join(SOURCE_DIR, "4G干扰文件")
SOURCE_5G_DIR = os.path.join(SOURCE_DIR, "5G干扰文件")
REPORT_DIR = os.path.join(DATA_DIR, "reports")
# 静态前端资源目录
STATIC_DIR = os.path.join(RESOURCE_DIR, "static")

# 确保所有目录存在
for d in [COOKIE_DIR, CAPTCHA_DIR, LOG_DIR, DATA_DIR, SOURCE_DIR, SOURCE_4G_DIR, SOURCE_5G_DIR, REPORT_DIR]:
    os.makedirs(d, exist_ok=True)

# 大数据平台 URL 配置
NQI_BASE_URL = 'https://nqi.gmcc.net:20443'
# CAS 登录页（与 Nqi导出工具_new 对齐，携带 service 参数才能获取到完整登录表单）
LOGIN_URL = f'{NQI_BASE_URL}/cas/login?service={NQI_BASE_URL}/pro-portal/'
# 图形验证码接口（旧路径 /cas/images/kaptcha.jpg 已失效，会返回 403）
CAPTCHA_URL = f'{NQI_BASE_URL}/cas/captcha.jpg'
# 图形验证码校验接口
GET_CONFIG_URL = f'{NQI_BASE_URL}/cas/getConfig'
# 短信验证码发送接口
SEND_CODE_URL = f'{NQI_BASE_URL}/cas/sendCode1'
JXCX_URL = f'{NQI_BASE_URL}/pro-adhoc/adhocquery/getTable'
JXCX_COUNT_URL = f'{NQI_BASE_URL}/pro-adhoc/adhocquery/getTableCount'

# 网络请求头（与 Nqi导出工具_new 对齐）
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Origin': NQI_BASE_URL,
    'Referer': f'{NQI_BASE_URL}/pro-adhoc/',
    'x-requested-with': 'XMLHttpRequest',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
}

HEADERS_JSON = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36',
    'Content-Type': 'application/json'
}

# CAS 登录页导航请求头（用于 GET 登录页/验证码，避免被 WAF 拒绝）
HEADERS_HTML = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': f'{NQI_BASE_URL}/',
    'Connection': 'keep-alive',
}

# 默认账号与密码配置（优先读取环境变量或外部 yaml）
DEFAULT_USERNAME = os.environ.get('NQI_USERNAME', '')
DEFAULT_PASSWORD = os.environ.get('NQI_PASSWORD', '')

# 全省 21 地市分类
CITY_CLASS = {
    "一类": ["广州", "深圳", "东莞", "佛山"],
    "二类": ["惠州", "珠海", "中山", "汕头", "湛江", "江门", "茂名", "揭阳"],
    "三类": ["清远", "肇庆", "梅州", "韶关", "河源", "潮州", "阳江", "汕尾", "云浮"],
}
ALL_CITIES = [c for v in CITY_CLASS.values() for c in v]
