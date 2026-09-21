# -*- coding: utf-8 -*-
"""
FastAPI 后端主服务
提供登录验证、任务管理、采集进度流、报表生成与文件下载接口
"""
import os
import sys
import json
import time
import queue
import secrets
import logging
import threading
import requests
from datetime import datetime, timedelta
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import (
    DEFAULT_USERNAME, DEFAULT_PASSWORD, BASE_DIR, STATIC_DIR, REPORT_DIR,
    SOURCE_4G_DIR, SOURCE_5G_DIR, ALL_CITIES
)
from core.auth import WebLoginManager
from core.collector import enter_jxcx_portal, download_city_date
from core.report_generator import generate_weekly_report

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="干扰小区周报全自动采集分析系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态资源挂载
static_dir = STATIC_DIR
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 全局任务状态管理
class JobManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.active_job_id = None
        self.status = "idle"  # idle, running, completed, failed, cancelled
        self.progress = 0     # 0-100
        self.total_tasks = 0
        self.completed_tasks = 0
        self.current_step = ""
        self.logs = []
        self.result_file = None
        self.error_message = None
        self.cancel_flag = False

    def start(self, job_id, total):
        with self.lock:
            self.active_job_id = job_id
            self.status = "running"
            self.progress = 0
            self.total_tasks = total
            self.completed_tasks = 0
            self.current_step = "准备开始采集..."
            self.logs = []
            self.result_file = None
            self.error_message = None
            self.cancel_flag = False

    def add_log(self, msg):
        with self.lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] {msg}")
            if len(self.logs) > 1000:
                self.logs.pop(0)

    def inc_progress(self, step_info=None):
        with self.lock:
            self.completed_tasks += 1
            if self.total_tasks > 0:
                self.progress = min(99, int((self.completed_tasks / self.total_tasks) * 90))
            if step_info:
                self.current_step = step_info

    def finish(self, file_path):
        with self.lock:
            self.status = "completed"
            self.progress = 100
            self.current_step = "周报生成完毕！"
            self.result_file = file_path
            self.active_job_id = None

    def fail(self, err):
        with self.lock:
            self.status = "failed"
            self.error_message = str(err)
            self.current_step = f"异常中止: {err}"
            self.active_job_id = None

    def cancel(self):
        with self.lock:
            if self.status == "running":
                self.cancel_flag = True
                self.status = "cancelled"
                self.current_step = "任务已由用户取消"

job_mgr = JobManager()

# 会话存储
_current_session = None
_current_user = None
_session_lock = threading.Lock()


