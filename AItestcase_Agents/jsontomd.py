import json
import glob
import os
import sys

# 测试点 JSON 文件所在目录
TEST_POINTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "test_points")


def get_latest_json_file(directory: str) -> str:
    """
    获取指定目录下最新的测试点 JSON 文件路径

    按文件名中的时间戳排序，返回最新的文件路径。

    参数说明:
        directory (str): JSON 文件所在目录路径

    返回值:
        str: 最新 JSON 文件的完整路径

    异常说明:
        FileNotFoundError: 目录下不存在任何匹配的 JSON 文件时抛出
    """
    pattern = os.path.join(directory, "test_points_*.json")
    files = glob.glob(pattern)
    if not files:
        raise FileNotFoundError(f"目录 {directory} 下未找到任何 test_points_*.json 文件")
    # 文件名包含时间戳，按名称降序即为最新
    return max(files, key=os.path.basename)


def json_to_xmind_advanced(json_file: str, output_file: str = None):
    """
    从 JSON 文件读取测试点数据并生成 Markdown 格式的思维导图文件

    功能说明:
        生成 XMind 可导入的 Markdown 文件，通过 XMind 的「导入 Markdown」功能
        转换为思维导图。层级映射：# 根节点 → ## 模块 → ### 功能 → #### 场景 → - 测试点

    参数说明:
        json_file (str): 测试点 JSON 文件路径，位于 output/test_points/ 目录下
        output_file (str): 输出 Markdown 文件路径，默认为 JSON 同目录下同名 .md 文件

    异常说明:
        FileNotFoundError: JSON 文件不存在时抛出
        json.JSONDecodeError: JSON 文件格式不合法时抛出
    """
    # 读取 JSON 文件
    if not os.path.exists(json_file):
        raise FileNotFoundError(f"JSON 文件不存在: {json_file}")

    with open(json_file, "r", encoding="utf-8") as f:
        json_data = json.load(f)

    # 默认输出路径：与 JSON 文件同目录、同名但后缀为 .md
    if output_file is None:
        output_file = os.path.splitext(json_file)[0] + ".md"

    # 按模块分组
    modules = {}
    for item in json_data:
        module = item['module']
        feature = item['feature']
        scenario = item['scenario']
        test_point = item['test_point']
        risk_level = item['risk_level']

        if module not in modules:
            modules[module] = {}

        if feature not in modules[module]:
            modules[module][feature] = {}

        if scenario not in modules[module][feature]:
            modules[module][feature][scenario] = []

        modules[module][feature][scenario].append({
            'id': item['id'],
            'point': test_point,
            'risk': risk_level
        })

    # 构建 Markdown 内容（层级：# 根 → ## 模块 → ### 功能 → #### 场景 → - 测试点）
    lines = ["# 测试点思维导图", ""]

    for module_name, features in modules.items():
        lines.append(f"## {module_name}")
        lines.append("")

        for feature_name, scenarios in features.items():
            lines.append(f"### {feature_name}")
            lines.append("")

            for scenario_name, points in scenarios.items():
                lines.append(f"#### {scenario_name}")
                lines.append("")

                for point in points:
                    lines.append(f"- [{point['id']}] {point['point']}")

                lines.append("")

    # 写入 Markdown 文件
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Markdown 文件已生成: {output_file}")
    print("请在 XMind 中通过「文件 → 导入 → Markdown」打开此文件")


# 风险图标 → 风险等级的反向映射
_RISK_ICON_TO_LEVEL = {
    '[P0🔴]': 'P0',
    '[P1🟠]': 'P1',
    '[P2🟡]': 'P2',
    '[P3🟢]': 'P3',
}


def parse_risk_from_text(text: str) -> str:
    """
    从测试点文本末尾提取风险等级

    参数说明:
        text: 测试点文本，可能包含风险图标如 [P0🔴]

    返回值:
        str: 风险等级（P0/P1/P2/P3），未匹配到时返回 "P3"
    """
    for icon, level in _RISK_ICON_TO_LEVEL.items():
        if icon in text:
            return level
    return "P3"


