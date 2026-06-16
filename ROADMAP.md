# ModLink Studio Roadmap

本文档记录当前版本边界、后续路线和明确不做的方向。它不是设计草稿合集；已经完成或废弃的探索只保留结论。

## 当前位置

`0.3.1` 已正式发布。`0.3.2rc2` 当前在 `wip/0.3.2` 推进，作为 `0.3.2` 的 release candidate。`0.3.x` 仍属于 SDK / driver API 的早期阶段，不承诺兼容 `0.2.x` driver 实现；`0.4.0` 预计会继续收紧 SDK 与插件管理边界。

`0.3.1` 重点修复：

- 长时间录制超过约三小时后自动停止的 bug
- 启动期间 splash 版本徽章样式被主题刷新覆盖的问题
- Windows 任务栏图标偶发回退为 `python.exe` 默认图标
- 桌面启动主路径精简，加入 splash screen 承载冷启动等待

分支约定：

- `legacy/0.2.x`：维护 `0.2.x` 稳定线
- `wip/0.3.x`：当前 `0.3.x` 维护与小步演进线
- `main`：发布合并目标

## 产品原则

- `modlink-studio` 继续作为公开安装入口，外部 driver plugin 依赖主包并通过 `modlink.drivers` entry point 被宿主发现。
- 主仓库维护宿主、SDK、core、UI 和插件管理入口；官方驱动源码和发布资产由独立插件仓库维护。
- `recording` 是最小数据资产，`session` 和 `experiment` 是上层组织关系，不反向塑造 recording 的内部结构。
- Core 保持纯 Python runtime；Qt 相关行为只留在 UI / bridge 层。
- 插件开发不再维护 npm scaffold 或自研 Python plugin AI agent；外部插件开发转向 `tools/modlink-plugin-author/SKILL.md`。
- UI 继续保持工具型、低装饰、少定制；新增能力优先通过已有页面、已有控件和 schema 化配置承载。
- 不为了未来 Web/QML 路线提前保留当前用不到的宿主包、适配层或扩展点。

## 0.3.0

状态：已发布。

`0.3.0` 在 `0.2.0` 的纯 Python runtime 基线上补齐：

- replay / export / widgets Replay 页面
- live experiment sidebar 与 AI assistant 原型
- `tools/modlink-plugin-author` skill 作为外部 driver plugin 的推荐起点
- `modlink-plugin` CLI 安装官方驱动
- PyQt6 / PyQt6-Qt6 约束为 `>=6.10.2,<6.11`，避开 Qt 6.11.0 在 Windows 上的透明 popup 边界问题

不属于 `0.3.0` 范围、转入 `0.3.x` / `0.4.x` 继续推进：

- 完整 protocol editor
- 任意时间轴 seek
- 多 recording 拼接
- live/replay 混播
- Web UI
- 新 QML 宿主
- 插件显示 / 隐藏 UI
- 独立插件注册中心

## 0.3.1

状态：已发布。

`0.3.1` 是 `0.3.0` 之后的稳定性修订。

已完成：

- 修复长时间录制（约三小时后）自动停止的关键 bug；recording 写盘热路径改为不再读取 frames 索引
- recording 持久化新增 `session_name` 与 `experiment_name` 扁平标签字段
- 回放页面支持通过列表页右键菜单和 player 页按钮删除 recording
- 启动期间显示 qfluentwidgets `SplashScreen`，并把 heavy import 放到后台线程
- 修复启动期间 splash 版本徽章样式被主题刷新覆盖的问题
- 修复 Windows 任务栏图标偶发回退的问题（绑定 AppUserModelID）
- 桌面启动主路径精简到约 75 行直线脚本

不属于 `0.3.1` 范围：

- session / experiment 列表 UI 与按字段筛选
- replay 时间轴 seek
- 启动期间 MainWindow 构造的进一步异步化

## 0.3.2

状态：进行中。

`0.3.2` 在 `wip/0.3.2` 分支推进，重点是把 replay 体验补齐到"可以正常用"的程度。

已完成：

- replay 时间轴任意位置 seek：core 后端新增 `seek` worker，使用 `bisect` 维护时间线索引；UI 用滑块控件触发拖动 / 点击两种 seek 提交方式
- replay player 页结构整理：原 `timeline.py` 模块的展示函数内联到 player 页，`page.py` 主路径精简
- preview view 体系新增 `clear()` 钩子，确保 seek 和复位时旧帧数据不会残留在 plot 上
- 修复滑块 seek 在长录制（>2.147 秒）下静默失败的 bug：`pyqtSignal` 改用 `qint64`，避免 ns 值溢出成负数被后端 clamp 到 0
- 修复滑块 seek 后 100 ms 轮询 stale snapshot 把滑块视觉拉回原位置的竞态：改用 300 ms 时间窗屏蔽 + 立即更新时间标签

不属于 `0.3.2` 范围：

- session / experiment 列表 UI 与按字段筛选
- 键盘左右箭头 seek
- marker / segment 编辑


### 导出系统重构
`0.3.2` 重点是导出系统重构：把原先零散注册的导出器替换成以录制为中心、按需选择内容、自描述的统一导出体验。SDK / driver API 接口保持不变。

`0.3.2rc2` 追加：

- server 入口 `modlink-server` 支持 `--host` / `--port` CLI 参数，替换原先硬编码的默认值

`0.3.2rc1` 已完成：

