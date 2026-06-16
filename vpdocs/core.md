# Core 模块架构

Core 层负责的是“driver 发出的流怎么进入系统、怎么路由、怎么录制、怎么被其他模块消费”。

如果需要概括 Core 层的定位，可以理解为：

- UI 和应用层依赖 Core 暴露出来的稳定流模型，而不是直接依赖设备协议

当前文档以 `0.3.2` 主线为准。`modlink_core` 已经是纯 Python runtime，不再依赖 `QThread`、Qt signal 或其他 Qt runtime 兼容层。

## Core 负责什么

当前 Core 主要负责这几件事：

1. 托管 driver worker thread
2. 调 driver 的生命周期方法
3. 接住 driver 通过 context 发出的 `FrameEnvelope`
4. 把 descriptor 注册到 `StreamBus`
5. 把实时流交给录制和其他消费者

## 建议优先了解的几个对象

### `DriverPortal`

`DriverPortal` 是系统其他部分接触 driver 的入口。

它负责：

- 转发 `search / connect / disconnect / start / stop`
- 维护 driver 的连接状态和 streaming 状态
- 接住来自 driver 的 frame 和 connection-lost 事件

### `DriverRuntime`

`DriverRuntime` 负责把 driver 放到独立线程上运行，并通过命令队列把方法调用串行投递到这条线程。

从 driver 侧看，这意味着：

- 生命周期方法仍然是同步方法
- 但不会直接堵住 UI 线程

### `StreamBus`

`StreamBus` 是系统内部的统一流入口。

它的角色是：

- 注册 `StreamDescriptor`
- 接收实时 `FrameEnvelope`
- 给录制和 UI 提供统一的订阅源

### `RecordingBackend`

`RecordingBackend` 负责录制任务。

它不需要知道设备怎么连接，只关心总线里已经存在的流以及如何把这些流写出去。

### `ModLinkEngine`

`ModLinkEngine` 是整个 Core 的组合根。

它负责：

- 创建 `StreamBus`
- 创建录制后端
- 安装 driver portal
- 把这些共享服务挂在一起

## 一个 frame 的流转路径

典型路径如下：

1. driver 通过 `DriverContext.emit_frame()` 或 `Driver.emit_frame()` 发出 `FrameEnvelope`
2. `DriverRuntime` 接到这条事件
3. `DriverPortal` 把它继续往上转
4. `StreamBus` 接收并分发
5. 录制后端和 UI 消费者分别订阅

对展示层来说，最重要的是最后两步，而不是设备底层怎么来的。

## 为什么 descriptor 要尽量稳定

当前 engine 在安装 driver 时就会先读取 `descriptors()` 并把它们注册到总线里。

这意味着：

- descriptor 最好不要依赖“先连上设备之后才能知道”的动态状态
- `stream_id`、`payload_type`、`chunk_size` 这些字段最好在 driver 生命周期内保持稳定

这不是因为系统不能做动态 descriptor，而是因为目前整条链路还没有把“连接后重新注册 descriptor”作为主流程。

## 对 driver 开发更直接相关的部分

如果关注点是编写 driver，建议优先了解的是：

- `emit_frame()` 最终会进入 `StreamBus`
- `StreamDescriptor` 会先被注册
- 生命周期方法在 worker thread 上同步执行

理解这些边界之后，通常不需要再了解过多的 Core 内部实现细节。

## 对展示开发更直接相关的部分

如果关注点是页面、图表或面板，更适合优先依赖的是这些约定：

- `stream_id`
- `payload_type`
- `data.shape`
- `channel_names`
- `unit`

也就是说，UI 更适合消费“已经稳定化的流模型”，而不是消费设备自己的底层概念。

当前还需要明确一件事：backend 已经纯 Python 化，但 Qt UI 仍需要单独的 bridge，把 runtime 事件安全转回 UI 主线程。这属于 UI 适配层工作，不再属于 Core 本身。

## 推荐继续阅读的页面

- 想接设备：看 [SDK](/sdk)
- 想做页面展示：看 [UI](/ui)
- 想知道应用入口怎么组装：看 [App](/app)
- 想直接跳源码 API：看 [API](/api)
