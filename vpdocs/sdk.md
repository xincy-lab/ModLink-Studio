# SDK 开发者指南

这一页记录的是把设备接入 `ModLink Studio` 时最常用的约定。

第一版的核心原则只有两条：

- 外部 driver 项目依赖公开主包 `modlink-studio`，代码从随主包分发的 `modlink_sdk` 导入 SDK 契约
- 安装后通过 `modlink.drivers` entry point 被宿主发现

当前文档以 `0.3.2rc2` 主线为准。SDK / driver API 仍处于早期阶段，`0.3.2rc2` 不保证兼容 `0.2.x` driver 实现；外部插件建议明确依赖兼容的 `modlink-studio` 版本。`0.4.0` 预计会继续收紧 SDK 与插件管理边界。

需要特别说明的是：公开 PyPI 发布面当前收口为 `modlink-studio` 一个主包；`modlink_sdk` 这一层契约由主包携带，不要求外部插件项目单独依赖一个公开的 `modlink-sdk` 包。

开发前，请先完成宿主环境安装，见 [安装与发布](/install)。

## 快速定位

- [先选哪一个基类](#先选哪一个基类)
- [用 coding agent 起步](#用-coding-agent-起步)
- [最小接入流程](#最小接入流程)
- [DriverContext 和发帧出口](#drivercontext-和发帧出口)
- [三个核心数据模型](#三个核心数据模型)
- [driver 生命周期](#driver-生命周期)
- [插件项目怎么组织](#插件项目怎么组织)
- [零参数工厂](#零参数工厂)
- [命名建议](#命名建议)

## 先选哪一个基类

### `Driver`

`Driver` 是所有 driver 的根基类。宿主真正理解的是这套基类契约，而不是某个具体设备自己的接入方式。

一个 `Driver` 实例通常代表“宿主管理下的一个设备端点”，它需要对外提供：

- `descriptors()`：这个 driver 会发哪些流
- `search()`：当前能找到哪些候选设备
- `connect_device()` / `disconnect_device()`：连接生命周期
- `start_streaming()` / `stop_streaming()`：数据流生命周期
- `bind(context)`：接入宿主注入的 `DriverContext`
- `emit_frame()`：向宿主发出 `FrameEnvelope`
- `emit_connection_lost()` / `report_error()` / `set_status()`：回传运行时事件

适合这类设备：

- callback 型 SDK
- 第三方库回调驱动的数据源
- 很难用固定 `loop()` 表达清楚的设备

如果你还不确定设备是不是标准轮询模式，优先先用 `Driver`。它是最直接的抽象，也更适合在早期先把设备协议跑通。

### `LoopDriver`

`LoopDriver` 的基类也是 `Driver`。它不是另一套平行体系，而是在 `Driver` 之上，为轮询型设备提供的一个已经封装好的 helper。

它主要适用于这类场景：driver 不需要等待外部 callback，而是要在自己的线程里反复执行一段短操作，例如“读串口缓冲区”“检查 SDK 是否有新样本”“取一批可用数据并发出去”。

`LoopDriver` 默认已经帮你接好了：

- 基于 driver 独立线程的周期调度
- `start_streaming()` / `stop_streaming()` 的默认实现
- `on_loop_started()` / `on_loop_stopped()` 这两个可选钩子

通常你只需要补：

- `descriptors()`
- `search()`
- `connect_device()` / `disconnect_device()`
- `loop()`
- 必要时调整 `loop_interval_ms`

适合这类设备：

- 串口轮询
- BrainFlow 风格设备
- 一次短循环就能表达的数据获取逻辑

不适合这类设备：

- callback 型 SDK
- 单次读取会长时间阻塞的设备
- 采集逻辑本身依赖复杂异步状态机的设备

如果判断不清楚，回到 `Driver`。`LoopDriver` 的目的在于减少轮询样板代码，而不是让所有 driver 都采用轮询模型。

## 用 coding agent 起步

如果你希望在外部插件项目里直接让 Claude Code、Codex 等 coding agent 编写 driver，可以使用仓库里的 `tools/modlink-plugin-author/SKILL.md` 作为可分发 skill。这个 skill 面向独立插件项目，而不是 ModLink-Studio 主仓库开发。

推荐使用方式是在外部插件项目目录启动 coding agent，把这个 `SKILL.md` 作为 skill 或上下文加载，然后直接描述设备、连接方式、数据流类型和采样率。生成后仍应在插件项目内运行 `python -m pip install -e .` 和测试命令验证。

推荐让 coding agent 在一个新建的独立 driver 项目里生成：

- 基础包结构
- `pyproject.toml`
- `README.md`
- `LICENSE`
- `.gitignore`
- `<plugin_name>/driver.py`
- `<plugin_name>/factory.py`
- `modlink.drivers` entry point
- `tests/test_smoke.py`

skill 只负责告诉 coding agent 如何把项目骨架和 SDK 契约接好，不会替代真实设备协议确认。生成项目后，通常还需要你继续补完：

- `search()`
- `connect_device()` / `disconnect_device()`
- 真实数据流提供与 `FrameEnvelope` 发射逻辑

## 最小接入流程

1. 定义一个 driver 类
2. 实现 `device_id`
3. 实现 `descriptors()`
4. 实现 `search()`
5. 实现连接和数据提供逻辑
6. 通过 `emit_frame()` 发出 `FrameEnvelope`

优先先定住两件事：

- `StreamDescriptor`
- `FrameEnvelope.data` 的 shape

## DriverContext 和发帧出口

`DriverContext` 不是需要你选择的 driver 基类，而是宿主在 `bind(context)` 阶段注入给 driver 的运行时出口。driver 与宿主的正式交互通道是这组 callback，而不是 Qt signal。

最常用的方法有：

- `emit_frame(frame)`：把 `FrameEnvelope` 交给宿主
- `emit_connection_lost(detail)`：通知连接丢失
- `report_error(message)`：上报非致命运行时错误
- `set_status(status, detail=None)`：发布 driver 状态

通常推荐直接使用 `Driver` 基类已经提供的同名 helper：`self.emit_frame(...)`、`self.emit_connection_lost(...)`、`self.report_error(...)`、`self.set_status(...)`。只有在解释宿主和 driver 的绑定关系时，才需要直接理解 `DriverContext`。

## 三个核心数据模型

### `SearchResult`

`SearchResult` 是 `search()` 的返回值。宿主拿它做两件事：

- 用 `title` / `subtitle` 展示给用户
- 在用户选择后，把整个对象回传给 `connect_device()`

最常用字段：

- `title`：列表主标题
- `subtitle`：列表副标题
- `extra`：driver 自己保存的连接参数

可选补充字段：

- `device_id`：driver 提供的稳定设备标识

宿主不会解析 `extra`。端口号、地址、序列号、驱动私有参数等信息，都可以放在这里。`device_id` 也不是宿主当前会消费的字段；它不是必填项，只有在 driver 希望额外提供一个规范化设备标识时才需要填写。

### `StreamDescriptor`

`StreamDescriptor` 描述“这个 driver 会发哪些流”，它是静态契约，不是实时数据。

宿主会在连接前就调用 `descriptors()`，因此这里返回的信息应该在 driver 生命周期内保持稳定。

先明确一件事：`stream_id` 不是手写字段，而是由 `device_id + stream_key` 自动派生出来的。
因此真正需要你决定的是下面这些字段。

#### 强约束字段

这些字段不只是补充描述，而是会直接影响宿主如何路由、预览和录制数据。

- `device_id`
  这是这个流所属的设备实例标识，必须满足 `name.XX` 形式，例如 `host_camera.01`。
  它会直接参与 `stream_id` 的生成。如果这个值变了，系统会把它视为另一个流。
- `stream_key`
  这是设备内唯一的流键，例如 `eeg`、`audio`、`video`、`accel`。
  它同样会参与 `stream_id` 的生成，因此应该使用稳定、可复用的名字，而不是临时描述。
- `payload_type`
  这个字段不能任意写，当前只能从这四个值里选：
  - `signal`
  - `raster`
  - `field`
  - `video`
  它决定了宿主选用哪一类预览视图、哪一类录制 writer，以及 `FrameEnvelope.data` 应该满足什么维度约定：
  - `signal`：`data.shape == [channel_count, chunk_size]`
  - `raster`：`data.shape == [channel_count, chunk_size, line_length]`
  - `field`：`data.shape == [channel_count, chunk_size, height, width]`
  - `video`：`data.shape == [channel_count, chunk_size, height, width]`
  如果值超出这四个范围，当前预览和录制链路都会直接报错。
- `nominal_sample_rate_hz`
  这是正数，表示该流的名义采样率。
  它会影响预览中的时间轴、部分默认设置和录制时的名义采样周期计算。当前 Core 会要求它是正数，非正值会直接报错。
- `chunk_size`
  这是正整数，表示每个 `FrameEnvelope` 通常打包多少个样本或多少帧。
  它不是提示性字段。录制链路会校验运行时收到的实际 `chunk_size` 是否和 descriptor 一致；如果 descriptor 写的是 32，而实际 frame 发的是 64，当前 writer 会直接报错。
  从实践上看，采样率越高、发帧越频繁的设备，通常越适合把 `chunk_size` 设得更高一些，以减少过于频繁的 frame 派发和处理开销。

#### 描述性字段

这些字段更偏向“告诉宿主如何展示和解释这个流”，不是路由主键，但仍然建议保持稳定。

- `channel_names`
  这是通道标签列表，本质上可以自由命名，例如 `("Fp1", "Fp2")`、`("x", "y", "z")`、`("red", "green", "blue")`。
  对 `signal` 类型尤其重要：如果数量和实际 `channel_count` 一致，预览图和录制文件会使用这些名字；如果数量不一致，系统会退回到自动生成的通道名。
- `display_name`
  这是面向用户的可读名称，例如 `Ganglion EEG`、`Host Microphone Waveform`。
  它主要影响界面显示；如果不提供，UI 通常会退回到 `stream_id`。

#### `metadata` 应该怎么用

`metadata` 是补充说明信息，适合放那些“有助于解释流，但又不适合作为主字段”的内容。  
它应该保持 JSON 友好，并且在 driver 生命周期内尽量稳定。

当前最常见、最推荐使用的键是：

- `unit`
  表示工程单位，例如 `uV`、`degC`、`kPa`、`m/s^2`、`a.u.`。
  它并不和 `signal` 绑定。只要这个流本身有明确量纲，就可以填写 `unit`；例如信号流、场图流和栅格流都可以使用。
  当前系统里，`unit` 主要有两个作用：
  - 会进入录制时保存下来的 descriptor 元数据
  - 会显示在预览卡片摘要里
  目前它不会自动驱动数值缩放、坐标轴换算或滤波参数，因此它更像“明确数据语义”的说明字段，而不是控制行为的配置字段。

其他 payload 相关信息也可以放进 `metadata`，例如：

- `length`
- `height`
- `width`

但要注意：当前运行时并不会依赖这些键来决定预览或录制 shape；系统主要还是根据 `payload_type` 和实际 `FrameEnvelope.data.shape` 工作。  
因此这些键如果提供，应该作为补充说明，并且与真实数据 shape 保持一致，而不是把它们当成唯一真值来源。

### `FrameEnvelope`

`FrameEnvelope` 是运行时真正发出的数据块。它和 `StreamDescriptor` 的关系必须是一一可解释的：宿主先通过 `StreamDescriptor` 知道“这个流是什么”，再通过 `FrameEnvelope` 收到“这个流的实时数据”。

最重要字段：

- `stream_id`：属于哪个流
- `timestamp_ns`：时间戳
- `data`：数据本体
- `seq`：可选顺序号

实际接入时最重要的约束有三条：

- `device_id + stream_key` 会派生出 `stream_id`，它必须能对应到某个 `StreamDescriptor`
- `data` 的 shape 必须和该流的约定一致
- `timestamp_ns` 需要有真实时间语义，不能只是随手填值

## driver 生命周期

宿主对 driver 的典型调用顺序：

1. 创建 driver
2. 读取 `device_id` / `display_name`
3. 读取 `descriptors()`
4. 宿主调用 `bind(context)`
5. 启动 driver worker thread
6. 调 `on_runtime_started()`
7. 调 `search()`
8. 调 `connect_device()`
9. 调 `start_streaming()`
10. 后续调 `stop_streaming()` / `disconnect_device()` / `shutdown()`

## 插件项目怎么组织

推荐一个 driver 项目一个目录：

```text
my_driver/
├─ pyproject.toml
└─ my_driver/
   ├─ __init__.py
   ├─ factory.py
   └─ driver.py
```

最小 `pyproject.toml` 示例：

```toml
[project]
name = "my-driver"
version = "0.1.0"
dependencies = [
  "modlink-studio>=0.3.2rc2",
  "numpy>=2.3.3",
]

[project.entry-points."modlink.drivers"]
my-driver = "my_driver.factory:create_driver"
```

这里的边界很重要：

- driver 项目依赖公开主包 `modlink-studio`
- driver 代码仍然从 `modlink_sdk` 导入 SDK 类型
- 如无必要，不要依赖 `modlink-core`
- 宿主只关心 `modlink.drivers` 和 SDK 契约

`factory.py` 的职责也应该保持简单：它负责暴露给宿主加载的工厂函数，而不是在这里实现设备协议逻辑。

当前阶段更推荐在源码或本地联调环境中验证 driver：

安装方式：

```bash
python -m pip install -e .
```

安装到与宿主相同的环境后，启动宿主：

```bash
modlink-studio-debug
```

## 零参数工厂

每个 driver 包都应该通过 `modlink.drivers` entry point 暴露一个零参数工厂。

最常见的形式就是：

```python
from .driver import MyDriver


def create_driver() -> MyDriver:
    return MyDriver()
```

这里“零参数”不是风格建议，而是当前宿主的实际契约：

- 宿主启动时会扫描 `modlink.drivers`
- entry point 加载出来的对象必须是可调用的
- 宿主会直接以无参数形式调用它
- 返回值必须是一个 `Driver` 实例

因此当前推荐把 entry point 固定写成：

```toml
[project.entry-points."modlink.drivers"]
my-driver = "my_driver.factory:create_driver"
```

这个约束背后的原因很直接：宿主在发现插件时只知道“这里有一个 driver factory”，并不知道你的设备需要什么端口、地址、序列号或认证参数。  
这些运行时信息应该放到后续流程里处理：

- 设备候选在 `search()` 里发现
- 连接参数通过 `SearchResult.extra` 回传
- 真实连接在 `connect_device()` 里建立

因此不建议把这类运行时参数塞进 `Driver` 构造函数。  
构造函数更适合做的是：

- 初始化内部状态
- 创建还不依赖设备连接的对象
- 准备稳定的 descriptor 定义

而不适合在构造阶段就：

- 打开设备
- 启动数据流
- 依赖必须由用户选择后才能确定的连接参数

当前宿主还会继续校验工厂返回值：

- 返回对象必须是 `Driver`
- `driver.device_id` 不能为空

所以如果 entry point 不是零参数工厂，或者工厂没有返回一个合法 `Driver`，宿主会在启动加载阶段直接报错。

## 命名建议

### `device_id`

推荐格式：

```text
name.XX
```

例如：

- `my_driver.01`
- `host_camera.01`
- `openbci_ganglion.01`

### `stream_id`

当前约定由 `device_id + stream_key` 自动派生：

```text
{device_id}:{stream_key}
```

例如：

- `host_camera.01:video`
- `openbci_ganglion.01:eeg`

## 官方驱动命名与插件安装

当前仓库内维护的官方驱动使用下面这组 entry point：

- `host-camera`
- `host-microphone`
- `openbci-ganglion`

在 `0.3.2rc2` 当前阶段，这些 entry point 主要通过 `modlink-plugin install <plugin_id>` 安装进当前环境；后续会沿这条路径继续扩展到更通用的插件管理方式。