# --- Pydantic 模型 ---
class LoginBeginReq(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None

class CaptchaSubmitReq(BaseModel):
    login_id: str
    captcha_code: str

class SmsSendReq(BaseModel):
    login_id: str

class SmsSubmitReq(BaseModel):
    login_id: str
    sms_code: str

class CollectAndReportReq(BaseModel):
    start_date: str          # YYYY-MM-DD
    end_date: str            # YYYY-MM-DD
    cities: Optional[List[str]] = None
    systems: Optional[List[str]] = ["4G", "5G"]
    force_download: Optional[bool] = False
    max_workers: Optional[int] = 4


# --- 认证路由 ---
@app.get("/api/auth/status")
def get_auth_status():
    global _current_session, _current_user
    with _session_lock:
        if _current_session is not None:
            return {"logged_in": True, "username": _current_user, "message": "在线"}
        # 尝试复用本地 Cookie：未显式配置用户名时，自动扫描 cookies 目录
        ok, sess, msg, username = WebLoginManager.check_saved_session(DEFAULT_USERNAME or None)
        if ok:
            _current_session = sess
            _current_user = username
            return {"logged_in": True, "username": _current_user, "message": msg}
        return {"logged_in": False, "username": None, "message": "未登录或Cookie已失效"}

@app.post("/api/auth/begin")
def auth_begin(req: LoginBeginReq):
    res = WebLoginManager.begin(req.username, req.password)
    return res

@app.post("/api/auth/refresh-captcha")
def auth_refresh_captcha(req: dict):
    login_id = req.get("login_id")
    return WebLoginManager.refresh_captcha(login_id)

@app.post("/api/auth/submit-captcha")
def auth_submit_captcha(req: CaptchaSubmitReq):
    return WebLoginManager.submit_captcha(req.login_id, req.captcha_code)

@app.post("/api/auth/send-sms")
def auth_send_sms(req: SmsSendReq):
    return WebLoginManager.send_sms_code(req.login_id)

@app.post("/api/auth/submit-sms")
def auth_submit_sms(req: SmsSubmitReq):
    global _current_session, _current_user
    ok, sess, msg = WebLoginManager.submit_msg_code(req.login_id, req.sms_code)
    if ok and sess is not None:
        with _session_lock:
            _current_session = sess
            ctx = WebLoginManager._get_ctx(req.login_id)
            _current_user = ctx.username if ctx else DEFAULT_USERNAME
        return {"success": True, "message": "登录成功！"}
    return {"success": False, "message": msg}

@app.post("/api/auth/logout")
def auth_logout():
    global _current_session, _current_user
    with _session_lock:
        _current_session = None
        _current_user = None
    return {"success": True, "message": "已退出登录"}


# --- 任务与周报路由 ---
def run_collection_and_report_task(job_id, req: CollectAndReportReq, session):
    try:
        job_mgr.add_log("正在验证大数据平台即席查询模块访问权限...")
        if not enter_jxcx_portal(session):
            raise Exception("未能成功进入大数据平台即席查询模块(CASTGC可能失效)")

        d_start = datetime.strptime(req.start_date, "%Y-%m-%d")
        d_end = datetime.strptime(req.end_date, "%Y-%m-%d")
        days = (d_end - d_start).days + 1
        if days <= 0 or days > 31:
            raise Exception(f"日期区间非法: {req.start_date} ~ {req.end_date}")

        date_list = [(d_start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
        target_cities = req.cities if req.cities else ALL_CITIES
        systems = req.systems if req.systems else ["4G", "5G"]

        # 构建所有单点任务 (system, city, date)
        tasks = []
        for d in date_list:
            for c in target_cities:
                for s in systems:
                    tasks.append((s, c, d))

        total = len(tasks)
        job_mgr.add_log(f"任务规划完成：共 {total} 个采集子项 (包含 {len(target_cities)} 地市 × {days} 天 × {len(systems)} 制式)")

        # 使用线程池并发采集
        workers = min(max(req.max_workers or 4, 1), 8)
        job_mgr.add_log(f"启动并发采集线程池，并发数: {workers}")

        def worker_task(item):
            if job_mgr.cancel_flag:
                return None
            s, c, d = item
            # 独立复用Cookie的会话，避免连接池互踩
            worker_sess = requests.Session()
            worker_sess.verify = False
            worker_sess.cookies = session.cookies
            return download_city_date(worker_sess, s, c, d, force_overwrite=req.force_download, log_fn=job_mgr.add_log)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_item = {executor.submit(worker_task, item): item for item in tasks}
            for future in as_completed(future_to_item):
                if job_mgr.cancel_flag:
                    break
                item = future_to_item[future]
                try:
                    res = future.result()
                    s, c, d = item
                    job_mgr.inc_progress(f"已完成: {s} {c} {d}")
                except Exception as e:
                    job_mgr.add_log(f"[ERROR] 采集子项异常 {item}: {e}")

        if job_mgr.cancel_flag:
            job_mgr.add_log("采集已被手动终止")
            return

        job_mgr.add_log("全部地市源数据采集完成！开始执行融合周报算法分析与统计计算...")
        out_report = generate_weekly_report(req.start_date, req.end_date, log_fn=job_mgr.add_log)
        job_mgr.finish(out_report)
        job_mgr.add_log(f"周报计算生成完成！文件路径: {os.path.basename(out_report)}")

    except Exception as e:
        logger.exception("任务执行失败")
        job_mgr.add_log(f"[FATAL] 任务异常: {e}")
        job_mgr.fail(e)


@app.post("/api/job/start")
def start_job(req: CollectAndReportReq, bg: BackgroundTasks):
    global _current_session
    if _current_session is None:
        raise HTTPException(status_code=401, detail="请先登录系统后操作")

    if job_mgr.status == "running":
        raise HTTPException(status_code=400, detail="已有正在运行的采集周报任务，请等待完成或取消")

    d_start = datetime.strptime(req.start_date, "%Y-%m-%d")
    d_end = datetime.strptime(req.end_date, "%Y-%m-%d")
    days = (d_end - d_start).days + 1
    target_cities = req.cities if req.cities else ALL_CITIES
    systems = req.systems if req.systems else ["4G", "5G"]
    total = len(target_cities) * days * len(systems)

    job_id = secrets.token_hex(8)
    job_mgr.start(job_id, total)
    bg.add_task(run_collection_and_report_task, job_id, req, _current_session)

    return {"success": True, "job_id": job_id, "message": f"任务已启动，总任务项: {total}"}


@app.post("/api/job/cancel")
def cancel_job():
    job_mgr.cancel()
    return {"success": True, "message": "已发送取消信号"}


@app.get("/api/job/status")
def get_job_status():
    with job_mgr.lock:
        return {
            "status": job_mgr.status,
            "progress": job_mgr.progress,
            "total_tasks": job_mgr.total_tasks,
            "completed_tasks": job_mgr.completed_tasks,
            "current_step": job_mgr.current_step,
            "result_filename": os.path.basename(job_mgr.result_file) if job_mgr.result_file else None,
            "error_message": job_mgr.error_message,
            "logs": job_mgr.logs[-100:]  # 最近 100 条日志
        }


@app.post("/api/job/generate-only")
def generate_only(req: CollectAndReportReq):
    """仅生成周报（利用已采集的源文件）"""
    try:
        logs = []
        out = generate_weekly_report(req.start_date, req.end_date, log_fn=lambda m: logs.append(m))
        return {
            "success": True,
            "result_filename": os.path.basename(out),
            "logs": logs
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.get("/api/reports/list")
def list_reports():
    files = []
    if os.path.exists(REPORT_DIR):
        for f in sorted(os.listdir(REPORT_DIR), reverse=True):
            if f.endswith(".xlsx"):
                fp = os.path.join(REPORT_DIR, f)
                stat = os.stat(fp)
                files.append({
                    "filename": f,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })
    return {"reports": files}


@app.get("/api/reports/download/{filename}")
def download_report(filename: str):
    fp = os.path.join(REPORT_DIR, filename)
    if not os.path.exists(fp):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(fp, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=filename)


@app.get("/")
def index():
    index_html = os.path.join(static_dir, "index.html")
    if os.path.exists(index_html):
        return FileResponse(index_html)
    return {"message": "服务运行中，请访问前端页面"}

# --- 数据库历史查询路由 ---
from core.database import get_db_connection

@app.get("/api/db/weeks")
def get_db_weeks():
    """获取数据库中已归档的周次列表"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
        SELECT DISTINCT week_start, week_end
        FROM province_weekly_summary
        ORDER BY week_start DESC
        """)
        return {"weeks": [dict(r) for r in c.fetchall()]}

@app.get("/api/db/province-summary")
def get_db_province_summary(week_start: str, rule_type: Optional[str] = "干扰电平判断"):
    """获取指定周的全省 21 地市干扰汇总与排名"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
        SELECT * FROM province_weekly_summary
        WHERE week_start = ? AND rule_type = ?
        ORDER BY CASE city_class WHEN '一类' THEN 1 WHEN '二类' THEN 2 ELSE 3 END, g4_prov_rank ASC
        """, (week_start, rule_type))
        return {"data": [dict(r) for r in c.fetchall()]}

@app.get("/api/db/yj-cells")
def get_db_yj_cells(week_start: str, rule_type: Optional[str] = "干扰电平判断", system: Optional[str] = None, area: Optional[str] = None):
    """获取阳江干扰小区明细"""
    sql = "SELECT * FROM yj_weekly_cells WHERE week_start = ? AND rule_type = ?"
    params = [week_start, rule_type]
    if system:
        sql += " AND system = ?"
        params.append(system)
    if area:
        sql += " AND area = ?"
        params.append(area)
    sql += " ORDER BY avg_interf_level DESC"

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(sql, params)
        return {"data": [dict(r) for r in c.fetchall()]}
