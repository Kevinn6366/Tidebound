# Qwen3-TTS 角色参考音频

每个角色一个子目录，内含两样克隆素材（缺一不可，参考音频文字稿是克隆质量的关键）：

```
voices/
  ATRI/
    ref.wav    # 3~10 秒日语参考音频（复用现有 ref_audio 或原素材截取）
    ref.txt    # 参考音频的逐字文字稿（日语，务必逐字精确）
  Sui/
    ref.wav
    ref.txt
```

- `ref.wav` 也兼容 `.mp3 / .flac / .m4a`（大小写不敏感，但首选 `ref.wav`）。
- `ref.txt` 内容为参考音频里**逐字**说的话，用于 `create_voice_clone_prompt` 生成克隆 prompt。
- 现有多角色（ATRI、Sui）可直接复用 `tts/ref_audio/` 下的素材迁移过来。
- Qwen3-TTS 是 zero-shot 克隆，**无需重新训练**。