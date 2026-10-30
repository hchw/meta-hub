# 运行实时直播循环（VNyan / 当前 Pi 模型）

`meta-hub live` 把已经实现的各段接起来：

```text
TCP/JSON ingress (7711)
  -> Gatekeeper（冷却/沉默/预算/优先级/硬打断）
  -> LLM tool-calling（默认使用当前 Pi agent 的模型）
  -> TimelineCompiler / TimelineExecutor
  -> VmcMotionPlayer（骨骼 + 表情 + idle）
  -> PlayerSpeaker（CosyVoice + A2F 口型 + Windows 音频）
  -> VMC/UDP -> VNyan（端口 3334）
```

## 启动

```bash
cd /home/hebl/project/meta-hub

export META_HUB_VMC_HOST=127.0.0.1
export META_HUB_VMC_PORT=3334          # VNyan VMC Receiver 2
export META_HUB_VMC_BLEND_PROFILE=vrm1 # 当前 avatar 是 VRM1
export META_HUB_VMC_RENDERER=vnyan
export META_HUB_VMC_BONES=1
export META_HUB_VMC_ROOT=0
export META_HUB_VMC_BONE_APPLY=0
export META_HUB_AUDIO=1                # 1=Windows 默认音频设备

PYTHONPATH=src .venv/bin/python -m meta_hub.cli live
```

默认模型：读取 `~/.pi/agent/commandcode.json` + `auth.json` + `settings.json`，
即当前 Pi agent 正在使用的模型（`PI_MODEL` / `defaultModel`）。也可显式指定：

```bash
... meta_hub.cli live --model deepseek/deepseek-v4.1-flash \
  --base-url https://api.commandcode.ai/provider/v1 --api-key "$KEY"
```

停止：`Ctrl-C`，或 `--seconds 1800` 跑固定时长。

## 输入事件

ingress 是 TCP 客户端，连接 `127.0.0.1:7711`，每行一个 JSON Event：

```json
{"kind":"comment","event_id":"e1","viewer_id":"u1","viewer_name":"观众A","text":"主播你好"}
```

字段见 `src/meta_hub/events.py`。没有 capture sidecar 时，可先用
`tests`/脚本向 7711 发事件做端到端验收。

## 单次快速自检

不经过 ingress/LLM，直接验证 TTS + A2F + 表情 + 手势：

```bash
PYTHONPATH=src .venv/bin/python -m meta_hub.cli demo "你好，测试一下口型和点头。" \
  --gesture nod --expression joy
```

## 动作库

`gesture` 工具和 `meta-hub demo --gesture` 现在支持：

| 名称 | 部位 |
| --- | --- |
| `nod` / `shake` / `tilt` | 头 |
| `lean` / `bow` | 胸/脊柱/髋 |
| `wave` | 右臂 + 手 |
| `arms_up` | 双臂 |
| `point` | 右臂 + 转胸 |
| `clap` | 双臂 |
| `dance` | 髋/脊柱/胸/双臂/腿，默认 6 秒 |

单测覆盖了这些动作会回到 rest，并且 `dance` 会驱动 hips/arms/legs。
VNyan 侧对应打开 `Track Left/Right Arm/Hand`、`Track Hip Rotation` 和
`Track Left/Right Leg`（当前 3334 层都是 1.0）。

## LLM 编舞

LLM 可以调用 `choreograph` 生成多拍舞蹈，详见 `docs/choreography.md`。
`meta-hub dance --program <json>` 可单独试跳。

## 已实测

- VNyan VMC Receiver 2（3334）的头/颈/脊柱骨骼可驱动 avatar。
- `trackBlendshapes=1.0` 后 `aa/happy/blink` 等 VRM1 表情可呈现。
- `live` 已用当前 Pi 模型、真实 TTS、A2F、VNyan 跑通一轮发言。
