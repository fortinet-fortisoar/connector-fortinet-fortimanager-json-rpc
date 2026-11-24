"""Flag edges whose straight source->target line passes through an unrelated box.

Draw.io's exported SVG does not carry per-cell IDs, so we work from the drawio
XML directly. Each mxCell is either a vertex (with x/y/w/h geometry) or an edge
(with source/target cell refs). For each edge we test the straight line between
the two cell centers against every other vertex rect; if it enters one, the
edge is at risk of visually crossing that box when drawio routes it.

This is a proxy, not a pixel-perfect test (drawio routes orthogonally and may
go around), but it correctly flags cross-lane / cross-row edges that are the
usual culprits for "line through box".

    python check_drawio.py faig_key_rotation.drawio
    exit 0 clean; exit 1 if any crossings found.
"""
from __future__ import annotations
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

INSET = 6  # px shrink box rects so passing just-at-the-edge is not flagged


def _ns(t: str) -> str:
    return t.split("}", 1)[1] if "}" in t else t


def parse_pages(src: Path) -> list[tuple[str, dict, list]]:
    """Return [(page_name, {cell_id: (x, y, w, h, label, parent)}, [(src, tgt, label)])]."""
    out = []
    root = ET.parse(src).getroot()
    for diag in root.iter():
        if _ns(diag.tag) != "diagram":
            continue
        name = diag.get("name", "?")
        vertices: dict = {}
        edges: list = []
        parents: dict = {}
        containers: set = set()   # swimlanes + notes: skipped as obstacles (but used for geometry)
        for cell in diag.iter():
            if _ns(cell.tag) != "mxCell":
                continue
            cid = cell.get("id")
            if not cid:
                continue
            geom = next((c for c in cell if _ns(c.tag) == "mxGeometry"), None)
            label = (cell.get("value") or "").replace("<br>", " ").replace("&quot;", '"')[:60]
            parents[cid] = cell.get("parent")
            style = cell.get("style") or ""
            if cell.get("edge") == "1":
                src, tgt = cell.get("source"), cell.get("target")
                # Author-pinned anchors (exitX/entryX in style) opt out of the
                # straight-line test: drawio's orthogonal router honours them
                # and routes around intermediate boxes.
                anchored = "exitX=" in style and "entryX=" in style
                exit_xy = None
                if "exitX=" in style:
                    import re as _re
                    mx = _re.search(r"exitX=([\d.]+)", style); my = _re.search(r"exitY=([\d.]+)", style)
                    if mx and my:
                        exit_xy = (float(mx.group(1)), float(my.group(1)))
                if src and tgt:
                    # Keep ALL edges for the label-collision pass; mark whether the
                    # straight-line check should fire.
                    edges.append((src, tgt, label, anchored, exit_xy))
            elif cell.get("vertex") == "1" and geom is not None:
                try:
                    x = float(geom.get("x", "0")); y = float(geom.get("y", "0"))
                    w = float(geom.get("width", "0")); h = float(geom.get("height", "0"))
                except ValueError:
                    continue
                if w > 5 and h > 5:
                    vertices[cid] = (x, y, w, h, label)
                    # swimlane zones + notes are containers; shape=image cells are
                    # decorative icons inside a parent box - neither is a flow obstacle.
                    if "swimlane" in style or "shape=note" in style or "shape=image" in style:
                        containers.add(cid)
        # Walk parent chain so a cell nested in a swimlane gets the lane's x/y added.
        def abs_rect(cid: str) -> tuple[float, float, float, float, str] | None:
            v = vertices.get(cid)
            if not v: return None
            x, y, w, h, lab = v
            p = parents.get(cid)
            while p and p in vertices:
                px, py, _, _, _ = vertices[p]
                x += px; y += py
                p = parents.get(p)
            return (x, y, w, h, lab)
        abs_vertices = {cid: abs_rect(cid) for cid in vertices}
        abs_vertices = {k: v for k, v in abs_vertices.items() if v}
        obstacles = {k: v for k, v in abs_vertices.items() if k not in containers}
        out.append((name, abs_vertices, obstacles, edges))
    return out


