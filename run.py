# -*- coding: utf-8 -*-
"""
干扰小区周报全自动采集分析系统 启动入口
"""
import uvicorn
import os
import sys

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8090))
    print(f"============================================================")
    print(f" 干扰小区周报全自动采集与分析系统")
    print(f" 服务访问地址: http://127.0.0.1:{port}")
    print(f"============================================================")
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=False)
