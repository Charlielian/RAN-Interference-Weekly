# -*- coding: utf-8 -*-
"""
干扰小区采集模块
从NQI即席查询(JXCX)按城市与日期采集4G/5G干扰小区数据

请求协议与 Nqi导出工具_new 保持一致：
- 请求体使用 DataTables 扁平 URL 编码（result/where 单独 JSON 序列化），
  而不是把整个 payload 包在 ``data=`` 里，后端 getTable/getTableCount 按
  表单字段逐个读取，包一层会导致字段解析失败。
- result 字段列表保持 HAR 抓包结构（feildtype/table/tableName/datatype/
  columntype），datatype 规则：固定字段集为 '1'，starttime/endtime/city 为 '2'，
  其余为 'character varying'；columntype：starttime 为 2，其余为 1。
- where 的上界使用 '<'（与浏览器一致），而不是 '<='。
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
from urllib.parse import quote
from typing import Optional

from backend.config import (
    NQI_BASE_URL, JXCX_URL, JXCX_COUNT_URL, HEADERS, ALL_CITIES,
    SOURCE_4G_DIR, SOURCE_5G_DIR
)

logger = logging.getLogger(__name__)

TIMEOUT_COUNT = 30
TIMEOUT_DATA = 120


# ==================== DataTables 编码（对齐 Nqi导出工具_new/utils/helpers.py） ====================

def _encode_columns_param(columns):
    """columns[i][data]=x&columns[i][searchable]=true&..."""
    parts = []
    for i, col in enumerate(columns):
        for key, val in col.items():
            if isinstance(val, dict):
                for sk, sv in val.items():
                    parts.append(f'columns[{i}][{key}][{sk}]={quote(str(sv).lower() if isinstance(sv, bool) else str(sv))}')
            else:
                parts.append(f'columns[{i}][{key}]={quote(str(val).lower() if isinstance(val, bool) else str(val))}')
    return '&'.join(parts)


def _encode_order_param(order):
    parts = []
    for i, o in enumerate(order):
        for key, val in o.items():
            parts.append(f'order[{i}][{key}]={quote(str(val))}')
    return '&'.join(parts)


def _encode_search_param(search):
    parts = []
    for key, val in search.items():
        parts.append(f'search[{key}]={quote(str(val).lower() if isinstance(val, bool) else str(val))}')
    return '&'.join(parts)


def _encode_json_param(key, value):
    json_str = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return quote(key) + '=' + quote(json_str, safe='/:= ')


def encode_datatables_payload(payload):
    """把查询 payload 编码为 DataTables URL-encoded 表单，与浏览器 HAR 一致。"""
    out_list = []
    for key in payload:
        if key == 'columns':
            if isinstance(payload[key], str):
                out_list.append(quote(key) + '=' + quote(payload[key]))
                continue
            elif not isinstance(payload[key], list):
                out_list.append(quote(key) + '=' + quote(str(payload[key])))
                continue
            out_list.append(_encode_columns_param(payload[key]))
        elif key == 'order':
            out_list.append(_encode_order_param(payload[key]))
        elif key == 'search':
            out_list.append(_encode_search_param(payload[key]))
        elif key in ['result', 'where']:
            out_list.append(_encode_json_param(key, payload[key]))
        elif isinstance(payload[key], int):
            out_list.append(quote(key) + '=' + str(payload[key]))
        else:
            out_list.append(quote(key) + '=' + quote(str(payload[key]) if payload[key] is not None else ''))
    return '&'.join(out_list)


def _build_columns_param(field_list):
    columns = []
    for field in field_list:
        columns.append({
            'data': field,
            'name': '',
            'searchable': True,
            'orderable': True,
            'search': {'value': '', 'regex': False}
        })
    return columns


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


SYSTEM_CONFIG = {
    '4G': {
        'fieldtype': '4G干扰报表（忙时）',
        'table': 'appdbv3.a_interfere_lte_cell_zb2_d',
        'enodebField': 'enodeb_id',
        'cgiField': 'cgi',
        'cellField': 'cell',
        'fields': [
            ('starttime', '数据时间'), ('endtime', '结束时间'), ('cgi', 'CGI'),
            ('cell_name', '小区名'), ('freq', '频段'), ('micro_grid', '微网格标识'),
            ('bandwidth', '系统带宽'), ('averagevalue', '平均干扰电平'), ('is_interfere', '是否干扰小区')
        ],
    },
    '5G': {
        'fieldtype': '5G干扰报表（忙时）',
        'table': 'appdbv3.a_interfere_nr_cell_zb2_d',
        'enodebField': 'gnodeb_id',
        'cgiField': 'cgi',
        'cellField': 'cell',
        'fields': [
            ('starttime', '数据时间'), ('endtime', '结束时间'), ('cgi', 'CGI'),
            ('cell_name', '小区名'), ('freq', '频段'), ('micro_grid', '微网格标识'),
            ('averagevalue', '全频段均值'), ('averagevalued1', 'D1均值'),
            ('averagevalued2', 'D2均值'), ('is_interfere_5g', '是否干扰小区')
        ],
    },
}

# HAR 中 datatype 固定为 '1' 的字段
FIXED_DATATYPE_FIELDS = {'starttime', 'endtime', 'cgi', 'cell_name', 'city'}


def _build_result_fields(fields, fieldtype, table_name):
    """按 HAR 抓包规则构建 result 字段元数据。"""
    result_list = []
    for feild, feildName in fields:
        columntype = 2 if feild == 'starttime' else 1
        if feild in ('ncgi', 'nrcell_name'):
            datatype, columntype = 'character varying', 2
        elif feild in FIXED_DATATYPE_FIELDS:
            datatype = '1'
        elif feild in ('starttime', 'endtime', 'city'):
            datatype = '2'
        else:
            datatype = 'character varying'
        result_list.append({
            'feildtype': fieldtype,
            'table': table_name,
            'tableName': fieldtype,
            'datatype': datatype,
            'columntype': columntype,
            'feildName': feildName,
            'feild': feild,
            'poly': '无',
            'anyWay': '无',
            'chart': '无',
            'chartpoly': '无',
        })
    return result_list


def _build_payload(system: str, date_str: str, city: str) -> dict:
    """构建单日、单地市的干扰小区查询Payload。"""
    cfg = SYSTEM_CONFIG[system]
    result_list = _build_result_fields(cfg['fields'], cfg['fieldtype'], cfg['table'])
    return {
        'draw': 1, 'start': 0, 'length': 200, 'total': 0,
        'geographicdimension': '小区', 'timedimension': '天',
        'enodebField': cfg['enodebField'], 'cgiField': cfg['cgiField'], 'timeField': 'starttime',
        'cellField': cfg['cellField'], 'cityField': 'city',
        'columns': _build_columns_param([f[0] for f in cfg['fields']]),
        'order': [{'column': 0, 'dir': 'desc'}],
        'search': {'value': '', 'regex': False},
        'result': {'result': result_list, 'tableParams': {'supporteddimension': None, 'supportedtimedimension': ''}, 'columnname': ''},
        'where': [
            {'datatype': 'timestamp', 'feild': 'starttime', 'feildName': '', 'symbol': '>=', 'val': f'{date_str} 00:00:00', 'whereCon': 'and', 'query': True},
            {'datatype': 'timestamp', 'feild': 'starttime', 'feildName': '', 'symbol': '<', 'val': f'{date_str} 23:59:59', 'whereCon': 'and', 'query': True},
            {'datatype': 'character', 'feild': 'city', 'feildName': '', 'symbol': 'in', 'val': city, 'whereCon': 'and', 'query': True}
        ],
        'indexcount': 0
    }


def build_4g_payload(date_str: str, city: str) -> dict:
    """构建单日、单地市的4G干扰小区查询Payload"""
    return _build_payload('4G', date_str, city)


def build_5g_payload(date_str: str, city: str) -> dict:
    """构建单日、单地市的5G干扰小区查询Payload"""
    return _build_payload('5G', date_str, city)


def _extract_count(result: dict):
    """从 getTableCount 响应中提取总数，兼容多种响应包装。"""
    if not isinstance(result, dict):
        return None
    if 'count' in result:
        return result['count']
    if 'data' in result and isinstance(result['data'], dict):
        if 'count' in result['data']:
            return result['data']['count']
        if 'total' in result['data']:
            return result['data']['total']
    if 'recordsTotal' in result:
        return result['recordsTotal']
    if 'data' in result and isinstance(result['data'], (int, float)):
        return result['data']
    if 'result' in result and isinstance(result['result'], (int, float)):
        return result['result']
    if 'recordsFiltered' in result:
        return result['recordsFiltered']
    return None


# count 接口只接受查询维度/where/result，columns/order/search 会导致部分报表异常
COUNT_PAYLOAD_KEYS = [
    'geographicdimension', 'timedimension', 'enodebField', 'cgiField',
    'timeField', 'cellField', 'cityField', 'result', 'where', 'indexcount'
]


def query_table_count(session: requests.Session, payload: dict) -> int:
    """获取查询总记录数"""
    payload_count = {k: v for k, v in payload.items() if k in COUNT_PAYLOAD_KEYS}
    body = encode_datatables_payload(payload_count)
    res = session.post(JXCX_COUNT_URL, data=body, headers=HEADERS, timeout=TIMEOUT_COUNT)
    if res.status_code == 200:
        try:
            ret = res.json()
        except ValueError:
            return 0
        count = _extract_count(ret)
        if count is not None and count != '':
            return int(count)
    return 0


def fetch_all_records(session: requests.Session, payload: dict, total_count: int, log_cb=None) -> list:
    """分页拉取所有数据"""
    batch_size = 5000 if total_count > 10000 else 2000
    records = []
    start = 0
    draw = 1

    while start < total_count or (total_count == 0 and start == 0):
        p = json.loads(json.dumps(payload, ensure_ascii=False))
        p['start'] = start
        p['length'] = batch_size
        p['draw'] = draw

        body = encode_datatables_payload(p)
        res = session.post(JXCX_URL, data=body, headers=HEADERS, timeout=TIMEOUT_DATA)
        if res.status_code != 200:
            raise Exception(f"HTTP {res.status_code} 获取数据失败")

        ret = res.json()
        # 服务器返回错误消息时按文本判断
        if isinstance(ret, dict) and ret.get('message'):
            msg = str(ret['message'])
            if '不存在' in msg:
                break
            if any(err in msg for err in ['失败', '错误', 'error', 'Error', '异常']):
                raise Exception(f"服务器返回错误: {msg[:100]}")

        rows = []
        if isinstance(ret, dict):
            rows = ret.get('data') or []
            if not rows:
                for key in ('result', 'records', 'rows', 'dataList'):
                    if isinstance(ret.get(key), list) and ret[key]:
                        rows = ret[key]
                        break
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


def download_city_date(session: requests.Session, system: str, city: str, date_str: str, force_overwrite: bool = False, log_fn=None) -> Optional[str]:
    """采集单个地市单日的数据并保存为Excel。当天地市若无数据则不生成Excel文件。"""
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
        if log_fn:
            log_fn(f"[{system}] {city} {date_str} 无数据，跳过生成文件")
        # 若开启强制覆盖且存在旧文件，则清理
        if force_overwrite and os.path.exists(target_file):
            try:
                os.remove(target_file)
            except OSError:
                pass
        return None

    # 2. 批量拉取
    rows = fetch_all_records(session, payload, total)
    if not rows:
        if log_fn:
            log_fn(f"[{system}] {city} {date_str} 获取到的数据行为空，跳过生成文件")
        if force_overwrite and os.path.exists(target_file):
            try:
                os.remove(target_file)
            except OSError:
                pass
        return None

    df = pd.DataFrame(rows)
    if df.empty:
        if log_fn:
            log_fn(f"[{system}] {city} {date_str} 数据集为空，跳过生成文件")
        if force_overwrite and os.path.exists(target_file):
            try:
                os.remove(target_file)
            except OSError:
                pass
        return None

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
