# -*- coding: utf-8 -*-
"""
Cookie与辅助函数
"""
import os
import json
import http.cookiejar
from requests.cookies import RequestsCookieJar
from backend.config import COOKIE_DIR

class HttpCookieEncoder:
    @staticmethod
    def encode(cookie_jar):
        cookies = []
        for cookie in cookie_jar:
            cookie_dict = {
                'name': cookie.name,
                'value': cookie.value,
                'domain': cookie.domain,
                'path': cookie.path,
                'secure': cookie.secure,
                'expires': cookie.expires if hasattr(cookie, 'expires') else None,
            }
            cookies.append(cookie_dict)
        return json.dumps(cookies, ensure_ascii=False)

    @staticmethod
    def decode(json_str, cookie_jar=None):
        if cookie_jar is None:
            cookie_jar = RequestsCookieJar()
        try:
            cookies_data = json.loads(json_str)
            for cookie_dict in cookies_data:
                cookie = http.cookiejar.Cookie(
                    version=0,
                    name=cookie_dict.get('name', ''),
                    value=cookie_dict.get('value', ''),
                    port=None,
                    port_specified=False,
                    domain=cookie_dict.get('domain', ''),
                    domain_specified=bool(cookie_dict.get('domain')),
                    domain_initial_dot=False,
                    path=cookie_dict.get('path', '/'),
                    path_specified=bool(cookie_dict.get('path')),
                    secure=cookie_dict.get('secure', False),
                    expires=cookie_dict.get('expires'),
                    discard=True,
                    comment=None,
                    comment_url=None,
                    rest={},
                    rfc2109=False
                )
                cookie_jar.set_cookie(cookie)
        except Exception:
            pass
        return cookie_jar

def save_cookie(cookie_jar, username):
    os.makedirs(COOKIE_DIR, exist_ok=True)
    filepath = os.path.join(COOKIE_DIR, f"{username}.json")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(HttpCookieEncoder.encode(cookie_jar))

def load_cookie(username):
    filepath = os.path.join(COOKIE_DIR, f"{username}.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return HttpCookieEncoder.decode(f.read())
        except Exception:
            return None
    return None

def delete_cookie(username):
    filepath = os.path.join(COOKIE_DIR, f"{username}.json")
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except OSError:
            pass
