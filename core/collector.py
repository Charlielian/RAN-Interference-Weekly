# -*- coding: utf-8 -*-
"""
干扰小区采集模块
从NQI即席查询(JXCX)按城市与日期采集4G/5G干扰小区数据
"""
import os
import json
import time
import random
import logging
import requests
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.config import (
    NQI_BASE_URL, JXCX_URL, JXCX_COUNT_URL, HEADERS, ALL_CITIES,
    SOURCE_4G_DIR, SOURCE_5G_DIR
)

logger = logging.getLogger(__name__)

TIMEOUT_COUNT = 30
TIMEOUT_DATA = 120


def get_cookie_val(cookies, name):
    try:
        val = cookies.get(name, domain='nqi.gmcc.net')
        if val:
            return val
        return cookies.get(name)
    except Exception:
        for c in cookies:
            if c.name == name:
                return c.value
    return None


def enter_jxcx_portal(session: requests.Session) -> bool:
    """确认可进入即席查询系统"""
    castgc = get_cookie_val(session.cookies, 'CASTGC')
    if not castgc:
        logger.error("Session中缺少CASTGC Cookie")
        return False
    try:
        url = f'{NQI_BASE_URL}/pro-portal/pure/urlAction.action'
        params = {
            'url': 'pro-adhoc/index',
            'random': random.random(),
            '__PID': 'JXCX',
            'token': castgc
        }
        res = session.get(url, params=params, headers=HEADERS, timeout=20)
        return res.status_code == 200
    except Exception as e:
        logger.error(f"进入即席查询入口异常: {e}")
        return False


def build_4g_payload(date_str: str, city: str) -> dict:
    """构建单日、单地市的4G干扰小区查询Payload"""
    fields = [
        ('starttime', '数据时间'), ('endtime', '结束时间'), ('cgi', 'CGI'),
        ('cell_name', '小区名'), ('freq', '频段'), ('micro_grid', '微网格标识'),
        ('bandwidth', '系统带宽'), ('averagevalue', '平均干扰电平'), ('is_interfere', '是否干扰小区')
    ]
    fixed_fields = {'starttime', 'endtime', 'cgi', 'cell_name', 'city'}
    result_list = []
    for f_code, f_name in fields:
        columntype = 1 if f_code in fixed_fields else 2
        result_list.append({
            'feildtype': '4G干扰报表（忙时）',
            'table': 'appdbv3.a_interfere_lte_cell_zb2_d',
            'datatype': '1' if f_code in ['starttime', 'endtime'] else 'character varying',
            'columntype': columntype,
            'feildName': f_name,
            'feild': f_code,
            'poly': '无', 'anyWay': '无', 'chart': '无', 'chartpoly': '无'
        })

    return {
        'draw': 1, 'start': 0, 'length': 200, 'total': 0,
        'geographicdimension': '小区', 'timedimension': '天',
        'enodebField': 'enodeb_id', 'cgiField': 'cgi', 'timeField': 'starttime',
        'cellField': 'cell', 'cityField': 'city',
        'result': {'result': result_list, 'tableParams': {'supporteddimension': None, 'supportedtimedimension': ''}, 'columnname': ''},
        'where': [
            {'datatype': 'timestamp', 'feild': 'starttime', 'feildName': '', 'symbol': '>=', 'val': f'{date_str} 00:00:00', 'whereCon': 'and', 'query': True},
            {'datatype': 'timestamp', 'feild': 'starttime', 'feildName': '', 'symbol': '<=', 'val': f'{date_str} 23:59:59', 'whereCon': 'and', 'query': True},
            {'datatype': 'character', 'feild': 'city', 'feildName': '', 'symbol': 'in', 'val': city, 'whereCon': 'and', 'query': True}
        ],
        'indexcount': 0
    }


def build_5g_payload(date_str: str, city: str) -> dict:
    """构建单日、单地市的5G干扰小区查询Payload"""
    fields = [
        ('starttime', '数据时间'), ('endtime', '结束时间'), ('cgi', 'CGI'),
        ('cell_name', '小区名'), ('freq', '频段'), ('micro_grid', '微网格标识'),
        ('averagevalue', '全频段均值'), ('averagevalued1', 'D1均值'),
        ('averagevalued2', 'D2均值'), ('is_interfere_5g', '是否干扰小区')
    ]
    fixed_fields = {'starttime', 'endtime', 'cgi', 'cell_name', 'city'}
    result_list = []
    for f_code, f_name in fields:
        columntype = 1 if f_code in fixed_fields else 2
        result_list.append({
            'feildtype': '5G干扰报表（忙时）',
            'table': 'appdbv3.a_interfere_nr_cell_zb2_d',
            'datatype': '1' if f_code in ['starttime', 'endtime'] else 'character varying',
            'columntype': columntype,
            'feildName': f_name,
            'feild': f_code,
            'poly': '无', 'anyWay': '无', 'chart': '无', 'chartpoly': '无'
        })

    return {
        'draw': 1, 'start': 0, 'length': 200, 'total': 0,
        'geographicdimension': '小区', 'timedimension': '天',
        'enodebField': 'gnodeb_id', 'cgiField': 'cgi', 'timeField': 'starttime',
        'cellField': 'cell', 'cityField': 'city',
        'result': {'result': result_list, 'tableParams': {'supporteddimension': None, 'supportedtimedimension': ''}, 'columnname': ''},
        'where': [
            {'datatype': 'timestamp', 'feild': 'starttime', 'feildName': '', 'symbol': '>=', 'val': f'{date_str} 00:00:00', 'whereCon': 'and', 'query': True},
            {'datatype': 'timestamp', 'feild': 'starttime', 'feildName': '', 'symbol': '<=', 'val': f'{date_str} 23:59:59', 'whereCon': 'and', 'query': True},
            {'datatype': 'character', 'feild': 'city', 'feildName': '', 'symbol': 'in', 'val': city, 'whereCon': 'and', 'query': True}
        ],
        'indexcount': 0
    }


