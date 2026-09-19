# -*- coding: utf-8 -*-
"""
Web端登录状态机
支持图形验证码获取、刷新、提交以及短信验证码发送与提交，支持Cookie持久化与复用
"""
import json
import time
import base64
import secrets
import logging
import threading
import requests
import urllib3
from lxml import etree

from backend.config import (
    NQI_BASE_URL, LOGIN_URL, CAPTCHA_URL, GET_CONFIG_URL, SEND_CODE_URL,
    HEADERS, HEADERS_JSON, DEFAULT_USERNAME, DEFAULT_PASSWORD
)
from utils.crypto import rsa_encrypt
from utils.helpers import save_cookie, load_cookie, delete_cookie

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

_web_login_contexts = {}
_web_login_lock = threading.Lock()
TIMEOUT_SHORT = 10
TIMEOUT_MEDIUM = 30


class _LoginContext:
    def __init__(self, login_id, username, password):
        self.login_id = login_id
        self.username = username
        self.password = password
        self.sess = requests.Session()
        self.sess.verify = False
        self.execution = None
        self.public_key = None
        self.username_e = None
        self.password_e = None
        self.captcha_code = None
        self.captcha_bytes = None
        self.sms_sent = False
        self.logged_in = False
        self.created_at = time.time()
        self.last_active = time.time()


def _gc_web_login_contexts():
    now = time.time()
    with _web_login_lock:
        to_del = [lid for lid, ctx in _web_login_contexts.items() if now - ctx.last_active > 900]
        for lid in to_del:
            _web_login_contexts.pop(lid, None)


