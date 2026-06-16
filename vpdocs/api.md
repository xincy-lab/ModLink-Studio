# API 快速索引

这个页面主要作为 API 入口和对象速查表。

如果目标是接前端、联调 FastAPI 宿主或直接消费 HTTP / SSE / WebSocket 协议，请先看 [服务端 API 手册](/server-api)。

如果目标是安装和运行宿主应用，先看 [安装与发布](/install)；如果目标是开发 driver，先看 [SDK 开发者指南](/sdk)。

当前 API 说明以 `0.3.2rc2` 主线为准：

- `modlink_sdk` / `modlink_core` 已经是纯 Python runtime
- SDK / driver API 仍处于早期阶段，`0.3.2rc2` 不保证兼容 `0.2.x` driver 实现
- 当前桌面 UI 包以 `modlink_ui` 为准
- 插件管理 CLI 当前随 `modlink_studio` 一起分发

## Web API 入口

- 前端接入和服务端联调：看 [服务端 API 手册](/server-api)

## 完整 API 参考

从源码 docstring 自动生成的 API 文档入口如下：

- <a href="/pdoc/index.html" target="_self">打开 pdoc 总览</a>

当前主要包的入口如下：

- <a href="/pdoc/modlink_sdk.html" target="_self">modlink_sdk</a>
- <a href="/pdoc/modlink_core.html" target="_self">modlink_core</a>
- <a href="/pdoc/modlink_ui.html" target="_self">modlink_ui</a>
- <a href="/pdoc/modlink_studio.html" target="_self">modlink_studio</a>

## 先建立一条最小接入链路

从 SDK 视角看，一个 driver 的最小工作链路通常是：

1. 宿主创建一个 `Driver` 或 `LoopDriver` 实例
2. 宿主调用 `bind(context)`，注入 `DriverContext`
3. 宿主调用 `descriptors()`，读取这个 driver 会暴露哪些 `StreamDescriptor`
4. 宿主调用 `search()`，拿到一组 `SearchResult`
5. 宿主把选中的 `SearchResult` 传回 `connect_device()`
6. driver 开始流并提供实时数据后，通过 `emit_frame()` 发出 `FrameEnvelope`
7. 每个 `FrameEnvelope` 都必须能够对应到前面声明过的某个 `StreamDescriptor`

如果这条链路里有一环没有定义清楚，宿主、录制和 UI 就很难稳定工作。更需要先定清楚的不是“页面长什么样”，而是：

- 这个 driver 有哪些 stream
- 每个 stream 的 `payload_type` 是什么
- 每次发出的 `FrameEnvelope.data` shape 应该怎么解释

## 最常看的对象

### `Driver`

`Driver` 是所有 driver 的根基类，也是最保守、最通用的起点。它定义的是宿主能够理解的统一生命周期，而不是某种具体设备协议。

最核心的方法包括：

- `descriptors()`
- `search()`
- `connect_device()` / `disconnect_device()`
- `start_streaming()` / `stop_streaming()`
- `bind(context)`
- `emit_frame()`

如果暂时无法判断设备是不是标准轮询模型，默认回到 `Driver`。它的抽象更直接，也更不容易把设备逻辑硬套进不合适的轮询结构。

### `LoopDriver`

`LoopDriver` 建立在 `Driver` 之上，适合轮询型设备。它已经帮你封装了：

- 基于 runtime 的周期调度
- `start_streaming()` / `stop_streaming()` 的默认实现
- `on_loop_started()` / `on_loop_stopped()` 这两个可选钩子

通常只需要补齐：

- `descriptors()`
- `search()`
- `connect_device()` / `disconnect_device()`
- `loop()`

### `SearchResult`

`SearchResult` 是 `search()` 返回的候选设备对象。宿主只做两件事：

- 用 `title` / `subtitle` 展示给用户
- 在用户选中后，把整个对象回传给 `connect_device()`

宿主不会解析 `extra`。端口号、地址、序列号和传输参数等连接信息都可以放在这里，由 driver 自己消费。

### `StreamDescriptor`

`StreamDescriptor` 描述的是“这个 driver 会发出什么流”，它是静态契约，不是实时数据。

最关键的字段有：

- `device_id`
- `stream_key`
- `payload_type`
- `nominal_sample_rate_hz`
- `chunk_size`
- `channel_names`
- `display_name`
- `metadata`

其中 `payload_type` 当前只能从 `signal`、`raster`、`field`、`video` 中选择；UI 和录制链路会根据它解释 `FrameEnvelope.data`。

### `FrameEnvelope`

`FrameEnvelope` 是运行时真正发出的数据块。前面的 `StreamDescriptor` 负责“声明”，`FrameEnvelope` 负责“兑现”这个声明。

每次发帧时，最关键的是：

- `stream_id`
- `timestamp_ns`
- `data`
- `seq`
- `extra`

最重要的三条约束是：

1. `stream_id` 必须能对应到某个 `StreamDescriptor`
2. `data.shape` 必须和该流的约定一致
3. `timestamp_ns` 应该有真实时间语义

## 继续阅读

- 想接设备：看 [SDK](/sdk)
- 想理解运行时：看 [Core](/core)
- 想做展示层：看 [UI](/ui)
- 想理解宿主入口：看 [App](/app)
