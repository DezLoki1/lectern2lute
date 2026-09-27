"""Long-lived IndexTTS-2.5 worker.

This script runs inside IndexTTS's own Python environment, not lectern2lute's,
because IndexTTS pins its own torch/transformers/numpy versions. It must not
import anything from book2audio.

Protocol: one JSON object per line. The worker prints {"ready": true} once the
model is loaded, then answers each request line with {"ok": true} or
{"ok": false, "error": "..."}. IndexTTS prints its own progress to stdout, so
the real stdout is reserved for protocol lines and everything else goes to
stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", default="checkpoints")
    parser.add_argument("--no-bf16", action="store_true")
    args = parser.parse_args()

    protocol_out = sys.stdout
    sys.stdout = sys.stderr

    def send(payload: dict) -> None:
        protocol_out.write(json.dumps(payload) + "\n")
        protocol_out.flush()

    try:
        from indextts.infer_v2_5 import IndexTTS2

        model_dir = os.path.abspath(args.model_dir)
        tts = IndexTTS2(
            cfg_path=os.path.join(model_dir, "config.yaml"),
            model_dir=model_dir,
            use_bf16=not args.no_bf16,
        )
    except Exception as exc:
        traceback.print_exc()
        send({"ok": False, "error": f"IndexTTS failed to load: {exc}"})
        return 1

    send({"ready": True})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            tts.infer(
                spk_audio_prompt=request["voice_path"],
                text=request["text"],
                output_path=request["output_path"],
                lang=request.get("lang", "EN"),
                duration_factor=float(request.get("duration_factor", 1.0)),
                verbose=False,
            )
            if not os.path.exists(request["output_path"]):
                raise RuntimeError("IndexTTS finished without writing an output file.")
            send({"ok": True})
        except Exception as exc:
            traceback.print_exc()
            send({"ok": False, "error": str(exc)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
