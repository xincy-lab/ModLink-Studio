---
layout: home

hero:
  name: ModLink Studio
  text: 设备接入、多模态采集与展示的文档站
  tagline: 了解 0.3.2rc2 的 PyPI 发布口径、driver 契约、回放与导出能力和当前 widgets 宿主路线
  actions:
    - theme: brand
      text: 开始安装
      link: /install
    - theme: alt
      text: 查看 SDK
      link: /sdk

features:
  - icon: 📦
    title: PyPI 安装
    details: 0.3.2rc2 作为 0.3.2 release candidate 走 PyPI；TestPyPI 仅用于发布链路演练。
  - icon: 🔌
    title: Driver 接入
    details: 外部 driver 优先依赖仓库内的 SDK 契约，通过 modlink.drivers entry point 被宿主发现。
  - icon: 🧠
    title: 纯 Python Runtime
    details: SDK 与 Core 已从 Qt 运行时语义中拆开，宿主围绕统一流模型和采集后端工作。
  - icon: 🖥️
    title: Widgets 宿主
    details: 当前桌面宿主路线收敛到 Qt Widgets，FastAPI host 继续保留为服务化边界。
  - icon: ⚠️
    title: 0.3.2rc2 候选发布
    details: 0.3.2rc2 补齐 replay seek、recording 元数据和录制导出体验。
---

<div style="height: 1rem;"></div>

# ModLink Studio 文档总览

当前文档以 `0.3.2rc2` 主线为准。这里描述的是 `0.3.2rc2` 的当前边界：

- `modlink_sdk` / `modlink_core` 已经是纯 Python runtime
- SDK / driver API 仍处于早期阶段，`0.3.2rc2` 不保证兼容 `0.2.x` driver 实现
- 当前桌面宿主以 Qt Widgets 为准
- FastAPI host 已建立服务化边界，用于后续 HTML / Web UI
- recording replay、seek 与录制导出已接入当前 widgets 宿主
- `0.4.0` 预计会继续收紧 SDK 与插件管理边界

`0.3.2rc2` 的公开安装入口以 **PyPI** 为准；`TestPyPI` 只用于发布链路演练，不作为日常安装源。

## 从哪里开始

- 想安装和运行：看 [安装与发布](/install)
- 想接 driver：看 [SDK 开发者指南](/sdk)
- 想理解 runtime：看 [Core 模块架构](/core)
- 想看 UI / host 方向：看 [UI 模块架构](/ui) 和 [App 组合根](/app)
- 想查服务接口：看 [服务端 API 手册](/server-api)
- 想直接跳源码 API：看 [API 快速索引](/api)

## 三个正式入口

- 源码仓库：[github.com/modlink-studio/ModLink-Studio](https://github.com/modlink-studio/ModLink-Studio)
- 文档站点：[modlink-studio.github.io](https://modlink-studio.github.io)
- 正式发布渠道：PyPI
