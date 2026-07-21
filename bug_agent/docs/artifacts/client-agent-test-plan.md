# CLIENT AGENT 类型测试计划

**测试日期**: 2026-03-28  
**测试范围**: 验证 client AGENT 类型在系统中的完整性

---

## 一、测试环境准备

### 1.1 数据库更新
执行 SQL 脚本为现有用户添加 client 类型：
```bash
# 连接数据库
psql -h <host> -U <user> -d <database>

# 执行更新脚本
\i server/scripts/add_client_agent_type.sql
```

### 1.2 服务重启
```bash
# 重启后端服务
cd server && go run ./cmd/server/

# 重启前端服务
cd web && npm run dev
```

---

## 二、功能测试用例

### 2.1 用户注册测试
**用例 ID**: TC-001  
**测试目的**: 验证新用户默认拥有 6 种 AGENT 类型  
**前置条件**: 系统正常运行  
**测试步骤**:
1. 注册新用户 `test_client_agent`
2. 查询数据库 `users` 表
3. 检查 `agent_types` 字段

**预期结果**:
```
agent_types = "product,ui,frontend,client,backend,test"
```

**验证 SQL**:
```sql
SELECT username, agent_types 
FROM users 
WHERE username = 'test_client_agent';
```

---

### 2.2 缺陷分析测试
**用例 ID**: TC-002  
**测试目的**: 验证可触发 client AGENT 分析  
**前置条件**: 已创建缺陷，用户已登录  
**测试步骤**:
1. 打开缺陷详情页
2. 点击"触发分析"按钮
3. 在 AGENT 类型选择弹窗中勾选"客户端AGENT"
4. 点击"开始分析"

**预期结果**:
- ✅ 弹窗显示 6 种 AGENT 类型（包括 client）
- ✅ 可以勾选 client 类型
- ✅ 提交成功，生成分析报告
- ✅ 报告显示 `agentType: "client"`

---

### 2.3 修复任务测试
**用例 ID**: TC-003  
**测试目的**: 验证可创建 client AGENT 修复任务  
**前置条件**: 分析报告已生成  
**测试步骤**:
1. 在缺陷详情页查看分析报告
2. 点击"创建修复任务"
3. 选择 AGENT 类型为"客户端AGENT"
4. 填写修复计划
5. 提交创建

**预期结果**:
- ✅ 修复任务创建成功
- ✅ 任务显示 `agentType: "client"`
- ✅ 任务列表正确显示"客户端AGENT"标签

---

### 2.4 评论 @提及测试
**用例 ID**: TC-004  
**测试目的**: 验证可 @提及 client AGENT 用户  
**前置条件**: 有用户绑定了 client 类型  
**测试步骤**:
1. 在评论框输入 `@`
2. 查看提及列表
3. 选择绑定了 client 类型的用户
4. 发表评论

**预期结果**:
- ✅ 提及列表显示所有用户（包括 client 类型）
- ✅ 评论成功发送
- ✅ 被提及用户收到通知

---

### 2.5 用户 AGENT 类型更新测试
**用例 ID**: TC-005  
**测试目的**: 验证用户可更新自己的 AGENT 类型  
**前置条件**: 用户已登录  
**测试步骤**:
1. 调用更新接口
2. 更新 `agentTypes` 为包含 client 的组合
3. 查询用户信息

**API 调用**:
```bash
curl -X PUT http://localhost:8765/api/auth/profile \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "agentTypes": "frontend,client,backend"
  }'
```

**预期结果**:
```json
{
  "code": 0,
  "data": {
    "id": 1,
    "username": "admin",
    "agentTypes": "frontend,client,backend"
  }
}
```

---

## 三、前端 UI 验证

### 3.1 缺陷详情页
**检查点**:
- [ ] AGENT 类型选择弹窗显示 6 个选项
- [ ] "客户端AGENT"选项说明为"分析客户端代码问题"
- [ ] 分析报告列表正确显示"客户端AGENT"标签
- [ ] 修复任务列表正确显示"客户端AGENT"标签

### 3.2 评论区域
**检查点**:
- [ ] AGENT 评论显示"🤖 客户端AGENT"
- [ ] 标签颜色为 `#4f46e5`（靛蓝色）

---

## 四、后端 API 验证

### 4.1 分析接口
**请求**:
```bash
POST /api/defects/{id}/analyze
{
  "agentTypes": ["client"]
}
```

**响应**:
```json
{
  "code": 0,
  "message": "分析已触发",
  "data": {
    "reportCode": "RPT-20260328-001",
    "agentType": "client"
  }
}
```

### 4.2 修复任务接口
**请求**:
```bash
POST /api/fix-tasks
{
  "defectId": 1,
  "agentType": "client",
  "plan": "修复客户端兼容性问题"
}
```

**响应**:
```json
{
  "code": 0,
  "message": "修复任务创建成功",
  "data": {
    "taskCode": "FIX-20260328-001",
    "agentType": "client"
  }
}
```

---

## 五、数据库验证

### 5.1 用户表
```sql
-- 检查所有用户的 AGENT 类型
SELECT id, username, agent_types 
FROM users 
WHERE deleted_at IS NULL;
```

**预期**: 所有用户的 `agent_types` 都包含 `client`

### 5.2 分析报告表
```sql
-- 检查是否有 client 类型的报告
SELECT id, report_code, agent_type 
FROM analysis_reports 
WHERE agent_type = 'client';
```

### 5.3 修复任务表
```sql
-- 检查是否有 client 类型的任务
SELECT id, task_code, agent_type 
FROM fix_tasks 
WHERE agent_type = 'client';
```

---

## 六、回归测试

### 6.1 现有功能不受影响
- [ ] 其他 5 种 AGENT 类型正常工作
- [ ] 缺陷创建/编辑/删除正常
- [ ] 评论和 @提及正常
- [ ] 状态流转正常

### 6.2 性能测试
- [ ] 分析接口响应时间 < 2s
- [ ] 列表查询响应时间 < 500ms
- [ ] 前端页面加载时间 < 1.5s

---

## 七、测试结果记录

| 用例 ID | 测试项 | 结果 | 备注 |
|---------|-------|------|------|
| TC-001 | 用户注册 | ⏳ | 待测试 |
| TC-002 | 缺陷分析 | ⏳ | 待测试 |
| TC-003 | 修复任务 | ⏳ | 待测试 |
| TC-004 | 评论 @提及 | ⏳ | 待测试 |
| TC-005 | 类型更新 | ⏳ | 待测试 |

**测试状态**: ⏳ 待执行  
**测试人员**: 待指定  
**测试环境**: 开发环境

---

_测试计划创建时间: 2026-03-28 14:20_
