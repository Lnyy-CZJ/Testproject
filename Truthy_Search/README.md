# searchTool

`searchTool` 按输入顺序调用以下接口并提取候选人的完整 `ui_sections`：

```text
CreateIntentTask → GetTask（每 5 秒轮询）
→ ListTaskCandidates（前 5 名）→ GetTaskCandidateDetail
```

## 安装

建议使用 Python 3.10 或更高版本：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 配置

复制配置模板并填写真实值：

```bash
cp .env.example .env
```

必须配置 `SEARCH_API_URL`、`AUTH_TOKEN`、`DEVICE_ID`、`USER_ID`。固定 HTTP 请求头写入 `SEARCH_HTTP_HEADERS_JSON`，其值必须为 JSON 对象。

## 准备输入

```bash
cp input/tasks.example.jsonl input/tasks.jsonl
```

`tasks.jsonl` 每行是一条搜索任务。`input_id` 和非空 `clues` 必填，`match_strategy` 默认 `UNION`，`additional_details` 默认空数组。

## 运行

```bash
python search_tool.py
```

也可指定路径：

```bash
python search_tool.py --input input/tasks.jsonl --output output --env-file .env
```

每次运行会清空并重新生成：

- `output/results.jsonl`：成功任务及其最多 5 名候选人的完整 `ui_sections`；
- `output/failures.jsonl`：输入、接口、未知状态或轮询超时错误。

退出码：全部成功为 `0`，配置或输入文件无法启动为 `1`，批次中存在失败为 `2`。

## 测试

测试使用模拟响应，不会调用真实接口：

```bash
python -m unittest discover -s tests -v
```