def query_table_count(session: requests.Session, payload: dict) -> int:
    """获取查询总记录数"""
    post_headers = HEADERS.copy()
    post_headers.update({
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
        'Origin': NQI_BASE_URL,
        'Referer': f'{NQI_BASE_URL}/pro-adhoc/adhocquery'
    })
    data = {'data': json.dumps(payload, ensure_ascii=False)}
    res = session.post(JXCX_COUNT_URL, data=data, headers=post_headers, timeout=TIMEOUT_COUNT)
    if res.status_code == 200:
        ret = res.json()
        if isinstance(ret, dict):
            return int(ret.get('total', ret.get('recordsTotal', 0)))
    return 0


def fetch_all_records(session: requests.Session, payload: dict, total_count: int, log_cb=None) -> list:
    """分页拉取所有数据"""
    post_headers = HEADERS.copy()
    post_headers.update({
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
        'Origin': NQI_BASE_URL,
        'Referer': f'{NQI_BASE_URL}/pro-adhoc/adhocquery'
    })

    batch_size = 5000 if total_count > 10000 else 2000
    records = []
    start = 0
    draw = 1

    while start < total_count or (total_count == 0 and start == 0):
        p = json.loads(json.dumps(payload))
        p['start'] = start
        p['length'] = batch_size
        p['draw'] = draw

        data = {'data': json.dumps(p, ensure_ascii=False)}
        res = session.post(JXCX_URL, data=data, headers=post_headers, timeout=TIMEOUT_DATA)
        if res.status_code != 200:
            raise Exception(f"HTTP {res.status_code} 获取数据失败")

        ret = res.json()
        rows = ret.get('data', [])
        if not rows:
            break

        records.extend(rows)
        if log_cb and total_count > 0:
            log_cb(min(len(records), total_count), total_count)

        start += len(rows)
        draw += 1
        if len(rows) < batch_size:
            break

    return records


def download_city_date(session: requests.Session, system: str, city: str, date_str: str, force_overwrite: bool = False, log_fn=None) -> str:
    """采集单个地市单日的数据并保存为Excel"""
    out_dir = SOURCE_4G_DIR if system == '4G' else SOURCE_5G_DIR
    target_file = os.path.join(out_dir, f"{system}干扰小区_{date_str}_{city}.xlsx")

    if not force_overwrite and os.path.exists(target_file) and os.path.getsize(target_file) > 1024:
        if log_fn:
            log_fn(f"[{system}] {city} {date_str} 文件已存在且完整，跳过重复下载")
        return target_file

    if system == '4G':
        payload = build_4g_payload(date_str, city)
    else:
        payload = build_5g_payload(date_str, city)

    # 1. 尝试多次获取 count
    total = 0
    for attempt in range(3):
        try:
            total = query_table_count(session, payload)
            break
        except Exception as e:
            if attempt == 2:
                raise Exception(f"获取记录数失败: {e}")
            time.sleep(1)

    if log_fn:
        log_fn(f"[{system}] {city} {date_str} 记录数: {total}")

    if total == 0:
        # 空数据写入空DataFrame保持结构
        if system == '4G':
            df = pd.DataFrame(columns=['CGI', '小区名', '频段', '平均干扰电平', '是否干扰小区'])
        else:
            df = pd.DataFrame(columns=['CGI', '小区名', '频段', '全频段均值', '是否干扰小区'])
        df.to_excel(target_file, index=False)
        return target_file

    # 2. 批量拉取
    rows = fetch_all_records(session, payload, total)
    df = pd.DataFrame(rows)

    # 字段重命名与标准化
    if system == '4G':
        rename_map = {
            'cgi': 'CGI',
            'cell_name': '小区名',
            'freq': '频段',
            'averagevalue': '平均干扰电平',
            'is_interfere': '是否干扰小区',
        }
    else:
        rename_map = {
            'cgi': 'CGI',
            'cell_name': '小区名',
            'freq': '频段',
            'averagevalue': '全频段均值',
            'is_interfere_5g': '是否干扰小区',
        }
    df = df.rename(columns=rename_map)

    # 写入Excel
    df.to_excel(target_file, index=False)
    if log_fn:
        log_fn(f"[{system}] {city} {date_str} 采集成功，保存至: {os.path.basename(target_file)}")
    return target_file
