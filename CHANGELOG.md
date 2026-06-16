# Changelog

本文件记录 ModLink Studio 的重要变更。

## [0.3.2] - 2026-06-16

### Summary

`0.3.2` 在 `0.3.1` 稳定性修订基础上补齐 replay seek、recording manifest 元数据和录制导出体验。公开安装入口仍是单主包 `modlink-studio`，SDK / driver API 仍处于早期阶段。

### Added

- replay 时间轴支持滑块拖动和点击 seek，长录制 seek 使用 `qint64` 信号避免纳秒值溢出
- recording 停止或失败时在 `recording.json` 落盘开始/结束时间、状态、持续时间和各 stream 帧数
- replay recordings 列表 tooltip 展示录制时长、帧数、状态、session 和 experiment 信息
- 导出路径接入按 recording 组织的 bundle 输出，支持单录制、多录制和时间切片导出
- 根包补齐 `pillow` 依赖，确保 PNG / ZIP 图像导出 formatter 在主包环境可用
- `modlink-server` 入口新增 `--host` / `--port` CLI 参数，支持自定义监听地址

### Fixed

- 修复 replay seek 后 stale snapshot 把滑块短暂拉回旧位置的竞态
- 修复时间切片导出使用相对 UI 时间却按绝对 frame timestamp 过滤的问题
- 修复导出对话框选择的输出目录未传入 backend 的问题
- 修复 UI 导出成功但旧 `ExportService` 只创建空目录的问题

### Changed

- 导出对话框暂时隐藏未实现的 raw 副本和 zip 打包选项，避免发布候选版暴露误导性控件

### Known Limitations

- 跨录制单流导出已有 core handler，但当前 widgets UI 暂未提供专门入口
- 导出任务历史持久化、打开输出文件夹按钮、schema version / checksum / lineage 不属于 `0.3.2` 范围

---

## [0.3.2rc2] - 2026-06-16

### Summary

`0.3.2rc2` 在 `0.3.2rc1` 基础上新增 server CLI 参数化，其余内容与 `0.3.2rc1` 一致。

### Added

- `modlink-server` 入口新增 `--host` / `--port` CLI 参数，支持自定义监听地址

---

## [0.3.2rc1] - 2026-06-08

### Summary

`0.3.2rc1` 是 `0.3.2` 的 release candidate，重点补齐 replay seek、recording manifest 元数据和录制导出体验。公开安装入口仍是单主包 `modlink-studio`，SDK / driver API 仍处于早期阶段。

### Added

- replay 时间轴支持滑块拖动和点击 seek，长录制 seek 使用 `qint64` 信号避免纳秒值溢出
- recording 停止或失败时在 `recording.json` 落盘开始/结束时间、状态、持续时间和各 stream 帧数
- replay recordings 列表 tooltip 展示录制时长、帧数、状态、session 和 experiment 信息
- 导出路径接入按 recording 组织的 bundle 输出，支持单录制、多录制和时间切片导出
- 根包补齐 `pillow` 依赖，确保 PNG / ZIP 图像导出 formatter 在主包环境可用

### Fixed

- 修复 replay seek 后 stale snapshot 把滑块短暂拉回旧位置的竞态
- 修复时间切片导出使用相对 UI 时间却按绝对 frame timestamp 过滤的问题
- 修复导出对话框选择的输出目录未传入 backend 的问题
- 修复 UI 导出成功但旧 `ExportService` 只创建空目录的问题

### Changed

- 导出对话框暂时隐藏未实现的 raw 副本和 zip 打包选项，避免发布候选版暴露误导性控件

### Known Limitations

- 跨录制单流导出已有 core handler，但当前 widgets UI 暂未提供专门入口
- 导出任务历史持久化、打开输出文件夹按钮、schema version / checksum / lineage 不属于 `0.3.2rc1` 范围

---

## [0.3.1] - 2026-05-26

### Summary