- 统一 `ExportRequest` dataclass，模式驱动 4 种导出（A 单录制 / B 多录制合并 / C 时间切片 / D 跨录制单流）
- 14 个 payload-aware formatter，按 signal / raster / field / video 与 annotations / metadata 分发
- `ExportPackageWriter`：临时目录写入 + 原子 rename，崩溃安全
- replay backend 导出路径接入真实 bundle 输出，支持关闭时取消 queued / running 导出任务
- 自描述导出包：`README.md` + `manifest.json` + `streams/` + `annotations/` + `recording_metadata.json`
- SDK 层 `StreamDescriptor.channel_names` fail-fast 校验，拒绝 CSV-unsafe 名字
- `RecordingReader` 扩展 4 个范围方法 + 4 个 manifest 属性；新增 `RecordingStore` 用于跨录制扫描
- 视频导出（MP4 / PNG ZIP）配套 `<stream>.frame_timestamps.csv` sidecar
- viridis colormap 硬编码 LUT，不引入 matplotlib / colorcet
- 全局 min-max 归一化采用 lazy + cache
- widgets UI 通过导出对话框选择录制、stream、格式、标注、元数据和输出目录
- 删除遗留导出注册表和导出格式下拉，UI 由 `ExportRequest` 驱动

不属于 `0.3.2` 范围：

- `manifest.json` 的 `schema_version` / `checksum` / `lineage` 字段
- 多时间段切片
- 并行导出
- 导出任务历史持久化（重启即清空）
- UI 4 模式左导航、历史导出列表和打开输出文件夹按钮
- raw 副本和 zip 打包 UI 选项
- 跨录制单流导出的专门 UI 入口
- 用 `ExportEngine` 替换当前 replay backend 导出服务

## 0.3.x

状态：进行中。

目标：在 `0.3.1` 修复关键稳定性问题之后，继续小步改善 replay/export、experiment/sidebar 和官方插件安装链路。

候选内容：

- replay / export 的 bug fix 和小体验改进
- recording catalog 的查询和筛选体验
- session / experiment 列表、详情和 recording 归档（标签字段已落盘到 recording.json，列表 UI 待补）
- marker / segment 的展示和编辑
- ~~批量导出和 export 参数配置~~ — 已在 0.3.2 导出重构落地
- `modlink-plugin` CLI 的状态、来源、升级提示和错误信息
- 外部插件开发文档和 skill 使用示例
- 面向 Claude Code / Codex 的独立插件项目示例
- Qt 6.11 popup 透明边界问题的后续验证，但不把迁移 PySide6 或重写 UI 作为默认方向
- 启动期间 MainWindow 构造的进一步异步化或预热
- ~~recording manifest enrichment（录制停止时落盘元数据 + 列表 tooltip）~~ — 已在 0.3.2 实现

仍然保持克制：

- AI 只辅助填写、建议和整理，不直接控制硬件关键动作
- catalog 先服务当前 widgets UI，不抽象成通用数据库层
- export 扩展先通过内建格式推进，不引入插件式 exporter 体系
- session / experiment 先做最小持久化和 UI 流程，不提前设计复杂研究数据平台
- 不恢复 npm scaffold
- 不恢复自研 Python plugin AI agent

## 0.4.0

状态：计划中。

目标：把已安装插件变成产品内可见、可控制的状态。第一版不做完整插件管理器，而是先提供最小 UI：查看已发现插件，并决定某个插件是否在 Studio UI 中展示。

核心范围：

- 新增插件状态 UI，优先放在 Settings 或 Devices 相关入口中
- 展示当前环境中已发现的 `modlink.drivers` entry point
- 展示插件名称、driver id、来源包、版本和当前显示状态
- 支持显示 / 隐藏已安装插件
- 隐藏只影响 Studio UI 是否展示该插件，不影响 runtime driver discovery 和 entry point 发现
- 对需要重启应用或重启 runtime 才能生效的操作给出明确提示
- 安装、更新和卸载仍主要通过 `modlink-plugin` CLI 完成
- CLI 和 UI 共享同一份本地显示状态，不维护两套配置

安全边界：

- UI 不执行插件作者提供的任意命令
- UI 不从任意第三方源下载安装插件
- 不自动静默隐藏新插件
- 插件来源、版本和显示状态必须可见
- 第一版不做插件沙箱，不承诺隔离恶意插件代码

不进入 `0.4.0`：

- 完整插件市场
- 完整安装 / 更新 / 卸载 UI
- 付费插件、账号系统或远端权限体系
- 插件签名和信任链
- 插件自定义 UI 扩展点
- AI 自动生成并安装插件
- 恢复 npm scaffold 或 Python plugin AI agent

## 0.4.x

状态：后续扩展。

目标：在插件显示 / 隐藏 UI 稳定后，继续扩展生态和数据交换能力。

候选方向：

- 第三方插件来源的可见性和手动添加流程
- 官方插件的安装 / 更新 / 卸载 UI
- 插件兼容性矩阵和升级提示
- BIDS / NWB / HDF5 等更正式的数据导出
- replay API 服务化
- Web replay 或轻量 Web viewer
- 更完整的发布自动化和兼容性矩阵

这些方向需要在 `0.4.0` 的插件管理基础稳定后再推进。

## 长期技术债务

- 从 SDK 开始引入类型检查
- 提升 UI 测试覆盖，尤其是 replay/export、settings 和插件管理页面
- 梳理 Windows 文件系统相关测试的稳定性
- 减少重复的临时测试目录和构建产物污染
- 为正式发布补齐更清晰的 release checklist
- **长录制存储重构（>4h 录制）**：当前 `frames.csv` 单文件追加 + 每帧一个 `.npz` 的设计在长录制下会全面瓶颈——CSV 文件体积爆炸、单目录文件数过多导致文件系统性能下降、reader 全量加载内存吃紧、进程崩溃丢失整段元数据。需要重新设计分块存储（按时间窗或帧数 rollover 成 chunk 文件）、分段索引、流式读取。可参考 HDF5 / Zarr / TileDB 等科学数据存储的分块策略。0.3.x 不做，0.4.x / 0.5.x 视用户实际长录制需求再定。
