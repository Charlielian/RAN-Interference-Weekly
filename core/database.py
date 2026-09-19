# -*- coding: utf-8 -*-
"""
干扰数据持久化数据库模块 (SQLite)
负责全省 21 地市干扰汇总、排名数据以及阳江重点小区干扰明细的持久化存储与历史查询
"""
import os
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd
from backend.config import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "interference.db")


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库表结构"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. 全省 21 地市每周干扰汇总表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS province_weekly_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            rule_type TEXT NOT NULL,         -- '干扰电平判断' 或 '干扰小区标识判断'
            city_class TEXT,                 -- 一类 / 二类 / 三类
            city TEXT NOT NULL,              -- 广州 / 阳江 等 21 地市
            g4_total INTEGER,                -- 4G总小区数
            g4_interf INTEGER,               -- 4G干扰小区数
            g4_ratio REAL,                   -- 4G干扰占比
            g4_prov_rank INTEGER,            -- 4G全省排名
            g4_class_rank INTEGER,           -- 4G三类排名
            g5_total INTEGER,                -- 5G总小区数
            g5_interf INTEGER,               -- 5G干扰小区数
            g5_ratio REAL,                   -- 5G干扰占比
            g5_prov_rank INTEGER,            -- 5G全省排名
            g5_class_rank INTEGER,           -- 5G三类排名
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(week_start, week_end, rule_type, city)
        )
        """)

        # 2. 阳江干扰小区明细表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS yj_weekly_cells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            rule_type TEXT NOT NULL,         -- '干扰电平判断' 或 '干扰小区标识判断'
            system TEXT NOT NULL,            -- 4G / 5G
            area TEXT,                       -- 江城 / 阳东 / 阳西 / 阳春 / 南区
            cgi TEXT NOT NULL,
            cell_name TEXT,
            band TEXT,                       -- FDD1800 / 700M / 2.6G 等
            threshold REAL,
            interf_days INTEGER,
            avg_interf_level REAL,
            is_gt_100 INTEGER DEFAULT 0,     -- 是否大于-100dBm (1=是, 0=否)
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(week_start, week_end, rule_type, cgi)
        )
        """)

        # 索引优化查询速度
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_prov_week ON province_weekly_summary(week_start, week_end, rule_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_prov_city ON province_weekly_summary(city)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_yj_week ON yj_weekly_cells(week_start, week_end, rule_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_yj_cgi ON yj_weekly_cells(cgi)")
        conn.commit()


def save_weekly_province_ranking(week_start: str, week_end: str, rule_type: str, rank_df: pd.DataFrame):
    """
    保存或更新全省地市周排名汇总数据
    rank_df 包含: ['类别', '地市', '制式', '总小区数', '干扰小区数', '干扰占比', '全省排名', '三类排名']
    """
    if rank_df is None or rank_df.empty:
        return

    # 按地市聚合 4G 和 5G
    pivot_dict = {}
    for _, row in rank_df.iterrows():
        city = row["地市"]
        system = row["制式"]
        if city not in pivot_dict:
            pivot_dict[city] = {
                "city_class": row.get("类别", ""),
                "g4_total": 0, "g4_interf": 0, "g4_ratio": 0.0, "g4_prov_rank": None, "g4_class_rank": None,
                "g5_total": 0, "g5_interf": 0, "g5_ratio": 0.0, "g5_prov_rank": None, "g5_class_rank": None,
            }
        if system == "4G":
            pivot_dict[city]["g4_total"] = int(row.get("总小区数", 0))
            pivot_dict[city]["g4_interf"] = int(row.get("干扰小区数", 0))
            pivot_dict[city]["g4_ratio"] = float(row.get("干扰占比", 0.0))
            pivot_dict[city]["g4_prov_rank"] = int(row.get("全省排名", 0)) if pd.notna(row.get("全省排名")) else None
            pivot_dict[city]["g4_class_rank"] = int(row.get("三类排名", 0)) if pd.notna(row.get("三类排名")) else None
        elif system == "5G":
            pivot_dict[city]["g5_total"] = int(row.get("总小区数", 0))
            pivot_dict[city]["g5_interf"] = int(row.get("干扰小区数", 0))
            pivot_dict[city]["g5_ratio"] = float(row.get("干扰占比", 0.0))
            pivot_dict[city]["g5_prov_rank"] = int(row.get("全省排名", 0)) if pd.notna(row.get("全省排名")) else None
            pivot_dict[city]["g5_class_rank"] = int(row.get("三类排名", 0)) if pd.notna(row.get("三类排名")) else None

    with get_db_connection() as conn:
        cursor = conn.cursor()
        for city, item in pivot_dict.items():
            cursor.execute("""
            INSERT INTO province_weekly_summary (
                week_start, week_end, rule_type, city_class, city,
                g4_total, g4_interf, g4_ratio, g4_prov_rank, g4_class_rank,
                g5_total, g5_interf, g5_ratio, g5_prov_rank, g5_class_rank
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(week_start, week_end, rule_type, city) DO UPDATE SET
                city_class=excluded.city_class,
                g4_total=excluded.g4_total,
                g4_interf=excluded.g4_interf,
                g4_ratio=excluded.g4_ratio,
                g4_prov_rank=excluded.g4_prov_rank,
                g4_class_rank=excluded.g4_class_rank,
                g5_total=excluded.g5_total,
                g5_interf=excluded.g5_interf,
                g5_ratio=excluded.g5_ratio,
                g5_prov_rank=excluded.g5_prov_rank,
                g5_class_rank=excluded.g5_class_rank
            """, (
                week_start, week_end, rule_type, item["city_class"], city,
                item["g4_total"], item["g4_interf"], item["g4_ratio"], item["g4_prov_rank"], item["g4_class_rank"],
                item["g5_total"], item["g5_interf"], item["g5_ratio"], item["g5_prov_rank"], item["g5_class_rank"]
            ))
        conn.commit()


def save_weekly_yj_cells(week_start: str, week_end: str, rule_type: str, yj_4g: pd.DataFrame, yj_5g: pd.DataFrame):
    """保存阳江干扰小区明细"""
    rows_to_insert = []
    for df, system in [(yj_4g, "4G"), (yj_5g, "5G")]:
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            avg_lvl = row.get("平均干扰电平")
            avg_lvl_val = float(avg_lvl) if pd.notna(avg_lvl) else None
            is_gt_100 = 1 if (avg_lvl_val is not None and avg_lvl_val > -100) else 0
            rows_to_insert.append((
                week_start,
                week_end,
                rule_type,
                system,
                row.get("区域", ""),
                str(row.get("CGI", "")),
                str(row.get("小区名", "")),
                str(row.get("频段", "")),
                float(row.get("门限")) if pd.notna(row.get("门限")) else None,
                int(row.get("干扰天数", 0)) if pd.notna(row.get("干扰天数")) else 0,
                avg_lvl_val,
                is_gt_100
            ))

    if not rows_to_insert:
        return

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
        INSERT INTO yj_weekly_cells (
            week_start, week_end, rule_type, system, area, cgi, cell_name, band,
            threshold, interf_days, avg_interf_level, is_gt_100
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(week_start, week_end, rule_type, cgi) DO UPDATE SET
            area=excluded.area,
            cell_name=excluded.cell_name,
            band=excluded.band,
            threshold=excluded.threshold,
            interf_days=excluded.interf_days,
            avg_interf_level=excluded.avg_interf_level,
            is_gt_100=excluded.is_gt_100
        """, rows_to_insert)
        conn.commit()


def get_previous_week_yj_ratio(rule_type: str, target_week_start: str) -> tuple:
    """从数据库中自动获取上一周阳江的 4G 和 5G 干扰占比"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT g4_ratio, g5_ratio FROM province_weekly_summary
        WHERE city = '阳江' AND rule_type = ? AND week_start < ?
        ORDER BY week_start DESC LIMIT 1
        """, (rule_type, target_week_start))
        row = cursor.fetchone()
        if row:
            return row["g4_ratio"], row["g5_ratio"]
    return None, None
