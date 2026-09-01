# 接口自动化 Dating Comm 项目化界面设计 QA

## 证据

- 视觉真相：`/var/folders/0y/bx0h56fj4z5bypwbfr5l7nzr0000gn/T/codex-clipboard-fbd4e44d-0585-423b-98d7-f091c23b39f9.png`
- 实现地址：`http://localhost:8080/settings/config?scope_id=tps_e6c4218848a74086892a8abd87c7e8b8`
- 浏览器实现截图：`/Users/admin/Testproject/test-platform/design-qa-implementation-auth-blocked.png`
- 同画布对比：`/Users/admin/Testproject/test-platform/design-qa-comparison-auth-blocked.png`
- 目标状态：DEV 平台、Dating/test Runtime Scope、当前生效 v3、只读展示已发布 Comm 静态值及版本历史。
- 实际状态：Chrome 中原有平台会话已过期，访问目标地址后跳转至登录页；没有读取或提交浏览器中保存的凭证。
- CSS 视口：1440 × 1000；Chrome 截图为 1425 × 1007 像素，浏览器默认设备密度。
- 源图为 1342 × 633 像素。合并对比时两张图等宽归一化到 1425 像素，中间使用 24 像素分隔带；由于认证状态不同，不进行组件级像素结论。

## Findings

- [P0] 无法捕获目标配置页面
  - 位置：`/settings/config`。
  - 证据：同画布对比上半部分是配置原型，下半部分是本机平台登录页；目标 URL 被重定向为 `/login?next=...`。
  - 影响：无法从真实浏览器证据核对已发布值、两列 Comm 栅格、版本切换、1280px 响应式与控制台错误，因此不能把视觉验收标记为通过。
  - 修复：用户在现有本地 Chrome 标签页完成登录后，重新捕获 Dating v3 的 1440px/1280px 页面并执行同画布比较。

## 必查保真面

- 字体与排版：受认证阻塞，目标页面尚未获得浏览器证据。
- 间距与布局：受认证阻塞，尚不能核对 Comm 两列栅格、历史版本行和桌面断点。
- 色彩与视觉令牌：代码继续复用平台现有 Apple-inspired 令牌，但尚不能据此替代可见页面检查。
- 图片与资产：该页面没有产品图或插画；本轮不涉及图像资产替换。
- 文案与内容：单元测试已锁定当前生效值、历史版本切换、动态字段不展示和自定义静态字段编辑；仍需真实页面复核。

## 全屏与局部证据

- 全屏对比：`design-qa-comparison-auth-blocked.png` 已将源图与本机浏览器截图放入同一比较输入，明确显示状态不一致。
- 局部对比：未执行。目标配置区域没有成功渲染，裁切登录页不会增加有效判断信息。

## 比较历史

1. 首轮：打开指定 Dating Scope 配置地址，平台返回登录页；记录为 P0 认证阻塞。
2. 尚无修复后视觉轮次。代码、数据迁移和自动化测试已完成，但这些证据不能替代浏览器实现截图。

## 实施检查清单

- [x] Dating Comm Definition 增加静态字段契约、动态字段黑名单和项目白名单。
- [x] Dating/test 生成独立 v3 Comm，Truthy 当前版本和值保持不变。
- [x] 当前生效版本值、历史版本查看和草稿结构化编辑已实现并由前端测试覆盖。
- [x] 后端、前端与接口自动化工具回归通过。
- [ ] 用户登录本机平台后，完成 1440px 与 1280px Chrome 视觉和交互验收。

final result: blocked
