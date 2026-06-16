# App 组合根

App 层负责把已经存在的 SDK、Core、UI 和 bridge 装配成真正可启动的宿主程序。它的职责不是重新定义协议，而是把现有能力组合成最终入口。

在当前阶段，宿主入口实现上只保留两条：

- `modlink_studio`：主桌面宿主，使用 `modlink_ui`
- `modlink_server`：FastAPI 服务宿主，为后续 HTML / Web UI 准备

## 这页主要回答什么

1. 最终用户从哪里启动宿主
2. App 层启动时会创建哪些对象
3. 已安装的 driver 是怎么被发现的
4. App 层保留了哪些 fail-fast 边界

## 启动入口

正式安装方式见 [安装与发布](/install)。`0.3.2rc2` 的主桌面宿主入口是：

```bash
modlink-studio
```

调试入口保留为：

```bash
modlink-studio-debug
```

`modlink_server` 当前主要面向前端联调和宿主边界验证，而不是普通终端用户的默认入口。

这两个入口当前都由同一个 `modlink-studio` distribution 提供，而不是拆成多个公开 PyPI 包。

## App 层到底负责什么

以桌面宿主为例，App 层当前会做这些事：

1. 创建或复用 `QApplication`
2. 设置应用名、图标和主题
3. 初始化设置服务
4. 发现当前环境里的 driver factories
5. 创建 `ModLinkEngine`
6. 创建主窗口
7. 把 Qt 的 `aboutToQuit` 接到 runtime shutdown
8. 启动 Qt 事件循环

这层的核心特征是“装配”，而不是“定义新协议”。

## 一个启动流程大概长什么样

从当前实现看，宿主启动顺序大致是：

1. 创建应用对象
2. 初始化主题、图标和设置
3. 扫描 `modlink.drivers`
4. 用扫描到的 driver factories 创建 `ModLinkEngine`
5. 创建对应宿主窗口或 controller
6. 进入事件循环

这条顺序说明：

- driver 发现发生在应用启动阶段
- Core 运行时在窗口创建前就已经准备好
- UI 页面拿到的是已经组装好的 engine，而不是自己去拼 driver 或流总线

## 插件发现模型

宿主不会在运行时临时发现“未安装的插件”。当前模型是“先安装，再发现”：

- 插件通过 `modlink-plugin install ...` 安装到当前环境
- 外部 driver 在当前阶段主要通过源码环境和本地安装联调到同一个 Python 环境
- 宿主启动时扫描当前环境里的 `modlink.drivers`

一个外部 driver 的典型联调方式是：

```bash
python -m pip install -e ../my_driver
modlink-studio-debug
```

这意味着：

- App 层只负责发现已经安装好的 driver
- driver 的安装和版本管理发生在 Python 包环境层，而不是宿主界面层

## 为什么外部 driver 不依赖宿主应用

`modlink-studio` 是最终桌面宿主，不是 driver 的最小公共接口。

外部 driver 更合理的依赖边界是：

- SDK 契约当前仍在仓库内明确存在
- 只有确实需要运行时服务时，才额外依赖 `modlink-core`

这样可以让 driver 依赖最小稳定接口，而不是反向绑死在整个宿主应用上。

## App 层保留的 fail-fast 边界

App 层当前明确保留 fail-fast 策略：

- 损坏的 driver entry point 会在启动或加载阶段直接暴露错误
- 未知 payload 类型不会在 App 层被静默吞掉
- 明显的插件协议错误会尽早暴露，而不是拖到运行过程中再变成更难排查的问题

这里的判断很明确：driver 是系统核心组成，不是可有可无的附属插件。

## 仓库内联调

官方驱动源码已经迁移到独立仓库 `ModLink-Studio-Plugins`。当前主仓库的宿主应用只负责发现已经安装进环境的插件；如果需要联调官方驱动源码，请在插件仓库中完成构建、发布或本地安装，再回到当前宿主环境验证。

如果目的是理解 driver 契约，优先继续看 [SDK](/sdk)。如果目的是理解 runtime 如何托管 driver 和流，继续看 [Core](/core)。如果目的是联调 Web / HTML 前端，则直接看 [服务端 API 手册](/server-api)。
