# -*- coding: utf-8 -*-
"""
全局配置模块
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.resolve()

# 目录配置
COOKIE_DIR = os.path.join(BASE_DIR, "cookies")
CAPTCHA_DIR = os.path.join(BASE_DIR, "captcha_images")
LOG_DIR = os.path.join(BASE_DIR, "logs")
DATA_DIR = os.path.join(BASE_DIR, "data")
SOURCE_DIR = os.path.join(DATA_DIR, "source")
SOURCE_4G_DIR = os.path.join(SOURCE_DIR, "4G干扰文件")
SOURCE_5G_DIR = os.path.join(SOURCE_DIR, "5G干扰文件")
REPORT_DIR = os.path.join(DATA_DIR, "reports")

# 确保所有目录存在
for d in [COOKIE_DIR, CAPTCHA_DIR, LOG_DIR, DATA_DIR, SOURCE_DIR, SOURCE_4G_DIR, SOURCE_5G_DIR, REPORT_DIR]:
    os.makedirs(d, exist_ok=True)

# 大数据平台 URL 配置
NQI_BASE_URL = 'https://nqi.gmcc.net:20443'
LOGIN_URL = f'{NQI_BASE_URL}/cas/login'
CAPTCHA_URL = f'{NQI_BASE_URL}/cas/images/kaptcha.jpg'
GET_CONFIG_URL = f'{NQI_BASE_URL}/cas/login/getConfig'
SEND_CODE_URL = f'{NQI_BASE_URL}/cas/login/sendCode'
JXCX_URL = f'{NQI_BASE_URL}/pro-adhoc/adhocquery/getTable'
JXCX_COUNT_URL = f'{NQI_BASE_URL}/pro-adhoc/adhocquery/getTableCount'

# 网络请求头
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
}

HEADERS_JSON = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Content-Type': 'application/json;charset=UTF-8',
    'X-Requested-With': 'XMLHttpRequest',
    'Origin': NQI_BASE_URL,
    'Referer': f'{NQI_BASE_URL}/cas/login',
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