`0.3.1` 是 `0.3.0` 之后的稳定性修订版本，重点修复了一个长时间录制时会触发自动停止的关键 bug，并整体改善桌面宿主的启动体验。发布边界继续沿用 `0.3.0` 的 Qt 版本约束 `>=6.10.2,<6.11`，公开安装入口仍是单主包 `modlink-studio`。

### Added

- 启动期间显示 qfluentwidgets `SplashScreen`，承载左上角版本徽章、底部状态文案和全宽 indeterminate 进度条
- recording 写盘时持久化 `session_name` 与 `experiment_name` 标签字段到 `recording.json`
- 回放页面支持删除 recording：列表页右键菜单和 player 页头部按钮均可触发，附确认对话框

### Fixed

- **录制超过约三小时后自动停止**：`storage/recordings.py::_append_stream_frame` 之前每写入一帧都会读取一次 `frames.csv` 计算下一帧索引，写入成本随帧数增长为 O(N²)。约 100k 帧后单帧写入耗时超过帧队列间隔，触发 overflow 后录制静默停止。`append_recording_frame` 改为接受 keyword-only 参数 `frame_index`，由 `RecordingBackend` 用内存计数器派生，热路径不再读盘
- 修复启动期间 splash 左上角 `ModLink Studio` 版本徽章的 inline 样式被 qfluentwidgets 主题刷新覆盖、退化为纯文字的问题
- 修复 Windows 任务栏图标偶发回退为 `python.exe` 默认图标的问题，进程显式绑定到自定义 AppUserModelID

### Changed

- 桌面启动主路径瘦身为约 75 行直线脚本，移除 `_LaunchOptions`、`_RuntimeDeps` 等过度设计的中间结构
- 启动期间 heavy import（`modlink_core` / `modlink_ui` / `pyqtgraph`）放到后台线程执行，主线程同时 pump Qt 事件保持 splash 动画
- 实验侧栏的 AI assistant runtime 移到 `modlink_ui.assistant` 子包

### Removed

- 删除从未在生产代码中使用的 `storage/sessions.py` 和 `storage/experiments.py` 死代码
- 删除桌面启动入口的 `debug_bootstrap.py` 死代码

### Known Limitations

- session / experiment 目前以扁平标签字段存储在 `recording.json`，列表与详情 UI、按字段筛选与归档仍待 `0.3.x` 后续版本补齐
- 启动期间 `MainWindow` 构造与首帧 paint 仍在主线程同步执行，splash 关闭前会有约一秒的进度条停顿，后续在 `0.3.x` 继续打磨

---

## [0.3.0] - 2026-04-28

### Summary

`0.3.0` 是 `0.2.0` 之后的正式版本，收口 recording replay、analysis export、widgets 主宿主回放页面、live experiment sidebar / AI assistant 原型，以及外部插件 author skill。正式版本沿用 `0.3.0rc3` 的 Qt 版本约束，避开 Qt 6.11.0 在 Windows 上暴露 ComboBox popup 透明边界的问题。

### Changed

- 将版本号从 `0.3.0rc3` 提升到 `0.3.0`
- 正式发布口径切到 PyPI；TestPyPI 仅保留为发布前 rehearsal
- 保持 PyQt6 / PyQt6-Qt6 `>=6.10.2,<6.11` 约束

---

## [0.3.0rc3] - 2026-04-28

### Summary

`0.3.0rc3` 是 `0.3.0` 工作线上的第三个 release candidate，主要修正 rc2 对 Windows 下拉菜单透明外框问题的处理方式：不再在 UI 层 patch QFluentWidgets popup，而是约束 PyQt6 / Qt6 到 6.11 之前的版本。

### Changed

- 将 PyQt6 / PyQt6-Qt6 约束为 `>=6.10.2,<6.11`，避免 Qt 6.11.0 在 Windows 上暴露 ComboBox popup 透明边界
- 移除 rc2 中针对 ComboBox popup margin 的 UI workaround

---

## [0.3.0rc2] - 2026-04-27

### Summary

`0.3.0rc2` 是 `0.3.0` 工作线上的第二个 release candidate，主要尝试缓解 Windows 下 QFluentWidgets 下拉菜单外层透明边框的问题，并继续保持 `0.3.0rc1` 的发布边界。

