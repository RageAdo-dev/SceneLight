"""Validate real Ren'Py observations and assemble their screenshots/recording."""

from __future__ import annotations

import argparse
import html
import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image


def summarize(rows: list[dict], manifest: dict) -> list[dict]:
    report = []
    for name in sorted({" ".join(row.get("name", [])[1:]) for row in rows}):
        samples = [r for r in rows if " ".join(r.get("name", [])[1:]) == name]
        sequence = manifest.get("scene_sequences", {}).get(name, {})
        compared, mismatches = 0, 0
        for row in samples:
            expected = None
            if sequence.get("mode") == "visible-source" and len(row["background"]) == 1:
                expected = sequence["sources"].get(row["background"][0])
            elif (
                sequence.get("mode") == "movie-position"
                and row.get("movie_lighting_pos", row.get("movie_pos")) is not None
            ):
                expected = name
                for time_ms, key in sequence["frames"]:
                    if time_ms > row.get("movie_lighting_pos", row["movie_pos"]) * 1000:
                        break
                    expected = key
            elif not sequence:
                expected = name
            if expected is not None:
                compared += 1
                mismatches += row["fields"] != [expected]
        report.append(
            {
                "scene": name,
                "observations": len(samples),
                "fields": len({tuple(row["fields"]) for row in samples}),
                "compared": compared,
                "mismatches": mismatches,
            }
        )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("game", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = json.loads((args.game / "game/scenelight_runtime/manifest.json").read_text())
    before = json.loads((root / "before/observations.json").read_text())
    verified_dir = "final" if (root / "final/observations.json").is_file() else "verified"
    rows = json.loads((root / verified_dir / "observations.json").read_text())
    summary = summarize(rows, manifest)
    extended_dir = (
        "final-extended" if (root / "final-extended/observations.json").is_file() else "extended"
    )
    extended_path = root / extended_dir / "observations.json"
    if extended_path.is_file():
        summary.extend(summarize(json.loads(extended_path.read_text()), manifest))
    baseline = summarize(before, manifest)
    original = np.asarray(Image.open(root / "before/06.png").convert("RGB"), dtype=np.int16)
    current = np.asarray(Image.open(root / verified_dir / "06.png").convert("RGB"), dtype=np.int16)
    difference = np.abs(original - current)
    static = {
        "mean_channel_difference": float(difference.mean()),
        "max_channel_difference": int(difference.max()),
    }
    result = {
        "before": baseline,
        "after": summary,
        "static_classroom": static,
        "engine": "Ren'Py 7.8.7, gl2, RTX 4090",
        "manifest_version": manifest["version"],
    }
    (root / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    # Each screenshot is the actual game's last presented frame. Preserve
    # capture timestamps rather than pretending capture ran at a fixed FPS.
    frames = sorted((root / verified_dir).glob("video-*.png"))
    concat = ["ffconcat version 1.0"]
    for index, frame in enumerate(frames):
        row_index = min(len(rows) - 1, int(frame.stem.split("-")[1]) - 1)
        if index + 1 < len(frames):
            next_index = min(len(rows) - 1, int(frames[index + 1].stem.split("-")[1]) - 1)
            duration = max(0.01, rows[next_index]["st"] - rows[row_index]["st"])
        else:
            duration = 0.2
        concat.extend([f"file '{frame.relative_to(root).as_posix()}'", f"duration {duration:.6f}"])
    concat_path = root / "recording.ffconcat"
    concat_path.write_text("\n".join(concat) + "\n")
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-v",
            "error",
            "-y",
            "-safe",
            "1",
            "-i",
            str(concat_path),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(root / "verified-game.mp4"),
        ],
        check=True,
    )
    table = "".join(
        f"<tr><td>{html.escape(r['scene'])}</td><td>{r['observations']}</td>"
        f"<td>{r['fields']}</td><td>{r['mismatches']} / {r['compared']}</td></tr>"
        for r in summary
    )
    page = """<!doctype html><meta charset="utf-8"><title>SceneLight — actual game verification</title>
<style>body{font:17px system-ui;background:#101820;color:#edf5fc;max-width:1200px;margin:30px auto;padding:0 24px}
h1{font-size:32px}p{line-height:1.55;color:#c4d6e4}video{width:100%;border-radius:10px}table{border-collapse:collapse;width:100%;margin:24px 0}td,th{text-align:left;padding:12px;border-bottom:1px solid #344554}
select,button{font:inherit;padding:10px;background:#203649;color:white;border:1px solid #729cbb;border-radius:6px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}.pair img{width:100%}a{color:#84cefc}small{color:#b6c6d4}</style>
<h1>SceneLight: actual game verification</h1>
<p>This is a recording from <b>Backrooms Media Lab — Copy (2)</b>, not the standalone preview renderer.
The background and Monika were rendered together by Ren’Py 7.8.7. The audit held each animation through multiple loops and changed Monika’s expression without changing the background.</p>
<video controls muted preload="metadata" src="verified-game.mp4"></video>
<p>The recording samples the actual game at about five screenshots per second; it does not represent normal playback performance.
The observation log separately compares the displayed background state or movie position with the character’s selected lighting field.</p>
<table><tr><th>Background</th><th>Observations</th><th>Distinct lighting fields</th><th>Mismatches / compared</th></tr>TABLE</table>
<h2>Captured scenes</h2><select id="scene"><option value="0">Dynamic background — first capture</option><option value="1">Dynamic background — later capture</option><option value="2">GIF frame animation</option><option value="3">ATL animation</option><option value="4">Looping movie</option><option value="5">Static-noise frame animation</option><option value="6">Ordinary classroom control</option></select>
<div class="pair"><div><p>Previous build</p><img id="before"></div><div><p>Verified build</p><img id="after"></div></div>
<p>Animated captures may show different frames: they are separate live runs, not synchronized still-image A/B comparisons. Use the recording and matching-state log to judge synchronization.</p>
<p>Classroom control: mean RGB channel difference STATIC_MEAN; maximum STATIC_MAX (0–255 scale).</p>
<h2>Scope and limits</h2><p>This checks named master-layer backgrounds. Arbitrary screen composites, movie masks, and Python-generated states outside the captured inventory are not certified by this test. An unseen source state is left unlit and logged. Movie lighting is preanalysed at approximately 8 Hz, while frame animations select their captured source directly.</p>
<p><a href="results.json">Results JSON</a> · <a href="verified/observations.json">Raw observations</a></p>
<script>const s=document.querySelector('#scene');function draw(){let n=String(s.value).padStart(2,'0');document.querySelector('#before').src='before/'+n+'.png';document.querySelector('#after').src='verified/'+n+'.png'}s.onchange=draw;draw()</script>"""
    page = page.replace("TABLE", table).replace(
        "STATIC_MEAN", f"{static['mean_channel_difference']:.4f}"
    )
    page = page.replace("STATIC_MAX", str(static["max_channel_difference"]))
    page = page.replace("verified/", verified_dir + "/")
    if extended_path.is_file():
        names = [
            "TV-static GIF frames",
            "Optical GIF frames",
            "Pool movie",
            "Manual movie channel",
            "Real VHS movie",
        ]
        captures = "<details><summary>Additional animation captures</summary>"
        for index, name in enumerate(names):
            captures += f'<p>{name}</p><img style="width:100%" src="extended/{index:02d}.png">'
        captures += (
            '</details><p><a href="extended/observations.json">Additional raw observations</a></p>'
        )
        page = page.replace("<h2>Scope and limits</h2>", captures + "<h2>Scope and limits</h2>")
        page = page.replace("extended/", extended_dir + "/")
    (root / "index.html").write_text(page, encoding="utf-8")
    print(json.dumps(result, indent=2))
    if any(r["mismatches"] or r["compared"] == 0 for r in summary):
        raise SystemExit("Temporal verification failed; inspect raw observations before shipping.")


if __name__ == "__main__":
    main()
