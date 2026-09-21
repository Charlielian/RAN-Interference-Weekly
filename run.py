# -*- coding: utf-8 -*-
"""
干扰小区周报全自动采集分析系统 启动入口
"""
import os
import sys
import webbrowser
import threading
import time
import uvicorn
from backend.main import app

def open_browser(port):
    time.sleep(1.2)
    try:
        webbrowser.open(f"http://127.0.0.1:{port}")
    except Exception:
        pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8090))
    print(f"============================================================")
    print(f" 干扰小区周报全自动采集与分析系统")
    print(f" 服务访问地址: http://127.0.0.1:{port}")
    print(f" 系统正在启动并尝试自动打开浏览器...")
    print(f"============================================================")

    # 后台线程自动打开浏览器
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    # 直接传 app 对象，避免 PyInstaller 环境下字符串导入问题
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
