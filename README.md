# ModLink Studio

面向设备接入、多模态采集与展示的桌面宿主项目。

ModLink Studio 的目标不是为每一种设备单独写一个上位机，而是把设备搜索、连接、流描述、实时预览、采集控制和录制保存统一到同一套运行时里。设备接入者主要实现 driver 和 `StreamDescriptor`；宿主、录制链路和大部分展示逻辑复用平台层能力。

当前仓库主线是 `0.3.2`：

- `modlink_sdk` / `modlink_core` 已切成纯 Python runtime
- SDK / driver API 仍处于早期阶段，`0.3.2` 不保证兼容 `0.2.x` driver 实现
- UI 仍处于适配期，但 backend 已经从 Qt 运行时语义中拆开，`0.4.0` 预计会继续收紧 SDK 与插件管理边界
- `0.3.2` 在 `0.3.1` 稳定性修订基础上补齐 replay seek 与录制导出体验

当前版本变更摘要见根目录 [CHANGELOG.md](CHANGELOG.md)，后续版本规划见 [ROADMAP.md](ROADMAP.md)。

![ModLink Studio screenshot](assets/ui-demo.png)

<details>
  <summary>查看更多界面截图</summary>

  <p>
    <img src="assets/ui-demo2.png" alt="ModLink Studio screenshot 2" />
  </p>
  <p>
    <img src="assets/ui-demo3.png" alt="ModLink Studio screenshot 3" />
  </p>
</details>

## Release Status

`0.3.2` 已正式发布：

- 当前仓库版本已切到 `0.3.2`
- 正式公开发布渠道以 **PyPI** 为准
- `TestPyPI` 只用于发布链路演练，不作为日常安装源

## Install

`0.3.2` 可从 PyPI 安装：

```bash
python -m pip install modlink-studio==0.3.2
```

当前安装完成后可用的宿主入口有：

```bash
modlink-studio
```

安装插件不再通过 PyPI extras。主包安装完成后，可使用独立的插件管理命令按需安装插件。

当前第一阶段，这个命令先覆盖官方驱动插件；后续会逐步扩成更通用的插件管理入口，而不仅仅是官方驱动安装器：

```bash
modlink-plugin list
```

```bash
modlink-plugin install host-camera
```

```bash
modlink-plugin list --installed
```

```bash
modlink-plugin status
```

```bash
modlink-plugin uninstall host-camera
```

更完整的安装说明、升级说明和源码运行方式见 [vpdocs/install.md](vpdocs/install.md)。

## Plugin Management

`0.3.2` 当前仍沿用以下官方驱动安装入口：

- Host Camera
- Host Microphone
- OpenBCI Ganglion
- Palm Sensor

这些驱动现在由独立仓库 [`ModLink-Studio-Plugins`](https://github.com/modlink-studio/ModLink-Studio-Plugins) 维护；安装路径是：

- 先安装 `modlink-studio`
- 再使用 `modlink-plugin install <plugin_id>` 从插件仓库 Pages 索引解析版本，并从插件仓库 GitHub Release 安装对应插件 wheel

当前这个命令仍以官方驱动为中心；后续版本会把它继续扩展成更完整的插件管理工具，例如统一查看插件状态、已安装第三方插件、安装来源和可升级项。

## Driver Development

`0.3.2` 继续以主宿主包 `modlink-studio` 作为公开安装入口。外部 driver 插件通常应该在自己的独立项目里开发，并把 `modlink-studio` 作为依赖；插件代码仍然从 `modlink_sdk` import SDK 类型，因为这个模块随 `modlink-studio` 分发。

典型外部插件项目安装方式是：

```bash
python -m pip install -e .
```

安装到与宿主相同的环境后，`modlink.drivers` entry point 会被宿主发现。

如果你希望让 Claude Code、Codex 等 coding agent 在外部插件项目里直接写 driver，可以使用 `tools/modlink-plugin-author/SKILL.md` 作为可分发 skill。它描述的是外部插件项目的真实工作流：依赖 `modlink-studio`、暴露 `modlink.drivers` entry point、`pip install -e .` 验证。

推荐使用方式是在外部插件项目目录启动 coding agent，把这个 `SKILL.md` 作为 skill 或上下文加载，然后直接描述设备和数据流需求。生成后仍应在插件项目内运行 `python -m pip install -e .` 和测试命令验证。

推荐的外部插件项目通常包括：

- `pyproject.toml`
- `README.md`
- `LICENSE`
- `.gitignore`
- `<plugin_name>/driver.py`
- `<plugin_name>/factory.py`
- `<plugin_name>/__init__.py`
- `tests/test_smoke.py`

## Repository Layout

```text
modlink-studio/
├─ apps/
│  ├─ modlink_studio/
│  └─ modlink_server/
├─ packages/
│  ├─ modlink_sdk/
│  ├─ modlink_core/
│  └─ modlink_ui/
├─ tools/
│  └─ modlink-plugin-author/
└─ vpdocs/
```

- `apps/modlink_studio/`: 主桌面宿主入口
- `apps/modlink_studio/modlink_studio/plugin/`: 跟随主宿主一起发布的插件管理 CLI
- `apps/modlink_server/`: FastAPI 服务宿主入口
- `packages/modlink_sdk/`: 当前仓库内的最小 SDK 契约
- `packages/modlink_core/`: 纯 Python runtime、流总线和采集基础设施
- `packages/modlink_ui/`: 当前唯一的 Qt Widgets UI 包，内部同时承载 Qt bridge
- `tools/modlink-plugin-author/`: 给 Claude Code / Codex 使用的外部插件开发 skill
- `vpdocs/`: VitePress 文档站源码

## Contributor Setup

仓库内开发使用 `uv`：

```bash
uv sync
uv run modlink-studio
```

如果要带控制台和更高日志级别启动桌面宿主：

```bash
uv run modlink-studio-debug
```

如果要联调官方驱动源码，请切到独立仓库 `ModLink-Studio-Plugins` 进行构建与发布验证；主仓库不再承载官方驱动源码目录。

根仓库执行 `uv sync --dev` 后，`apps/modlink_server/tests` 也会被当前工作区虚拟环境直接覆盖；不需要再单独创建 server 专用环境。

### Code Style And Pre-Commit

当前仓库主要使用 Python 工具链治理代码质量：

- Python 代码统一使用 `ruff` 负责 lint、import sorting 和 format，配置位于根 [pyproject.toml](pyproject.toml)
- 提交前检查使用根 [`.pre-commit-config.yaml`](.pre-commit-config.yaml)
- 编辑器基础约束写在根 [`.editorconfig`](.editorconfig)
- Git 行尾策略写在根 [`.gitattributes`](.gitattributes)

首次使用建议安装 pre-commit：

```bash
uv run pre-commit install
```

手动运行整套提交前检查：

```bash
uv run pre-commit run --all-files
```

只跑 Python 这一层的检查与格式化：

```bash
uv run ruff check . --fix
uv run ruff format .
```

## Docs And License

项目文档使用 VitePress，源码位于 `vpdocs/`，站点发布到 `https://modlink-studio.github.io`。

本地预览：

```bash
npm ci
npm run docs:vp:dev
```

构建文档：

```bash
npm ci
npm run docs:pdoc:build
npm run docs:vp:build
```

当前仓库整体按 `GPL-3.0-or-later` 路线发布，详细条款见根目录 [LICENSE](LICENSE)。
