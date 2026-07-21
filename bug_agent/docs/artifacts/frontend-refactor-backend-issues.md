# 前端重构后端接口适配问题

## 文档信息
- **日期**: 2026-03-29
- **版本**: v1.1
- **重构范围**: 项目优先层级架构改造
- **状态**: ✅ 已全部解决

---

## 1. 缺少项目统计数据接口

### 问题描述
原型设计中项目列表卡片需要显示每个项目的 **待处理缺陷数** 和 **进行中缺陷数**。

### 当前状态
✅ **已解决** - 新增 `GET /user/projects` 接口，返回项目统计和成员信息

### 实现方案
新增用户项目列表接口，一次性返回所有需要的数据：
```json
{
  "id": 1,
  "name": "Bug Agent",
  "code": "AGENT",
  "orgName": "TechCorp",
  "status": "active",
  "pendingDefects": 12,
  "activeDefects": 3,
  "members": [
    { "id": 1, "nickname": "张三", "avatar": "..." }
  ],
  "memberCount": 8
}
```

---

## 2. 项目列表接口缺少项目成员头像

### 问题描述
原型设计中项目卡片需要显示项目成员头像堆叠。

### 当前状态
✅ **已解决** - `GET /user/projects` 接口已包含 `members` 字段

### 返回数据
```json
{
  "members": [
    { "id": 1, "nickname": "张三", "avatar": "..." },
    { "id": 2, "nickname": "李四", "avatar": "..." }
  ],
  "memberCount": 8
}
```

---

## 3. 缺少用户项目列表接口

### 问题描述
新的信息架构要求首页显示 **用户参与的所有项目**，而非按组织分组。

### 当前状态
✅ **已解决** - 新增 `GET /user/projects` 接口

### 接口定义
```
GET /user/projects
Response: {
  "list": [
    { "id": 1, "name": "Bug Agent", "orgName": "TechCorp", ... }
  ]
}
```

---

## 4. 项目工作台统计数据

### 问题描述
项目工作台需要显示项目级别的缺陷统计。

### 当前状态
✅ **已解决** - 新增 `GET /projects/:id/stats` 接口

### 接口定义
```
GET /projects/:id/stats
Response: {
  "total": 128,
  "pending": 12,
  "fixing": 8,
  "completed": 98,
  "urgent": 3
}
```

---

## 5. 全局搜索接口（未实现）

### 问题描述
全局顶部导航栏有搜索框，支持搜索项目、缺陷等。

### 当前状态
⏸️ **暂缓** - 优先级较低，前端搜索框已渲染但功能暂未实现

### 建议方案（未来实现）
新增全局搜索接口：
```
GET /search?q=keyword&type=all
Response: {
  "projects": [...],
  "defects": [...],
  "users": [...]
}
```

---

## 实现记录

### 新增后端文件
- `server/internal/handler/user_projects.go` - 用户项目列表和项目统计处理器

### 新增API端点
| 端点 | 方法 | 说明 |
|------|------|------|
| `/user/projects` | GET | 获取当前用户参与的所有项目（含统计、成员） |
| `/projects/:id/stats` | GET | 获取项目缺陷统计汇总 |

### 前端更新
- `web/src/api/index.ts` - 新增 `listUserProjects()` 和 `getProjectStats()` 函数
- `web/src/pages/projects/ProjectList.tsx` - 使用新API，显示成员头像和缺陷统计
- `web/src/pages/projects/ProjectDashboard.tsx` - 使用新API获取统计数据

---

## 接口测试结果

### GET /user/projects
```bash
curl -s "http://localhost:8765/api/v1/user/projects" -H "Authorization: Bearer $TOKEN"
# 返回:
{"code":0,"message":"success","data":{"list":[{"activeDefects":1,"code":"DEMO",...,"pendingDefects":6,...,"members":[{...}],"memberCount":5}]}}
```

### GET /projects/:id/stats
```bash
curl -s "http://localhost:8765/api/v1/projects/2/stats" -H "Authorization: Bearer $TOKEN"
# 返回:
{"code":0,"message":"success","data":{"completed":0,"fixing":1,"pending":6,"total":7,"urgent":0}}
```

---

## 优先级完成情况

| 优先级 | 问题 | 状态 |
|--------|------|------|
| P0 | 缺少用户项目列表接口 | ✅ 已解决 |
| P1 | 项目统计数据接口 | ✅ 已解决 |
| P1 | 项目工作台统计 | ✅ 已解决 |
| P2 | 项目成员头像 | ✅ 已解决 |
| P3 | 全局搜索接口 | ⏸️ 暂缓 |