def md_to_json(md_file: str, output_file: str = None):
    """
    将 Markdown 格式的测试点文件转换回 JSON 格式

    功能说明:
        解析由 json_to_xmind_advanced 生成的 Markdown 文件，还原为原始 JSON 结构。
        支持用户在 XMind 或文本编辑器中修改后导回 JSON。

    参数说明:
        md_file (str): Markdown 文件路径
        output_file (str): 输出 JSON 文件路径，默认为 MD 同目录下同名 .json 文件

    异常说明:
        FileNotFoundError: MD 文件不存在时抛出
    """
    import re

    if not os.path.exists(md_file):
        raise FileNotFoundError(f"Markdown 文件不存在: {md_file}")

    with open(md_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 默认输出路径：与 MD 文件同目录、同名但后缀为 .json
    if output_file is None:
        output_file = os.path.splitext(md_file)[0] + ".json"

    test_points = []
    current_module = None
    current_feature = None
    current_scenario = None

    # 用于处理没有 #### 场景层级时，使用 - 子场景 或默认值
    _scenario_fallback = None

    # 扫描现有 TP 编号，确定自动编号起始值
    max_tp_num = 0
    for line in lines:
        m = re.search(r'\[TP(\d+)\]', line)
        if m:
            num = int(m.group(1))
            if num > max_tp_num:
                max_tp_num = num
    _tp_counter = max_tp_num

    for i, raw_line in enumerate(lines):
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        # ## 模块名
        m = re.match(r'^## (.+)$', line)
        if m:
            current_module = m.group(1).strip()
            _scenario_fallback = None
            continue

        # ### [TPxxx] 测试点内容（标题层级的测试点，无feature/scene层级）
        m = re.match(r'^### \[(TP\d+)\]\s*(.+)$', line)
        if m and current_module:
            tp_id = m.group(1)
            rest = m.group(2)
            risk_level = parse_risk_from_text(rest)
            for icon in _RISK_ICON_TO_LEVEL:
                rest = rest.replace(icon, '')
            test_point = rest.strip()
            test_points.append({
                "id": tp_id,
                "module": current_module,
                "feature": current_module,
                "scenario": "默认场景",
                "test_point": test_point,
                "risk_level": risk_level,
            })
            continue

        # ### 功能名
        m = re.match(r'^### (.+)$', line)
        if m:
            current_feature = m.group(1).strip()
            current_scenario = None
            _scenario_fallback = None
            continue

        # #### 场景名（标准格式）
        m = re.match(r'^#### (.+)$', line)
        if m:
            current_scenario = m.group(1).strip()
            _scenario_fallback = None
            continue

        # \t- [TPxxx] 测试点内容（带编号）
        m = re.match(r'^\s*- \[(TP\d+)\]\s*(.+)$', line)
        if m and current_module and current_feature:
            # 确定场景：优先用 current_scenario，其次用 _scenario_fallback
            scenario = current_scenario or _scenario_fallback or "默认场景"
            tp_id = m.group(1)
            rest = m.group(2)
            risk_level = parse_risk_from_text(rest)
            # 移除末尾的风险图标，得到纯测试点文本
            for icon in _RISK_ICON_TO_LEVEL:
                rest = rest.replace(icon, '')
            test_point = rest.strip()

            test_points.append({
                "id": tp_id,
                "module": current_module,
                "feature": current_feature,
                "scenario": scenario,
                "test_point": test_point,
                "risk_level": risk_level,
            })
            # 将当前场景设为 fallback，后续同场景的测试点可复用
            _scenario_fallback = scenario
            continue

        # - 测试点内容（无编号，自动分配 TP 编号）
        m = re.match(r'^\s*- (.+)$', line)
        if m and current_module and current_feature:
            # 判断是否为缩进的列表项（\t 或 4个空格缩进）
            is_indented = raw_line.startswith('\t') or raw_line.startswith('    ')

            if not is_indented:
                # 非缩进列表项：向前扫描，判断是否有缩进的子项（\t-）
                # 有子项 → 作为场景层级（scenario），无子项 → 作为测试点
                text = m.group(1).strip()
                has_children = False
                for j in range(i + 1, min(i + 10, len(lines))):
                    next_raw = lines[j]
                    next_stripped = next_raw.strip()
                    if not next_stripped:
                        continue  # 跳过空行
                    # 遇到标题，停止搜索
                    if re.match(r'^#', next_raw):
                        break
                    # 遇到非缩进的 - 列表项（同级），停止搜索
                    if re.match(r'^- ', next_stripped) and not (next_raw.startswith('\t') or next_raw.startswith('    ')):
                        break
                    # 遇到缩进的 - 列表项 → 有子项
                    if (next_raw.startswith('\t') or next_raw.startswith('    ')) and re.match(r'^\s*- ', next_raw):
                        has_children = True
                        break

                if has_children:
                    # 有子项，作为场景名
                    current_scenario = text
                    continue

            # 缩进列表项 或 无子项的非缩进列表项 → 作为测试点
            _tp_counter += 1
            tp_id = f"TP{_tp_counter:03d}"
            rest = m.group(1).strip()
            risk_level = parse_risk_from_text(rest)
            for icon in _RISK_ICON_TO_LEVEL:
                rest = rest.replace(icon, '')
            test_point = rest.strip()
            scenario = current_scenario or _scenario_fallback or "默认场景"

            test_points.append({
                "id": tp_id,
                "module": current_module,
                "feature": current_feature,
                "scenario": scenario,
                "test_point": test_point,
                "risk_level": risk_level,
            })
            _scenario_fallback = scenario
            continue

        # - 子场景名（列表项格式，作为场景层级）——仅在未进入 feature 上下文时生效
        m = re.match(r'^\s*- (.+)$', line)
        if m and not current_feature:
            current_scenario = m.group(1).strip()
            _scenario_fallback = None
            continue

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(test_points, f, ensure_ascii=False, indent=2)

    print(f"JSON 文件已生成: {output_file}")
    print(f"共解析 {len(test_points)} 条测试点")


if __name__ == "__main__":
    # 支持命令行指定文件路径，不指定则自动选择最新文件
    # 用法: python3 jsontomd.py [json或md文件路径] [--reverse]
    #md转json：python3 jsontomd.py output/test_points_res/个人中心测试点.md
    #json转md：python3 jsontomd.py output/test_points/test_points_20260604_173826.json --reverse，或直接运行python3 jsontomd.py
    reverse_mode = "--reverse" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if args:
        file_path = args[0]
    elif reverse_mode:
        # 反向模式：自动选择 output/test_points 下最新的 .md 文件
        md_pattern = os.path.join(TEST_POINTS_DIR, "*.md")
        md_files = glob.glob(md_pattern)
        if not md_files:
            print(f"目录 {TEST_POINTS_DIR} 下未找到任何 .md 文件")
            sys.exit(1)
        file_path = max(md_files, key=os.path.basename)
        print(f"自动选择最新文件: {file_path}")
    else:
        file_path = get_latest_json_file(TEST_POINTS_DIR)
        print(f"自动选择最新文件: {file_path}")

    if reverse_mode or file_path.endswith(".md"):
        md_to_json(file_path)
    else:
        json_to_xmind_advanced(file_path)