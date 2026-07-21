
import yaml
import pandas as pd
import sys
import os
# 获取项目根目录（假设当前文件在 utils 目录下）
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)  # 向上到项目根目录

# 将项目根目录添加到 Python 路径
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from config import constants_path
# 数据层
class DataManager():
    # 类变量：缓存已加载的YAML数据，避免重复读取文件
    _cache = {}
    # pandas 库 （依赖xlrd库）

    #打开文件，获取文件所有列的值
    def get_data_from_excel(self,name,sheet_name):
        path = '../data/'+name+'.xls'

        try:
            # dtype=str: 将所有列的数据类型强制转换为字符串，避免数字被自动识别为数值类型
            # sheet_name为表头sheet名称
            df = pd.read_excel(path, sheet_name=sheet_name, dtype=str)  # 从excel文件指定的标签页读取数据
            # 将NaN转换为空字符串
            df = df.fillna('')
            data_list = df.values.tolist()
            print(data_list)
            return data_list
        except FileNotFoundError as e:
            # 文件不存在异常
            print(f"------------错误: 文件不存在 - {path}--------")
            raise e
        except Exception as e:
            # 其他异常
            print(f"------------读取Excel文件时发生错误: {str(e)}-------")
            raise e
    
    #打开文件，获取文件部分列的值,通过列名获取数据
    def get_data_by_column_names(self,name,sheet_name,column_names):
        """
        通过列名获取数据（推荐）

        Args:
            name: 文件名
            sheet_name: 工作表名
            column_names: 列名列表，如 ['元素名称', '定位器类型', '定位器值']
        使用规则：data_manager.get_data_by_column_names('page_data','pagedata', ['元素名称', '定位器类型', '定位器值'])
        """
        path = '../data/'+name+'.xls'
        try:
            # dtype=str: 将所有列的数据类型强制转换为字符串，避免数字被自动识别为数值类型
            # sheet_name为表头sheet名称
            df = pd.read_excel(path, sheet_name=sheet_name, dtype=str)  # 从excel文件指定的标签页读取数据
            # 将NaN转换为空字符串
            df = df.fillna('')
            # 检查列是否存在
            existing_columns = [col for col in column_names if col in df.columns]
            if not existing_columns:
                print(f"❌ 没有找到指定的列，可用列: {list(df.columns)}")
                return []
            # 选择指定列
            selected_df = df[existing_columns]
            data_list = selected_df.values.tolist()
            print(data_list)
            return data_list
        except FileNotFoundError as e:
            # 文件不存在异常
            print(f"------------错误: 文件不存在 - {path}--------")
            raise e
        except Exception as e:
            # 其他异常
            print(f"------------读取Excel文件时发生错误: {str(e)}-------")
            raise e

    def load_yaml_data(self, file_path):
        """
        加载 YAML 文件并返回数据
        """
        if file_path in self._cache:
            return self._cache[file_path]
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                data = yaml.safe_load(file)
            # 将数据存入缓存，避免重复读取文件  
            self._cache[file_path] = data
            return data
        except FileNotFoundError:
            print(f"错误: YAML 文件不存在: {file_path}")
            return None
        except yaml.YAMLError as e:
            print(f"错误: YAML 文件解析错误: {e}")
            return None

data_manager = DataManager()

if __name__=='__main__':
    #测试一下打开文件，获取的数据对不对
    #login_page_data=data_manager.get_data_by_column_names('page_data','pagedata', ['定位器类型','定位器值'])
    #print(login_page_data[0][0])
    #yaml_data = data_manager.get_element('reg_page','page_elements','reg_input_name')
    # yaml_data = data_manager.get_element('reg_page','assert_elements','reg_success_message')
    # print(yaml_data)
    # print(yaml_data.assert_type)
    # print(yaml_data.selector_type)
    # print(yaml_data.selector_value)
    file_path = os.path.join(constants_path.DATA_PATH, "logindata.yaml")
    yaml_data = DataManager().load_yaml_data(file_path)["login_cases"]
    print(yaml_data)
    
