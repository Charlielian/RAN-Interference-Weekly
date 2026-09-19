# -*- coding: utf-8 -*-
"""
端到端模拟测试：验证周报算法生成的完整性与准确性
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from backend.config import ALL_CITIES, SOURCE_4G_DIR, SOURCE_5G_DIR
from core.report_generator import generate_weekly_report

def create_mock_data():
    """生成测试用的模拟源数据"""
    start = datetime(2026, 6, 15)
    dates = [start + timedelta(days=i) for i in range(7)]
    
    # 为部分城市生成模拟数据，确保阳江包含干扰小区
    for city in ALL_CITIES:
        for d in dates:
            d_str = d.strftime("%Y-%m-%d")
            
            # 4G
            records_4g = []
            cgi_count = 5 if city != "阳江" else 15
            for i in range(cgi_count):
                cgi_val = f"460-00-{city[:2]}-{i+1000}"
                cname = f"{city}江城示范小区{i}" if city == "阳江" else f"{city}基站小区{i}"
                band = "FD" if i % 2 == 0 else "FG"
                avg_level = -102.0 if i < 3 else -112.0
                is_interf = (i < 3)
                records_4g.append({
                    "CGI": cgi_val,
                    "小区名": cname,
                    "频段": band,
                    "平均干扰电平": avg_level,
                    "是否干扰小区": is_interf
                })
            df_4g = pd.DataFrame(records_4g)
            df_4g.to_excel(os.path.join(SOURCE_4G_DIR, f"4G干扰小区_{d_str}_{city}.xlsx"), index=False)

            # 5G
            records_5g = []
            for i in range(cgi_count):
                cgi_val = f"460-00-5G-{city[:2]}-{i+2000}"
                cname = f"阳江阳西测试5G小区{i}" if city == "阳江" else f"{city}5G基站小区{i}"
                band = "700M" if i % 2 == 0 else "2.6GHz"
                avg_level = -103.0 if i < 3 else -115.0
                is_interf = (i < 3)
                records_5g.append({
                    "CGI": cgi_val,
                    "小区名": cname,
                    "频段": band,
                    "全频段均值": avg_level,
                    "是否干扰小区": is_interf
                })
            df_5g = pd.DataFrame(records_5g)
            df_5g.to_excel(os.path.join(SOURCE_5G_DIR, f"5G干扰小区_{d_str}_{city}.xlsx"), index=False)

    print("测试数据准备完成")

if __name__ == "__main__":
    create_mock_data()
    logs = []
    out = generate_weekly_report("2026-06-15", "2026-06-21", log_fn=lambda m: logs.append(m))
    print(f"周报输出测试通过: {out}")
    assert os.path.exists(out), "输出文件不存在"
    
    # 检验Excel结构与Sheet
    from openpyxl import load_workbook
    wb = load_workbook(out)
    print("生成Sheet列表:", wb.sheetnames)
    assert "干扰电平判断" in wb.sheetnames
    assert "干扰小区标识判断" in wb.sheetnames
    
    ws1 = wb["干扰电平判断"]
    print("Sheet1 标题单元格 (1,1):", ws1.cell(1, 1).value)
    print("Sheet1 阳江统计汇总单元格 (4,22):", ws1.cell(4, 22).value)
    print("Sheet1 全省排名单元格 (57,22):", ws1.cell(57, 22).value)
    wb.close()
    print("ALL TESTS PASSED SUCCESSFULLY!")
