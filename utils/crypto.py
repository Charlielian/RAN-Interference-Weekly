# -*- coding: utf-8 -*-
"""
加密工具模块
提供RSA加密功能
"""
import base64
import logging

logger = logging.getLogger(__name__)

try:
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_v1_5
except ModuleNotFoundError:
    from Cryptodome.PublicKey import RSA
    from Cryptodome.Cipher import PKCS1_v1_5


def rsa_encrypt(data, public_key):
    """RSA公钥加密"""
    if not public_key or not data:
        raise ValueError("公钥和数据不能为空")
    public_key_formatted = '-----BEGIN PUBLIC KEY-----\n' + public_key + '\n-----END PUBLIC KEY-----'
    rsa_key = RSA.import_key(public_key_formatted)
    cipher = PKCS1_v1_5.new(rsa_key)
    encrypted_data = base64.b64encode(cipher.encrypt(data.encode(encoding="utf-8")))
    return encrypted_data.decode('utf-8')