def _seg_hits_rect(p1, p2, rect) -> bool:
    x, y, w, h, _ = rect
    x0, y0, x1, y1 = x + INSET, y + INSET, x + w - INSET, y + h - INSET
    (ax, ay), (bx, by) = p1, p2
    dx, dy = bx - ax, by - ay
    p = (-dx, dx, -dy, dy)
    q = (ax - x0, x1 - ax, ay - y0, y1 - ay)
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return False
        else:
            t = qi / pi
            if pi < 0:
                if t > u2: return False
                if t > u1: u1 = t
            else:
                if t < u1: return False
                if t < u2: u2 = t
    return u1 <= u2 and u2 > 0.02 and u1 < 0.98


def _exit_side(src_rect, tgt_rect, exit_xy):
    """Which side of src does this edge leave by? 'l' 'r' 't' 'b'."""
    if exit_xy is not None:
        ex, ey = exit_xy
        # Corner anchors pin a side strongly; otherwise the dominant axis wins.
        if ex <= 0.05: return "l"
        if ex >= 0.95: return "r"
        if ey <= 0.05: return "t"
        if ey >= 0.95: return "b"
    sx = src_rect[0] + src_rect[2] / 2; sy = src_rect[1] + src_rect[3] / 2
    tx = tgt_rect[0] + tgt_rect[2] / 2; ty = tgt_rect[1] + tgt_rect[3] / 2
    dx, dy = tx - sx, ty - sy
    if abs(dx) >= abs(dy):
        return "r" if dx > 0 else "l"
    return "b" if dy > 0 else "t"


def _label_rect(mx, my, text):
    """Approximate rect occupied by a label centered at (mx, my).

    drawio's default label font (11pt) renders at roughly 9-10 px/char — the
    earlier 7 px/char undersized labels and let real overlaps slip past the
    checker. Add 10 px padding on each side so a label grazing a box's edge
    still fires. Height is 22 px (text ~14, plus 4 px padding each side).
    """
    w = max(30, len(text) * 10) + 20
    return (mx - w / 2, my - 11, w, 22, text)


def _rects_overlap(a, b):
    ax, ay, aw, ah = a[:4]; bx, by, bw, bh = b[:4]
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _route_hits_rect(segments, rect):
    return any(_seg_hits_rect(a, b, rect) for a, b in segments)


