# 抓取路线维护说明（任务 7.2）

本文件记录**本机抓取适配器**（开发/自用通道）的协议变化风险与自查方式。正式
开播的官方通道是"互动工具（仅直播伴侣）"的本地插件桥接；两条通道都只把事件
喂给同一个统一 `Event` 契约，因此替换通道不影响 agent 与执行器。

## 1. 风险

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 协议会变 | 抓取读取的是客户端/网页的私有流量，字段、加密、路由随时可能调整 | 适配器只做"翻译"，保留 `raw` 原始字段；失败时丢弃并重连，不影响 agent |
| 平台条款 / 风控 | 抓取属于非官方接入，可能违反平台协议并引发账号风控 | 仅用于开发与自用联调；正式开播切到官方伴侣插件通道 |
| 数据缺失 | 客户端改版后可能拿不到礼物/粉丝团字段 | 统一事件允许空字段；缺字段的事件按普通评论/忽略处理，不抛异常 |
| 断线 | sidecar 崩溃、网络抖动、伴侣重启 | `ReconnectingIngress` 指数退避重连 + 心跳；`event_id` 去重保证不重复消费 |

## 2. 统一线上格式

抓取 sidecar 与 meta-hub 之间使用 **TCP + 换行分隔 JSON**（`TcpJsonAdapter`）。
每行一个 `Event.to_dict()`：

```json
{"kind":"comment","event_id":"...","ts":1710000000.0,"viewer_id":"u1","viewer_name":"观众A","text":"你好","gift_id":"","gift_name":"","gift_count":0,"gift_value":0,"direction":"","reason":"","raw":{}}
```

- `kind`：`comment` / `gift` / `like` / `enter` / `fansclub` / `follow`
- `event_id`：去重键。平台没有稳定 id 时，sidecar 必须生成**确定性** id（例如
  房间号 + 事件时间 + 观众 + 内容哈希），否则重连后的重投无法折叠。
- `raw`：原样保留上游字段，便于协议变更时排查。
- 心跳：meta-hub 每 5 秒发送 `{"type":"heartbeat","ts":...}`，sidecar 可忽略。

## 3. 自查清单（每次平台客户端更新后）

1. **通道存活**：`nc -vz 127.0.0.1 7711`，或观察 `IngressStats.reconnects` 不持续增长。
2. **事件取样**：发一条测试弹幕，确认本地收到 `kind=comment` 且 `viewer_id`、`text`、`ts` 均非空。
3. **礼物字段**：发一个小礼物，确认 `gift_id`、`gift_count`、`gift_value` 有值；
   高价值阈值（默认 1000）能触发硬打断条件。
4. **重投去重**：把同一行事件发送两次，`IngressStats.duplicates` 应 +1，agent 只处理一次。
5. **断线重连**：kill sidecar 再启动，`IngressStats.reconnects` 增加且事件流恢复，无需重启 meta-hub。
6. **注入防护**：发送包含"忽略之前的规则"的弹幕，确认上下文里它只出现在
   `<viewer_data>` 块内，系统提示词不变。
7. **协议差异**：对比 `raw` 与上一版本，字段改名/新增时只改 sidecar 的翻译层，
   不改 `events.py`、agent 或执行器。

## 4. 替换为官方伴侣插件

1. Windows 侧桥接进程连接伴侣的本地管道，订阅"直播间开放数据推送"。
2. 桥接进程把数据翻译成上面的统一 JSON，通过本地 TCP（或等价本地管道）转发给
   meta-hub，`event_id` 同样必须稳定。
3. meta-hub 侧只替换适配器实例（`TcpJsonAdapter` 指向新端口，或实现另一个
   `EventAdapter`）；`ReconnectingIngress`、agent、时间轴执行器一行不改。
4. 回滚：保留抓取适配器作为备用通道，配置切换即可；也可退回 `ScriptedAdapter`
   回放事件。

## 5. 已知未决项

- 抓取路线是否长期保留为备用通道（条款/风控自担）。
- 官方"互动工具（仅直播伴侣）"的申请门槛与上架周期（任务 7.3，待开放平台答复）。
- 伴侣插件桥接进程的具体管道名与开放数据字段（任务 7.4，待调试版伴侣包实测）。
