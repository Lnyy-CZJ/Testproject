import pandas as pd
import json
import os

def json_to_excel(json_file_path, excel_file_path=None):
    """
    将JSON文件转换为Excel文件
    
    Args:
        json_file_path: JSON文件路径
        excel_file_path: 输出的Excel文件路径（可选）
    """
    # 如果没有指定输出路径，使用JSON文件名
    if excel_file_path is None:
        excel_file_path = json_file_path.replace('.json', '.xlsx')
    
    # 读取JSON文件
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 处理不同格式的JSON数据
    if isinstance(data, list):
        # 如果是列表，直接转换为DataFrame
        df = pd.DataFrame(data)
    elif isinstance(data, dict):
        # 如果是字典，检查是否需要转换为DataFrame
        if all(isinstance(v, (list, dict)) for v in data.values()):
            # 嵌套结构，使用json_normalize
            df = pd.json_normalize(data)
        else:
            # 简单字典，转换为单行DataFrame
            df = pd.DataFrame([data])
    else:
        raise ValueError("不支持的JSON格式")
    
    # 保存为Excel文件
    df.to_excel(excel_file_path, index=False)
    print(f"转换成功！文件已保存为: {excel_file_path}")
    return excel_file_path

# 使用示例
json_to_excel('D:/PythonProject/AItestcase_Agents/output/项目C：赛事系统/计时赛功能/testcases_20260524_103146.json', 'D:/PythonProject/AItestcase_Agents/output/项目C：赛事系统/计时赛功能/estcases_20260524_103146.xlsx')
