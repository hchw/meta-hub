# 从 VSeeFace 换到 VNyan：需要改什么

meta-hub 输出的是标准 **VMC Protocol（OSC/UDP）**，不绑定具体渲染器。VNyan 与
VSeeFace 的差别主要在**接收端设置、端口、以及谁拥有头部/表情控制权**，协议本身
不变。

## 1. 项目侧改动（已落地）

| 配置项 | VSeeFace 时 | VNyan 建议 | 说明 |
| --- | --- | --- | --- |
| `META_HUB_VMC_HOST` | `127.0.0.1` | 不变 | VNyan 与 meta-hub 同机 |
| `META_HUB_VMC_PORT` | `39539` | **本次环境为 `3334`** | 以 VNyan 接收器界面为准 |
| `META_HUB_VMC_RENDERER` | 未设置 | `vnyan` | 仅用于记录/排查，不影响线格式 |
| `META_HUB_VMC_BONES` | 默认开 | `1` | 先开着验证骨骼；若 VNyan 只吃表情则设 `0` |
| `META_HUB_VMC_BONE_APPLY` | 可选 | `0`（默认） | `/VMC/Ext/Bone/Apply` 不在 VMC 规范内，已改为默认不发 |
| `META_HUB_VMC_BLEND_PROFILE` | `vrm0` | **当前 avatar 为 VRM1，用 `vrm1`** | 发送 `aa/ih/ou/ee/oh/happy/angry/sad/relaxed/surprised/blink` 等 VRM1 预设名 |
| `META_HUB_VMC_ROOT` | 未设置 | 先 `0`；骨骼不动再试 `1` | 发 identity `/VMC/Ext/Root/Pos` |
| `META_HUB_VMC_MOUTH_GAIN` | 按需 | 先 `1.0`，按观感调 | VNyan 自身口型若未关会稀释/叠加 |

代码变化：

- `motion/bones.py`：`VmcBoneSender` / `MotionSender` 默认不再发送非标准的
  `/VMC/Ext/Bone/Apply`；需要兼容旧接收器时才用 `send_bone_apply=True`。
- 当前 avatar 为 VRM 1.0：`META_HUB_VMC_BLEND_PROFILE` 默认已改为 `vrm1`，
  走 VRM1 预设表情名。
- `MotionSender` 支持 `send_bones=False`，用于确认 VNyan 是否消费骨骼。
- `config.py` 增加 `vmc_renderer`、`vmc_bones`、`vmc_bone_apply`。
- 新增 `tools/vmc_probe.py`，可单独发一次头部动作/表情，不经过 agent。
- **表情名称不变**：继续发 VRM 0.x 预设名（`A/I/U/E/O`、`Blink`、`Joy`、
  `Angry`、`Sorrow`、`Fun`、`Neutral` 等）。VMC 规范要求发送端用 VRM0 名称，
  由 VRM1 接收端转换；VNyan 支持 VRM1，应自行转换。

## 2. VNyan 侧设置

1. **启用一个 VMC 接收器**
   - VNyan 支持 4 个 VMC receiver。在设置里启用其中一个，记下端口。
   - 把 `META_HUB_VMC_PORT` 设成同一个端口；必要时重启 meta-hub 进程。
   - 若接收器需要绑定模型/跟踪角色，确认它作用于当前主播 avatar。
2. **交出头部/颈部/上半身的所有权**
   - 关闭 VNyan 自身的头部追踪、相机/iPhone 追踪对 Head/Neck/Chest 的覆盖，
     或把跟踪源切到 VMC。否则骨骼动作会被混合稀释（设计 D9）。
   - 若 VNyan 有“Idle animation / Auto blink / Eye tracking / Breathing”之类
     自动层，关闭与本系统重叠的部分；否则会和我们的 idle 层叠加。
3. **关闭 VNyan 的自动口型/表情**
   - 关闭 audio-based lipsync、自动表情、自动眨眼，避免与 A2F 的 `A/I/U/E/O`、
     `Blink` 抢控制权。
   - 如需要，用 VNyan 的 Blendshape Filter 把本系统驱动的表情名排除在其它
     跟踪源之外。
4. **模型**
   - VRM 0.x / VRM 1.0 / VSFAvatar 均可。VRM 1.0 请确认预设表情映射存在；
     若模型缺少 `happy/sad/...` 或 ARKit 自定义表情，先在 Unity/VRM 侧补齐。
