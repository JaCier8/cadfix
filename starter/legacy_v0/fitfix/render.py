"""Quick matplotlib renders of an assembly (for humans, demo slides and an optional agent tool)."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np

from . import geom as g

COLORS = {"enclosure": "#c9b8a6", "pcb": "#2f7d4a", "usb_plug": "#3a3a3a", "lid": "#9fb6cf"}


def render(parts: dict, path, view=(25, -130), hide=("lid",), zoom_box=None, title=None):
    fig = plt.figure(figsize=(7, 5.5), dpi=130)
    ax = fig.add_subplot(111, projection="3d")
    allpts = []
    for name, m in parts.items():
        if name in hide:
            continue
        tm = g.to_trimesh(m)
        tris = tm.triangles
        if zoom_box is not None:
            c = tris.mean(axis=1)
            keep = np.all((c >= zoom_box[0]) & (c <= zoom_box[1]), axis=1)
            tris = tris[keep]
        if len(tris) == 0:
            continue
        light = np.clip(0.55 + 0.45 * tm.face_normals[: len(tris)] @ np.array([0.3, -0.5, 0.8]), 0.25, 1)
        base = np.array(matplotlib.colors.to_rgb(COLORS.get(name, "#888888")))
        fc = np.clip(base[None, :] * light[:, None], 0, 1)
        ax.add_collection3d(Poly3DCollection(tris, facecolors=fc, edgecolors=(0, 0, 0, 0.08), linewidths=0.2))
        allpts.append(tris.reshape(-1, 3))
    pts = np.vstack(allpts)
    lo, hi = pts.min(0), pts.max(0)
    ctr, rad = (lo + hi) / 2, (hi - lo).max() / 2
    ax.set_xlim(ctr[0] - rad, ctr[0] + rad)
    ax.set_ylim(ctr[1] - rad, ctr[1] + rad)
    ax.set_zlim(ctr[2] - rad, ctr[2] + rad)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(*view)
    ax.set_xlabel("x"), ax.set_ylabel("y"), ax.set_zlabel("z")
    if title:
        ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def render_section(parts: dict, axis: str, value: float, path, window=None, title=None):
    """2D cut through several parts at axis=value: the clearest way to show a fit problem."""
    from matplotlib.patches import Polygon
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch

    fig, ax = plt.subplots(figsize=(6.5, 4.2), dpi=130)
    labels = None
    for name, m in parts.items():
        loops = g.section(m, axis, value)
        if not loops:
            continue
        labels = loops[0]["coords"]
        verts, codes = [], []
        for l in loops:
            pts = l["points"]
            verts += pts.tolist() + [pts[0].tolist()]
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(pts) - 1) + [MPath.CLOSEPOLY]
        patch = PathPatch(MPath(verts, codes), facecolor=COLORS.get(name, "#888"), edgecolor="black",
                          lw=0.6, alpha=0.75, label=name)
        ax.add_patch(patch)
    ax.autoscale_view()
    if window:
        ax.set_xlim(*window[0]), ax.set_ylim(*window[1])
    ax.set_aspect("equal")
    if labels:
        ax.set_xlabel(f"{labels[0]} [mm]"), ax.set_ylabel(f"{labels[1]} [mm]")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)
    if title:
        ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
