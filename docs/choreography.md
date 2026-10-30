# LLM 编舞：`choreograph` 工具与动作运行时

LLM **不生成逐帧骨骼**。它只输出一个高层舞蹈程序，运行时按 BPM/节拍插值到
60fps，再通过 VMC 发给 VNyan。

## 工具调用示例

```json
{
  "name": "eight_count",
  "bpm": 120,
  "loop": true,
  "steps": [
    {"at": 0, "move": "bounce", "beats": 1, "intensity": 0.5},
    {"at": 1, "move": "step_touch", "beats": 2, "intensity": 0.6},
    {"at": 3, "move": "arm_wave", "beats": 2, "intensity": 0.7},
    {"at": 5, "move": "clap", "beats": 1, "intensity": 0.8},
    {"at": 6, "move": "step_touch", "beats": 1, "intensity": 0.6, "mirror": true},
    {"at": 7, "move": "bounce", "beats": 1, "intensity": 0.6}
  ]
}
```

`at` / `beats` 单位都是拍；`bpm` 默认 120。`steps` 最多 32 个，总长最多
128 拍。

## 关键姿势模式（升级后的动作库）

现在优先用 `poses`，而不是 `steps`。每个 key 是一个**全身关键姿势**：

```json
{
  "name": "kpop_16",
  "bpm": 120,
  "loop": true,
  "loop_transition": 0.5,
  "poses": [
    {"at": 0, "pose": "hip_left", "hold": 0.5, "ease": "smooth"},
    {"at": 2, "pose": "arms_up", "hold": 0.5, "ease": "smooth"},
    {"at": 4, "pose": "body_wave_low", "ease": "soft"},
    {"at": 6, "pose": "point_right", "hold": 0.5, "ease": "snap"},
    {"at": 8, "pose": "clap_close", "ease": "smooth"}
  ]
}
```

- `at` / `hold` / `loop_transition`：拍
- `ease`：`linear` / `smooth` / `snap` / `soft`
- `hold`：在该姿势上停住，不立即过渡
- `mirror`：左右镜像
- 循环时自动从最后一个姿势过渡回第一个姿势，过渡长度由
  `loop_transition` 控制

内置关键姿势：

`center` `hip_left` `hip_right` `arms_open` `arms_up` `left_arm_up`
`right_arm_up` `hands_on_hips` `point_left` `point_right` `clap_open`
`clap_close` `body_wave_low` `body_wave_high` `step_left` `step_right`
`kick_left` `kick_right` `lean_back` `bow` `crouch` `spin_mid`

这些姿势包含左右重心、手臂高度、胸部/髋部反向、头部朝向和腿部弯曲，
比原来的正弦动作更适合编排有停顿、有重音、左右不对称的舞。

## 可用动作（旧的循环动作模式）

| move | 内容 |
| --- | --- |
| `bounce` | 屈膝弹跳 |
| `step_touch` | 左右踏步/点地 |
| `hip_sway` | 胯部左右摆 |
| `body_roll` | 身体波浪 |
| `arm_wave` | 双臂交替上举 |
| `clap` | 鼓掌 |
| `point` | 前指 |
| `spin` | 转体 |
| `wave` | 单手挥 |

所有动作都是 `phase` 的周期函数，phase 0 和 1 闭合；`mirror: true` 会交换
左右肢体。

## 运行时行为

- 一个 `choreograph` 调用就是一段可循环的舞；不占说话时间，和 `speak` 并行。
- `VmcMotionPlayer` 在同一个 60fps tick 里合成：舞蹈 + 手势 + idle + A2F 口型。
- 关节角做指数平滑（`META_HUB_VMC_SMOOTHING`，默认 0.08s）。
- 不支持的动作/超长程序会被 `validate_calls` 拒绝，不会把坏数据送到渲染器。

## 本地试跳

```bash
PYTHONPATH=src .venv/bin/python -m meta_hub.cli dance \
  --program /tmp/dance.json --seconds 12
```

或直接播放内置 8 拍：

```bash
PYTHONPATH=src .venv/bin/python -m meta_hub.cli dance --bpm 128 --seconds 14
```

## LLM 提示词约定

系统提示词已要求：多拍舞蹈用 `choreograph`，不要输出原始骨骼角度。
模型可以组合动作、镜像、重排节拍；运行时负责插值和同步。