class WebLoginManager:
    @staticmethod
    def check_saved_session(username: str):
        """检查保存的Cookie是否仍然有效"""
        saved_cookie = load_cookie(username)
        if not saved_cookie:
            return False, None, "未找到保存的Cookie凭证"
        
        sess = requests.Session()
        sess.verify = False
        sess.cookies = saved_cookie
        
        try:
            url = f'{NQI_BASE_URL}/pro-wfm-biz-server/cas/login/info'
            res = sess.get(url, headers=HEADERS, timeout=TIMEOUT_SHORT)
            if res.status_code == 200:
                try:
                    data = json.loads(res.text)
                    if isinstance(data, dict) and data.get('data', {}).get('loginId') == username:
                        return True, sess, "Cookie验证有效，自动登录成功"
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"检查保存Cookie失败: {e}")
        
        return False, None, "保存的Cookie已失效，请重新登录"

    @staticmethod
    def begin(username: str = None, password: str = None) -> dict:
        _gc_web_login_contexts()
        user = username or DEFAULT_USERNAME
        pwd = password or DEFAULT_PASSWORD
        login_id = secrets.token_urlsafe(24)
        ctx = _LoginContext(login_id, user, pwd)

        try:
            res = ctx.sess.get(LOGIN_URL, headers=HEADERS, timeout=TIMEOUT_SHORT)
            res.encoding = 'utf-8'
            html = etree.HTML(res.text)

            exec_nodes = html.xpath('//*[@id="fm1"]/div[4]/input[1]')
            if not exec_nodes:
                return {"login_id": login_id, "captcha_base64": "", "success": False, "message": "无法解析 CAS 登录页（未找到 execution）"}
            ctx.execution = exec_nodes[0].attrib.get('value')

            scripts = html.xpath('//*[@type="text/javascript"]/text()')
            pk_found = None
            for s in scripts:
                if 'setPublicKey(' in s:
                    try:
                        pk_found = s.split('setPublicKey("')[1].split('")')[0]
                        break
                    except Exception:
                        continue
            if not pk_found:
                return {"login_id": login_id, "captcha_base64": "", "success": False, "message": "无法解析 CAS 登录页（未找到公钥）"}
            ctx.public_key = pk_found
            ctx.username_e = rsa_encrypt(ctx.username, ctx.public_key)
            ctx.password_e = rsa_encrypt(ctx.password, ctx.public_key)

            captcha_res = ctx.sess.get(CAPTCHA_URL, timeout=TIMEOUT_SHORT)
            if captcha_res.status_code != 200 or len(captcha_res.content) < 100:
                return {"login_id": login_id, "captcha_base64": "", "success": False, "message": f"获取验证码失败（HTTP {captcha_res.status_code}）"}
            
            ctx.captcha_bytes = captcha_res.content
            captcha_b64 = base64.b64encode(captcha_res.content).decode('ascii')

            with _web_login_lock:
                _web_login_contexts[login_id] = ctx

            return {
                "login_id": login_id,
                "captcha_base64": f"data:image/jpeg;base64,{captcha_b64}",
                "success": True,
                "message": "已获取验证码，请在界面输入验证码",
            }
        except Exception as e:
            return {"login_id": login_id, "captcha_base64": "", "success": False, "message": f"初始化登录失败: {e}"}

    @staticmethod
    def _get_ctx(login_id: str):
        with _web_login_lock:
            ctx = _web_login_contexts.get(login_id)
            if ctx is not None:
                ctx.last_active = time.time()
        return ctx

    @staticmethod
    def refresh_captcha(login_id: str) -> dict:
        ctx = WebLoginManager._get_ctx(login_id)
        if ctx is None:
            return {"success": False, "message": "登录会话已过期，请重新登录", "captcha_base64": ""}
        try:
            captcha_res = ctx.sess.get(CAPTCHA_URL, timeout=TIMEOUT_SHORT)
            if captcha_res.status_code != 200:
                return {"success": False, "message": f"获取验证码失败（HTTP {captcha_res.status_code}）", "captcha_base64": ""}
            ctx.captcha_bytes = captcha_res.content
            ctx.captcha_code = None
            captcha_b64 = base64.b64encode(captcha_res.content).decode('ascii')
            return {
                "success": True,
                "captcha_base64": f"data:image/jpeg;base64,{captcha_b64}",
                "message": "已刷新验证码",
            }
        except Exception as e:
            return {"success": False, "message": f"刷新验证码异常: {e}", "captcha_base64": ""}

    @staticmethod
    def submit_captcha(login_id: str, captcha_code: str) -> dict:
        ctx = WebLoginManager._get_ctx(login_id)
        if ctx is None:
            return {"success": False, "message": "登录会话已过期，请重新登录"}
        code = (captcha_code or "").strip()
        if not code:
            return {"success": False, "message": "验证码不能为空"}

        try:
            data = {
                'password': ctx.password_e,
                'loginId': ctx.username_e,
                'captcha': code,
            }
            res = ctx.sess.post(GET_CONFIG_URL, data=json.dumps(data), headers=HEADERS_JSON, timeout=TIMEOUT_SHORT)
            if res.status_code != 200:
                return {"success": False, "message": f"图形验证码校验请求异常（HTTP {res.status_code}）"}
            result = json.loads(res.text)
            if result.get('code') == '1':
                ctx.captcha_code = code
                return {"success": True, "message": "图形验证码正确，请获取并输入短信验证码", "need_sms": True}
            else:
                msg = result.get('message') or result.get('msg') or "图形验证码错误"
                return {"success": False, "message": msg, "retry": True}
        except Exception as e:
            return {"success": False, "message": f"校验验证码异常: {e}"}

    @staticmethod
    def send_sms_code(login_id: str) -> dict:
        ctx = WebLoginManager._get_ctx(login_id)
        if ctx is None:
            return {"success": False, "message": "登录会话已过期"}
        if not ctx.captcha_code:
            return {"success": False, "message": "请先完成图形验证码校验"}
        try:
            data_sms = {'loginId': ctx.username_e, 'password': ctx.password_e}
            res_sms = ctx.sess.post(SEND_CODE_URL, data=json.dumps(data_sms), headers=HEADERS_JSON, timeout=TIMEOUT_MEDIUM)
            if res_sms.status_code != 200:
                return {"success": False, "message": f"发送短信请求失败（HTTP {res_sms.status_code}）"}
            result_sms = json.loads(res_sms.text)
            ok = (result_sms.get('msg') == 'success' or result_sms.get('code') == '1' or result_sms.get('success') is True)
            ctx.sms_sent = True
            if ok:
                return {"success": True, "message": "短信验证码已发送至手机，请注意查收", "sms_sent": True}
            else:
                msg = result_sms.get('message') or result_sms.get('msg') or "短信验证码发送失败"
                return {"success": False, "message": msg, "sms_sent": False}
        except Exception as e:
            return {"success": False, "message": f"发送短信失败: {e}", "sms_sent": False}

    @staticmethod
    def submit_msg_code(login_id: str, msg_code: str, persist_cookie: bool = True):
        ctx = WebLoginManager._get_ctx(login_id)
        if ctx is None:
            return False, None, "登录会话已过期，请重新登录"
        if not ctx.captcha_code:
            return False, None, "请先完成图形验证码校验"
        code = (msg_code or "").strip()
        if not code:
            return False, None, "短信验证码不能为空"

        try:
            login_data = {
                'password': ctx.password_e,
                'username': ctx.username_e,
                'msgCode': code,
                'captcha': ctx.captcha_code,
                'uuid': '',
                'execution': ctx.execution,
                '_eventId': 'submit',
                'geolocation': ''
            }
            res_login = ctx.sess.post(LOGIN_URL, data=login_data, headers=HEADERS, timeout=TIMEOUT_MEDIUM)

            if ctx.sess.cookies.get('CASTGC'):
                ctx.logged_in = True
                if persist_cookie:
                    try:
                        save_cookie(ctx.sess.cookies, ctx.username)
                    except Exception as ce:
                        logger.warning(f"保存Cookie异常: {ce}")
                with _web_login_lock:
                    _web_login_contexts.pop(login_id, None)
                return True, ctx.sess, "登录成功"
            else:
                return False, None, "短信验证码错误或登录凭证获取失败，请重试"
        except Exception as e:
            return False, None, f"登录请求异常: {e}"
