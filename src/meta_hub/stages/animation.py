"""Animation stage: wav -> ARKit blendshape frames, via the Audio2Face-3D NIM (gRPC)."""
from __future__ import annotations
from typing import Iterator
from ..config import settings


def a2f_frames(wav_path: str, grpc_target: str | None = None, with_time: bool = False) -> Iterator:
    """Yield (blend_names, {name: weight}) frames for a wav, from A2F-3D over gRPC.

    With ``with_time=True`` also yield the frame's audio time-code in seconds,
    giving the sample-counter timeline used for the single media clock (D5).
    """
    import numpy as np
    import soundfile as sf
    import grpc
    from nvidia_audio2face_3d import audio2face_pb2_grpc as stubmod, messages_pb2 as m
    from nvidia_ace import audio_pb2

    target = grpc_target or settings.a2f_target
    data, sr = sf.read(wav_path, dtype="float32", always_2d=False)
    if getattr(data, "ndim", 1) > 1:
        data = data[:, 0]
    if sr != settings.a2f_sample_rate:
        t = np.linspace(0, 1, len(data))
        tn = np.linspace(0, 1, int(len(data) * settings.a2f_sample_rate / sr))
        data = np.interp(tn, t, data)
    # A2F is extremely input-gain sensitive: quiet speech yields a near-silent
    # (JawOpen==0) animation. Peak-normalize to full scale before PCM16 encoding.
    peak = float(np.abs(data).max()) if len(data) else 0.0
    if peak > 1e-6:
        data = data / peak * 0.97
    pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16)

    def req():
        yield m.AudioWithEmotionStream(audio_stream_header=m.AudioWithEmotionStreamHeader(
            audio_header=audio_pb2.AudioHeader(
                audio_format=0, channel_count=1,
                samples_per_second=settings.a2f_sample_rate, bits_per_sample=16)))
        for i in range(0, len(pcm), 1600):
            yield m.AudioWithEmotionStream(
                audio_with_emotion=m.AudioWithEmotion(audio_buffer=pcm[i:i + 1600].tobytes()))
        yield m.AudioWithEmotionStream(end_of_audio=m.AudioWithEmotionStream.EndOfAudio())

    stub = stubmod.A2FControllerServiceStub(grpc.insecure_channel(target))
    names: list[str] = []
    for resp in stub.ProcessAudioStream(req()):
        part = resp.WhichOneof("stream_part")
        if part == "animation_data_stream_header":
            h = resp.animation_data_stream_header
            if h.HasField("skel_animation_header"):
                names = list(h.skel_animation_header.blend_shapes)
        elif part == "animation_data":
            sa = resp.animation_data.skel_animation
            if len(sa.blend_shape_weights):
                bs = sa.blend_shape_weights[-1]
                frame = dict(zip(names, list(bs.values)))
                if with_time:
                    yield names, frame, float(bs.time_code)
                else:
                    yield names, frame