def check_page(vertices: dict, obstacles: dict, edges: list) -> list[str]:
    problems: list[str] = []
    # 1. Edge path crosses an unrelated box. drawio routes orthogonally with one
    # bend; approximate with two candidates (H-then-V and V-then-H) and flag only
    # when BOTH cross something — if one is clean, drawio picks it.
    # Anchor-hinted edges opt out: with explicit exit/entry sides drawio actually
    # routes V-H-V (or H-V-H), going AROUND obstacles in the gutter, and our
    # 2-segment approximation generates false positives. Visually review any edge
    # you anchor; the label-in-box check below still fires on anchored edges.
    for src, tgt, elabel, anchored, _exit in edges:
        if anchored:
            continue
        s = vertices.get(src); t = vertices.get(tgt)
        if not s or not t:
            continue
        sx = s[0] + s[2] / 2; sy = s[1] + s[3] / 2
        tx = t[0] + t[2] / 2; ty = t[1] + t[3] / 2
        hv_route = [((sx, sy), (tx, sy)), ((tx, sy), (tx, ty))]
        vh_route = [((sx, sy), (sx, ty)), ((sx, ty), (tx, ty))]
        hv_hits = [rect for cid, rect in obstacles.items()
                   if cid != src and cid != tgt and _route_hits_rect(hv_route, rect)]
        vh_hits = [rect for cid, rect in obstacles.items()
                   if cid != src and cid != tgt and _route_hits_rect(vh_route, rect)]
        # drawio picks whichever route avoids obstacles. If BOTH candidate routes
        # cross something, it must cross something — report the lighter route.
        if hv_hits and vh_hits:
            lighter = hv_hits if len(hv_hits) <= len(vh_hits) else vh_hits
            names = ", ".join(repr(r[4]) for r in lighter)
            problems.append(f"  {s[4]!r} -> {t[4]!r} [{elabel or '-'}]  path crosses  {names}")
    # 1b. Edge LABEL lands inside an unrelated box. drawio puts the label at the
    # midpoint of the LONGEST segment of the orthogonal route. We don't know the
    # exact route, so test all four plausible positions where the label can land:
    # straight-line midpoint, and midpoints of horizontal legs at src.y / tgt.y
    # and vertical legs at src.x / tgt.x. If any lands inside an unrelated box,
    # flag it. labelBackgroundColor masks box fill but not box text on light bg.
    for src, tgt, elabel, _anc, _exit in edges:
        if not elabel:
            continue
        s = vertices.get(src); t = vertices.get(tgt)
        if not s or not t:
            continue
        sx = s[0] + s[2] / 2; sy = s[1] + s[3] / 2
        tx = t[0] + t[2] / 2; ty = t[1] + t[3] / 2
        candidates = [
            ((sx + tx) / 2, (sy + ty) / 2),   # straight-line midpoint
            ((sx + tx) / 2, sy),              # horizontal leg at source y
            ((sx + tx) / 2, ty),              # horizontal leg at target y
            (sx, (sy + ty) / 2),              # vertical leg at source x
            (tx, (sy + ty) / 2),              # vertical leg at target x
        ]
        hit = None
        for mx, my in candidates:
            lrect = _label_rect(mx, my, elabel)
            for cid, rect in obstacles.items():
                if cid == src or cid == tgt:
                    continue
                if _rects_overlap(lrect, rect):
                    hit = rect[4]; break
            if hit:
                break
        if hit:
            problems.append(f"  {s[4]!r} -> {t[4]!r}  label [{elabel}] lands inside  {hit!r}")
    # 2. Two labeled edges leave the same side of the same source: labels will share a corridor.
    by_src: dict = {}
    for src, tgt, elabel, _anc, exit_xy in edges:
        if not elabel:
            continue
        s = vertices.get(src); t = vertices.get(tgt)
        if not s or not t:
            continue
        by_src.setdefault(src, []).append((_exit_side(s, t, exit_xy), tgt, elabel))
    for src, outs in by_src.items():
        if len(outs) < 2:
            continue
        sides: dict = {}
        for side, tgt, lbl in outs:
            sides.setdefault(side, []).append((tgt, lbl))
        for side, bucket in sides.items():
            # drawio stacks 2 labels above/below one corridor without overlap; 3+
            # on one side crowd each other. Also flag 2+ whose targets share a row
            # (same y means truly on top of each other, not stacked).
            if len(bucket) >= 3:
                collide = True
            elif len(bucket) == 2:
                a_y = vertices[bucket[0][0]][1] + vertices[bucket[0][0]][3] / 2
                b_y = vertices[bucket[1][0]][1] + vertices[bucket[1][0]][3] / 2
                collide = abs(a_y - b_y) < 20  # same row ~ labels truly overlap
            else:
                collide = False
            if collide:
                sname = vertices[src][4]
                labels = ", ".join(f"[{lbl}] -> {vertices.get(t, (0,0,0,0,t))[4]!r}" for t, lbl in bucket)
                problems.append(f"  {sname!r} has {len(bucket)} labeled edges exiting side {side!r}; labels collide: {labels}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_drawio.py <file.drawio>"); return 2
    bad = False
    for i, (name, verts, obs, edges) in enumerate(parse_pages(Path(argv[1])), 1):
        problems = check_page(verts, obs, edges)
        if problems:
            bad = True
            print(f"[FAIL] page {i}: {name}")
            for p in problems:
                print(p)
        else:
            print(f"[OK]   page {i}: {name}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
