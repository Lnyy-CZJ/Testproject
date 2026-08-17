# 第三方组件声明

本目录包含自托管的 Mind Elixir 5.14.0 浏览器分发文件，仅供功能测试工作台脑图视图使用。

- 上游项目：https://github.com/SSShooter/mind-elixir-core
- npm 包：`mind-elixir@5.14.0`
- 许可证：MIT，原文保存在 `5.14.0/LICENSE`
- 加载方式：平台本地静态文件，不使用 CDN，不产生上游网络请求

`tests/ui/vendor-integrity.test.mjs` 固定校验已纳入运行时的 JavaScript、CSS 与许可证文件 SHA-256。