### Fixed

- 初步收窄 ComboBox popup 在 Windows 桌面合成 / OpenGL 预览场景下出现额外透明外框的问题；后续在 `0.3.0rc3` 改为通过 Qt 版本约束处理

---

## [0.3.0rc1] - 2026-04-27

### Summary

`0.3.0rc1` 是 `0.3.0` 工作线上的首个 release candidate。它在 `0.2.0` 的纯 Python runtime 基线上，重点补齐 recording replay、analysis export、当前 widgets 宿主里的回放页面，以及外部插件 author skill。

这一版仍按预发布版本处理；公开安装入口继续收口为单主包 `modlink-studio`，外部 driver 项目仍依赖 `modlink-studio` 并通过 `modlink.drivers` entry point 被宿主发现。

---

### Added

- 新增 `modlink_core.replay`，提供 `RecordingReader`、`ReplayBackend` 和 `ExportService`
- widgets 主应用接入 Replay 页面，支持 recordings 列表、播放 / 暂停 / 停止、1x / 2x / 4x 和 annotations 展示
- 新增 analysis-first 导出能力，首批覆盖 `signal_csv`、`signal_npz`、`raster_npz`、`field_npz`、`video_frames_zip` 和 `recording_bundle_zip`
- 新增 live experiment AI assistant 原型，支持 OpenAI-compatible Chat Completions 和本地工具调用
- 新增 `tools/modlink-plugin-author` skill，作为 Claude Code / Codex 编写外部 driver plugin 的推荐入口

### Changed

- Qt Widgets UI 包结构收敛为 `shell + features + shared + bridge`
- Replay 页面从单页 splitter 调整为 recordings 列表页、player 页和 export 页
- 录制写盘与读取路径继续围绕 `recordings/`、`recording.json`、`streams/<stream_id>/stream.json`、`frames.csv` 和 `frames/*.npz` 收敛
- pytest 默认使用 `--import-mode=importlib`，并忽略外部插件目录、构建产物和 `node_modules`

### Fixed

- 改进 Windows 下 settings 文件原子替换的重试处理，降低并发保存时的 transient `PermissionError` 风险

### Removed

- 删除已不再维护的 QML / Web 宿主路线包，当前桌面宿主收敛到 widgets 主宿主 `modlink_studio`
- 移除独立 npm 版 plugin scaffold，不再维护第二套插件生成入口
- 移除实验性 Python plugin AI agent，改用可分发 skill 指导成熟 coding agent

### Known Limitations

- `0.3.0rc1` 仍是预发布版本，session / protocol 工作流尚未完整收口
- 外部插件 author skill 只指导 coding agent 编写插件项目，不替代真实设备协议确认和硬件验证
- `modlink-plugin` 当前仍主要覆盖官方驱动安装路径，后续会继续扩展为更完整的插件管理工具

---

## [0.2.0] - Released

### Summary

`0.2.0` 是 `0.1.x` 之后的基础链路稳定化版本。

这一版本的重点不是在 `0.1.x` 基础上继续堆叠功能，而是把项目从以 Qt 风格 driver 为中心的实现，重构为以纯 Python runtime 为中心的结构。`0.2.0` 主要完成的是边界重整与基础链路稳定化，为后续版本的实验工作流、回放能力和 AI 辅助能力打地基。

在 UI 方向上，`0.1.x` 实际上只有一条以 Qt Widgets 为主的界面路线；`0.2.0` 则首次明确开始推进新的 UI 方向。这里的 `new UI` 不是单指某一个新界面，而是两条并行推进的方向：

- 一条是基于 QML 的新桌面 UI 路线
- 一条是以 FastAPI server host 为边界、为后续 HTML / Web UI 做准备的服务化路线

这样做不是为了简单“多做一个 UI”，而是因为随着实时预览类型、界面层级和后续交互复杂度增加，Qt Widgets 在表达能力、组织方式和后续演进空间上的局限已经越来越明显，因此需要为后续版本提前建立新的 UI / host 路线。

