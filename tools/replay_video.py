"""Replay a screen recording through the overlay, to see how it behaves on real game footage.

    .venv\\Scripts\\python tools\\replay_video.py recording.mp4 --out replay.mp4

Runs the same Session (reading / card following) and OverlayState (panel
positions and fades) as the live overlay, on the recording's own clock: a
step happens whenever the live loop would have taken its next screenshot,
and time spent on OCR delays the next step just as it would live. The
panels are composited onto the footage and every read / relayout is logged.
"""

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from riven_helper.analyze import Analyzer  # noqa: E402
from riven_helper.config import load_config  # noqa: E402
from riven_helper.capture import Ocr  # noqa: E402
from riven_helper.overlay_state import OverlayState  # noqa: E402
from riven_helper.session import Session  # noqa: E402


def composite(frame_bgr, items):
    if not items:
        return frame_bgr
    img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)).convert("RGBA")
    for _key, panel, x, y, alpha in items:
        if alpha < 255:
            a = panel.getchannel("A").point(lambda v: v * alpha // 255)
            panel = panel.copy()
            panel.putalpha(a)
        img.alpha_composite(panel, (int(x), int(y)))
    return cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2BGR)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("video")
    p.add_argument("--out", help="write the footage with the overlay composited (mp4)")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float, default=None)
    p.add_argument("--frames", help="also save these times (s, comma separated) as PNGs next to --out")
    args = p.parse_args()

    cfg = load_config()
    analyzer = Analyzer(cfg)
    session = Session(analyzer, Ocr())
    state = OverlayState(analyzer, cfg)
    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 60
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H)) if args.out else None
    grabs = sorted(float(t) for t in args.frames.split(",")) if args.frames else []
    cap.set(cv2.CAP_PROP_POS_MSEC, args.start * 1000)

    next_step, steps, n = args.start, 0, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = args.start + n / fps
        n += 1
        if args.end is not None and t > args.end:
            break
        if t >= next_step:
            began = time.perf_counter()
            events, wait = session.step(frame, now=t)
            spent = time.perf_counter() - began
            steps += 1
            for kind, payload in events:
                if kind == "results":
                    img, _lines, results = payload
                    state.on_results((W, H), results)
                    print(f"{t:6.2f}s  READ #{session.reads}: "
                          + (", ".join(f"{r.ev.weapon.name if r.ev else '?'} {r.rating.score:.0f}% "
                                       f"({len(r.card.stats)} stats)" for r in results) or "no cards")
                          + f"   [{spent * 1000:.0f} ms]", flush=True)
                elif kind == "hold":
                    state.on_hold()
                    print(f"{t:6.2f}s  read #{session.reads} not trusted yet, reading again   [{spent * 1000:.0f} ms]",
                          flush=True)
                elif kind == "upgrade":
                    state.on_upgrade((W, H), payload)
                    print(f"{t:6.2f}s  upgrade screen: {payload or 'left'}", flush=True)
                elif kind == "track":
                    state.on_track(payload)
                elif kind == "relayout":
                    state.on_relayout(payload)
                    print(f"{t:6.2f}s  relayout (cards moved, no read)", flush=True)
            next_step = t + max(wait, spent)
        items = state.tick()
        if writer or (grabs and t >= grabs[0]):
            out = composite(frame, items)
            if writer:
                writer.write(out)
            while grabs and t >= grabs[0]:
                cv2.imwrite(str(Path(args.out).with_suffix("")) + f"_{grabs.pop(0):05.2f}s.png", out)
    if writer:
        writer.release()
    print(f"done: {n} frames, {steps} steps, {session.reads} reads")


if __name__ == "__main__":
    main()
