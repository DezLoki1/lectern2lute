# TTS backend notes

## Recommended default: Kokoro

Kokoro is the first-class backend for this project because it best matches the current goals:

- fully local
- Windows-friendly
- practical on a 16 GB NVIDIA GPU
- fast enough for iterative audiobook cleanup and rerendering
- simple Python API through the official `kokoro` package

The official examples use `KPipeline`, emit 24 kHz audio, and document Windows `espeak-ng` installation.

## Future path: Higgs

Higgs remains a strong future option for expressiveness and later voice-cloning work, but it is not the default backend for this repo yet.

Why not first:

- the Boson open-source repo still says the v2 generation examples perform best on a GPU with at least 24 GB memory
- this project is targeting a 16 GB GPU first
- Higgs exposes a more complex generation stack than Kokoro, which makes it a worse first integration target for a cleanup-heavy audiobook CLI

Why still leave room for it:

- Boson says Higgs Audio V2.5 reduces the architecture to 1B parameters while improving speed and quality over the earlier 3B model
- Hugging Face Transformers added Higgs Audio V2 support in February 2026, which should make a future integration path more straightforward

## Decision

Ship Kokoro as the primary built-in backend first.

Keep the generic command backend and the render interfaces stable so we can add:

- an experimental Higgs backend later
- reference-audio voice cloning later
- GUI controls without changing the core pipeline

## References

- Kokoro official repo: <https://github.com/hexgrad/kokoro>
- Kokoro package metadata: <https://pypi.org/project/kokoro/>
- Higgs Audio official repo: <https://github.com/boson-ai/higgs-audio>
- Higgs Audio V2 Transformers docs: <https://huggingface.co/docs/transformers/model_doc/higgs_audio_v2>