`0.2.0` 当前锁定的发布边界是：

- 安装与启动
- 设备搜索与连接
- 实时流预览
- 开始 / 停止采集
- 录制与保存
- 插件安装与外部 driver 接入
  - `0.2.0` 公开分发面收口为单主包 `modlink-studio`

录制回放不属于 `0.2.0` 的发布范围，已整体延后到 `0.3.0`。

这一版本的公开安装入口以 **PyPI** 为准；`TestPyPI` 只用于发布前 rehearsal，不作为日常安装源。

`0.2.0` 的 `TestPyPI rehearsal` 已完成；正式稳定版使用 `0.2.0`，公开安装入口以 PyPI 为准。

---

### Breaking Changes

- 从 `0.1.x` 的 Qt-style driver API 切换到新的纯 Python runtime driver 模型
- `modlink_sdk` 与 `modlink_core` 不再以 Qt 作为运行时前提
- 现有 `0.1.x` driver 与 `0.2.0` 不兼容，需要迁移到新的 runtime-oriented driver API
- Monorepo 内部边界重新整理，明确区分为三类：
  - 基础包：
    - `modlink_sdk`
    - `modlink_core`
    - `modlink_ui`
    - `modlink_ui_qt_qml`
  - 宿主入口：
    - `modlink_studio`
    - `modlink_studio_qml`
    - `modlink_server`

---

### Added

#### Runtime / Core

- 引入以 `ModLinkEngine` 为中心的运行时结构
- 引入 `DriverPortal`、`StreamBus`、`AcquisitionBackend`、`SettingsService` 等核心能力
- 增加后端事件流和 snapshot 风格的状态传播方式
- 将更多采集、设置和状态同步逻辑收回到 runtime / backend 侧

#### Application Hosts

- 新增 `modlink_server`，作为 FastAPI 形式的 server host
- 新增 `modlink_studio_qml`，承载 QML UI 宿主方向
- `modlink_studio` 继续作为主桌面宿主入口保留
- `modlink_server` 当前并不等于完整 Web UI，但它已经把后续 HTML / Web 前端所需的 host 边界先建立出来

#### UI / Preview

- `0.1.x` 的单一 Qt Widgets UI 路线在 `0.2.0` 中开始扩展为 Widgets + new UI 并行结构
- `new UI` 在当前阶段包含两个方向：
  - 基于 QML 的新桌面 UI
  - 基于 FastAPI host 的服务化边界，为后续 HTML / Web UI 做准备
- 新增 `modlink_ui_qt_qml`，承载新的 QML UI 方向
- 增加 QML 侧 preview controller / preview store / preview pipeline
- 补齐录制完成与录制失败时的结果提示，UI 可明确看到 session、recording_id 和保存路径
- Qt Widgets 主页面补齐空状态提示，避免无流时出现空白展示页

#### Plugin / Ecosystem

- 官方驱动从主仓库拆出，迁移到独立仓库 `ModLink-Studio-Plugins`，并改为通过主包插件管理命令 + GitHub 发布物安装
- 外部 driver 开发路径明确为：
  - 外部插件项目依赖公开主包 `modlink-studio`
  - driver 代码从随主包分发的 `modlink_sdk` 导入 SDK 契约
  - 使用 `modlink.drivers` entry points 暴露 driver

#### Testing / Tooling

- 补齐和扩展了以下测试覆盖：
  - 纯 Python runtime
  - stream bus 行为
  - storage utilities / writers
  - QML smoke tests
  - preview 相关 UI 行为
- 根仓库加入 `ruff`、`pre-commit`、`.editorconfig`、`.gitattributes`
- 根工作区开发环境现在默认可以覆盖 `modlink_server` 的测试与入口

---

### Changed

#### Architecture

- 以 runtime 为中心重构项目结构，降低 UI 对系统语义的直接承担
- 将更多系统行为从 UI 侧逻辑收束到 backend / runtime 服务
- 明确 bridge 层的职责是适配，而不是承载新的后端语义