5. **输出到 OBS**
   - VNyan 支持 Spout 输出，OBS 继续用 Spout2 Capture；只是源名称从
     VSeeFace 变成 VNyan。若不用 Spout，则改为窗口/游戏捕获。
6. **音频**
   - 不要让 VNyan 把 TTS 播放的声音再当成麦克风输入做口型，否则会双重驱动。

## 3. 最小验证步骤

先绕过 agent，只验证渲染器：

```bash
# 1) 头部骨骼：观察是否点头
python tools/vmc_probe.py --port <VNyan端口> --bone nod --seconds 2

# 2) 表情：观察嘴型/表情是否变化
python tools/vmc_probe.py --port <VNyan端口> --blend A --seconds 2

# 3) 骨骼 + 表情同时
python tools/vmc_probe.py --port <VNyan端口> --bone nod --blend Joy --seconds 3
```

判断：

- **头动、表情/口型完全不动**：先看 VNyan 的 VMC 分层设置里
  `trackBlendshapes` 是否为 `0`。为 `0` 时该层只接收骨骼、**完全忽略
  `/VMC/Ext/Blend/Val`**——本次实测就是这种情况：
  `VMCLayers[1]` 端口 `3334`，`trackHead/trackNeck/trackSpine = 1`，
  但 `trackBlendshapes = 0`。把该层 Track Blendshapes 调到 `1.0` 后重发。
- **表情动、头不动**：VNyan 接收器没把 Bone/Pos 应用到 avatar（或头部追踪
  覆盖）。先关头部追踪；仍不动则 `META_HUB_VMC_BONES=0`，改用 VNyan 节点图/
  自定义 OSC 驱动头部，或使用 VMCReceiverManager 自定义对象。
- **头动、表情不动**：检查 VNyan 口型/表情自动层、Blendshape Filter、模型预设名。
- **都不动**：端口/接收器未启用，或发到了错误的 receiver；用 `--port` 逐个试。
- **方向相反/幅度小**：VNyan 的坐标系或 rest pose 不同；先在探针里确认方向，
  再决定是否加每骨骼符号/增益映射。

## 4. 本次实测记录（VNyan / VRM1 / 端口 3334）

- **骨骼**：Head/Neck/Chest 的 `/VMC/Ext/Bone/Pos` 可直接驱动 avatar 点头、
  摇头、歪头；扩展到 Hips/Spine/UpperChest、双臂（Shoulder/UpperArm/
  LowerArm/Hand）和双腿（UpperLeg/LowerLeg/Foot）后，可做挥手、举手、
  鞠躬、鼓掌和跳舞。**不需要** `/VMC/Ext/Root/Pos`，也**不需要**非标准的
  `/VMC/Ext/Bone/Apply`。
- **表情**：最初完全不动，根因是 VNyan 的 `VMCLayers[1]`（端口 3334）
  `trackBlendshapes = 0`。在 VNyan 界面把 `Blendshape Tracking` 从
  `Don't track` 改为跟踪，或把配置改成 `1.0` 并重启 VNyan 后，
  `aa`、`happy`、`blink` 以及 VRM0 的 `A`、`Joy`、`Blink` 均可呈现。
- **配置落地**：`tools/vnyan_enable_blendshapes.py` 可在 VNyan 关闭时备份并
  修改该字段；修改后必须重启 VNyan。
- **口型归属**：VNyan 当前 `LipsyncInput = microphone`，接 A2F 口型时应关闭
  或把 Gain 调 0，否则会和 VMC blendshape 抢嘴型。

## 5. 还没做/需要实测的

- VNyan 原生 VMC 接收器对 **Bone/Pos 驱动 avatar 头部** 的支持程度：本次
  实测端口 `3334` 的 VMC 层可驱动 Head/Neck/Spine，骨骼链路正常。
- `trackBlendshapes` 必须显式开启；默认层是关闭的，会表现为“只有头动、
  表情不动”。
- VNyan 的 idle/自动眨眼与本系统 idle 层的优先级。
- 是否需要发送 `/VMC/Ext/Root/Pos` 才能让骨骼正确落到 avatar 根节点
  （当前实现未发送；VSeeFace 不需要）。
- 任务 8.x 的 30 分钟连续运行验收需在 VNyan 上重新做一遍。
- 实时循环使用 `meta-hub live`，默认复用当前 Pi agent 的模型，详见
  `docs/live-run.md`。
