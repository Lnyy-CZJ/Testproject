# coding=utf-8 
 
import pytest
import os
import shutil

if __name__ == '__main__':
    # 定义清晰的目录结构
    results_dir = "allure-results"
    report_dir = "allure-report"
    
    # 执行测试，结果保存到 allure-results 目录
    pytest.main(['-s', '-q', './', '--clean-alluredir', f'--alluredir={results_dir}'])
    
    # 复制环境配置文件到结果目录（跨平台方式）
    if os.path.exists('environment.properties'):
        # 确保结果目录存在
        os.makedirs(results_dir, exist_ok=True)
        # 使用shutil.copy替代os.system，跨平台兼容
        shutil.copy('environment.properties', os.path.join(results_dir, 'environment.properties'))
        print("✅ 环境配置文件复制成功")
    else:
        print("⚠️  environment.properties 文件不存在，跳过复制")
    
    # 生成报告到 allure-report 目录（避免覆盖测试结果）
    generate_command = f"allure generate {results_dir} -c -o {report_dir}"
    result = os.system(generate_command)
    
    if result == 0:
        print(f"✅ Allure报告生成成功: {report_dir}/index.html")
        
        # 可选：自动在浏览器中打开报告
        open_report = input("是否在浏览器中打开报告? (y/n): ")
        if open_report.lower() == 'y':
            os.system(f"allure open {report_dir}")
    else:
        print("❌ Allure报告生成失败，请检查allure是否安装")
 

"""
#更健壮的版本（推荐）
import pytest
import os
import shutil
import subprocess
import sys

def main():
    # 主执行函数
    # 目录配置
    results_dir = "allure-results"
    report_dir = "allure-report"
    
    print("🚀 开始执行测试...")
    
    # 执行pytest测试
    exit_code = pytest.main([
        '-s', 
        '-v',  # 使用-v替代-q，显示更详细信息
        './test_cases/',  # 指定测试目录
        f'--alluredir={results_dir}',
        '--clean-alluredir'
    ])
    
    # 复制环境配置文件
    copy_environment_file(results_dir)
    
    # 生成Allure报告
    if generate_allure_report(results_dir, report_dir):
        print(f"\n🎉 测试执行完成！")
        print(f"📊 报告位置: {report_dir}/index.html")
        
        # 询问是否打开报告
        if input("\n是否在浏览器中打开报告? (y/n): ").lower() == 'y':
            open_allure_report(report_dir)
    else:
        print("\n❌ 报告生成失败")
        sys.exit(1)

def copy_environment_file(results_dir):
    # 复制环境配置文件
    env_file = "environment.properties"
    if os.path.exists(env_file):
        os.makedirs(results_dir, exist_ok=True)
        try:
            shutil.copy(env_file, os.path.join(results_dir, env_file))
            print("✅ 环境配置文件复制成功")
        except Exception as e:
            print(f"⚠️  环境配置文件复制失败: {e}")
    else:
        print("⚠️  environment.properties 文件不存在，跳过复制")

def generate_allure_report(results_dir, report_dir):
    # 生成Allure报告
    if not os.path.exists(results_dir) or not os.listdir(results_dir):
        print("❌ 未找到测试结果，跳过报告生成")
        return False
    
    print("📈 生成Allure报告中...")
    try:
        # 使用subprocess替代os.system，获得更好的控制
        result = subprocess.run([
            'allure', 'generate', 
            results_dir, 
            '-o', report_dir, 
            '-c'
        ], capture_output=True, text=True, check=True)
        
        print("✅ Allure报告生成成功")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Allure命令执行失败: {e}")
        print(f"错误输出: {e.stderr}")
        return False
    except FileNotFoundError:
        print("❌ 未找到allure命令，请确保已安装Allure命令行工具")
        print("安装指南: https://docs.qameta.io/allure/#_installing_a_commandline")
        return False

def open_allure_report(report_dir):
    # 在浏览器中打开报告
    try:
        subprocess.run(['allure', 'open', report_dir], check=False)
    except Exception as e:
        print(f"⚠️  打开报告失败: {e}")

if __name__ == '__main__':
    main()

"""