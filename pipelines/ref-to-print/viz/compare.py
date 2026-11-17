"""Score how well a rendered silhouette matches a reference picture of the same view.

    python -m viz.compare --render SILHOUETTE.png --ref REFERENCE.png [--out FILE] [--min-iou 0.6]

Both pictures are reduced to a foreground mask, cropped to the bounding box, padded to a
square and resized to 256 x 256, so position and scale do not matter. The score is the
intersection over union (IoU); the mirrored reference is tried too and the better one wins.

Reference mask: alpha > 128 when the image has a non-trivial alpha channel; otherwise pixels
far from the dominant border colour are foreground. This needs references on a plain
background and is a rough measure, not a proof of likeness.

Exit 0 pass, 1 fail, 2 bad input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from checks.report import finish, make_report, result

NORM = 256
COLOUR_DISTANCE = 40.0


def mask_from_image(path: str | Path) -> tuple[np.ndarray, str]:
    """Return (boolean foreground mask, method description)."""
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        alpha = np.asarray(img.convert("RGBA"))[:, :, 3]
        if alpha.min() < 255:
            return alpha > 128, "alpha channel"
    rgb = np.asarray(img.convert("RGB")).astype(float)
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    keys, counts = np.unique((border // 16).astype(int), axis=0, return_counts=True)
    dominant = border[((border // 16).astype(int) == keys[counts.argmax()]).all(axis=1)].mean(axis=0)
    return np.linalg.norm(rgb - dominant, axis=2) > COLOUR_DISTANCE, "border background colour"


def normalise(mask: np.ndarray) -> np.ndarray:
    """Crop to the bounding box, pad to a square, resize to NORM x NORM."""
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        raise ValueError("mask is empty (no foreground found)")
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = crop.shape
    side = max(h, w)
    square = np.zeros((side, side), dtype=np.uint8)
    top, left = (side - h) // 2, (side - w) // 2
    square[top:top + h, left:left + w] = crop * 255
    small = Image.fromarray(square).resize((NORM, NORM), Image.BILINEAR)
    return np.asarray(small) > 127


def iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def silhouette_iou(render_path: str | Path, ref_path: str | Path) -> tuple[float, bool, str]:
    """Return (best IoU, reference was mirrored, mask method of the reference)."""
    render_mask, _ = mask_from_image(render_path)
    ref_mask, method = mask_from_image(ref_path)
    r = normalise(render_mask)
    plain = iou(r, normalise(ref_mask))
    flipped = iou(r, normalise(ref_mask[:, ::-1]))
    return (flipped, True, method) if flipped > plain else (plain, False, method)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="viz.compare", description="Silhouette IoU against a reference picture")
    ap.add_argument("--render", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--out")
    ap.add_argument("--min-iou", type=float, default=0.6)
    args = ap.parse_args(argv)
    try:
        value, mirrored, method = silhouette_iou(args.render, args.ref)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    note = f"{'reference mirrored horizontally' if mirrored else 'reference not mirrored'}; mask: {method}"
    res = result(Path(args.render).name, "silhouette_iou", value >= args.min_iou, value, args.min_iou, "", note)
    return finish(make_report("gate", [res]), args.out)


if __name__ == "__main__":
    raise SystemExit(main())