#### Driver Model

- 收紧 driver 最小公共契约
- 强化基于 entry point 的插件发现策略
- 对损坏的 entry point、无效 driver 定义和未知 payload 维持 fail-fast 行为

#### Acquisition / Recording

- 重整 acquisition backend 与录制生命周期控制
- 重新梳理 marker / segment 相关链路
- 固定 `recording.json`、`annotations/`、`streams/` 的基本录制目录结构，为后续回放提供稳定输入基础

#### UI Structure

- 调整 `modlink_ui` 的页面和主界面组织方式
- 明确从 `0.1.x` 的单一 Widgets UI，过渡到 Widgets 与 QML/new UI 并行的结构
- 开始推进 new UI 的原因，是 Qt Widgets 在复杂实时预览、后续界面扩展和表现层组织上的局限逐渐显现
- 这里的 new UI 不只是一套 QML 界面，也包括以 `modlink_server` 为入口的服务化 host 边界，用于承接后续 HTML / Web UI
- QML UI 继续沿新结构迭代，Widgets 与 QML 维持并行
- 主页面与采集面板的默认交互更明确，不再依赖隐式状态理解

#### Documentation

- 更新安装说明、driver 开发说明和项目结构说明
- 公开安装与分发表述统一切到 PyPI / TestPyPI rehearsal 口径
- 将路线图正式纳入仓库，并要求实现内容同步更新 `ROADMAP.md`

---

### Fixed

- 修复 `SignalStreamView` 测试中的构造签名回归
- 修复 `modlink_server` 在根工作区开发环境中缺少测试依赖的问题
- 改进 Windows 下 settings 原子写入的稳定性，降低并发写入时的 `PermissionError` 风险
- 改善 widgets / QML 采集结果提示，使录制结果更容易被用户确认

---

### Removed

- 删除历史 `deprecated/` 目录，不再保留旧实现入口
- 不再把录制回放视作 `0.2.0` 的发布前置能力

---

### Plugin Management

`0.2.0` 当前提供以下官方驱动：

- Host Camera
- Host Microphone
- OpenBCI Ganglion

当前阶段的插件安装方式：

- 先安装 `modlink-studio`
- 再运行 `modlink-plugin install <plugin_id>`
- 官方驱动索引与 wheel 资产由独立仓库 `ModLink-Studio-Plugins` 提供

当前命令集主要覆盖官方驱动；插件索引已经改为远端 JSON manifest，后续版本会继续扩展为更通用的插件管理工具。

---

### Migration Notes

从 `0.1.x` 升级到 `0.2.0` 时，需要注意：

1. 旧 driver 需要迁移到新的 runtime-oriented driver API
2. 外部 driver 插件项目应依赖公开主包 `modlink-studio`
3. driver 代码继续从 `modlink_sdk` 导入 SDK 契约，设备自身的传输层依赖按需添加
4. 插件发现基于 `modlink.drivers` entry points
5. `0.2.0` 的公开安装入口以单主包 `modlink-studio` 为准；`TestPyPI` 只用于发布前 rehearsal

---

### Known Limitations

- UI 仍处于适配期，Qt Widgets 与 QML 继续并行演进
- Backend 已脱离 Qt，但 bridge 与 host 集成仍有继续打磨空间
- `Experiment / Participant / Session / Protocol` 不属于 `0.2.0`
- AI 辅助工作流不属于 `0.2.0`
- Web UI 不属于 `0.2.0`
- 录制回放已明确延后到 `0.3.0`

---

### Notes on Release Scope

`0.2.0` 的目标不是“做完所有规划中的能力”，而是先把基础采集链路做稳：

- install
- launch
- search devices
- connect
- preview streams
- start / stop acquisition
- record and save
- install plugins through `modlink-plugin`

这一版本是后续能力的结构基础：

- `0.3.x`：实验工作流与回放
- `0.4.x`：AI 辅助 session 管理
- `0.5.x`：更广泛的生态与外部接口
