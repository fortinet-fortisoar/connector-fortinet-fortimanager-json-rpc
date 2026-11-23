"""Diagrams for docs/HOW_THE_CONNECTOR_WORKS.md. Regenerate: python build_diagram.py

Patterns:
- page() for swimlane flows (one lane per actor, one row per step)
- overview_page() for architecture overviews (free-positioned system boxes)
- Lane colours shared across pages so audience can track components
- Validator (check_drawio.py) runs as the last build step and fails on crossings

Author: edit COLORS, define pages, then `python build_diagram.py`.
"""
import base64
import sys
from pathlib import Path
from xml.sax.saxutils import escape

LANE_W, HEAD, ROW_H, BOX_W, BOX_H = 280, 44, 120, 210, 76

COLORS = {  # (fill, stroke) -- one colour per role, same on every page
    "caller": ("#E8F5E9", "#43A047"),  # green -- the playbook / request
    "conn":   ("#E3F2FD", "#1E88E5"),  # blue  -- the connector
    "lock":   ("#FFF8E1", "#F9A825"),  # amber -- a lock is taken
    "none":   ("#F5F5F5", "#757575"),  # grey  -- no lock / outside
    "fmg":    ("#FCE4EC", "#D81B60"),  # pink  -- FortiManager
    "db":     ("#EDE7F6", "#5E35B1"),  # purple -- FortiSOAR database / device
}
SHAPES = {
    "box":   "rounded=1;whiteSpace=wrap;html=1;arcSize=12;",
    "start": "rounded=1;whiteSpace=wrap;html=1;arcSize=50;fontStyle=1;",
    "end":   "rounded=1;whiteSpace=wrap;html=1;arcSize=50;dashed=1;",
    "dec":   "rhombus;whiteSpace=wrap;html=1;",
    "note":  "shape=note;whiteSpace=wrap;html=1;size=14;align=left;spacingLeft=8;"
             "fillColor=#FFFDE7;strokeColor=#9E9D24;",
}
EDGE = ("edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;fontSize=11;"
        "labelBackgroundColor=#FFFFFF;")  # opaque pill so labels never bleed into boxes

_SIDE = {"l": (0, 0.5), "r": (1, 0.5), "t": (0.5, 0), "b": (0.5, 1),
         "lt": (0, 0.2), "lb": (0, 0.8), "rt": (1, 0.2), "rb": (1, 0.8),
         "tl": (0.2, 0), "tr": (0.8, 0), "bl": (0.2, 1), "br": (0.8, 1)}

# Fortinet TEC icon library — base64-embed any of 721 SVGs by name.
TEC_ICONS = Path.home() / "PycharmProjects/TEC/tec-builder-template/hugo-builder/static/images/icons"


def icon_shape(name: str) -> str:
    """Style string for an icon cell. Pass as the `shape` slot in a node tuple."""
    p = TEC_ICONS / f"{name}.svg"
    b64 = base64.b64encode(p.read_bytes()).decode()
    return (f"shape=image;html=1;labelPosition=right;align=left;verticalLabelPosition=middle;"
            f"verticalAlign=middle;image=data:image/svg+xml;base64,{b64};")


def page(name, title, lanes, nodes, edges, notes=()):
    """Swimlane flow page.
    lanes: [(key, label)]  — key picks a COLORS entry; label is the swimlane header
    nodes: [(id, lane, row, shape, text)]  — shape in SHAPES or a full icon_shape() style
    edges: [(src, dst, label)] or [(src, dst, label, exit_side, entry_side)]
    notes: [(x, y, w, h, text)]  — absolute positions on the page
    """
    col = {k: i for i, (k, _) in enumerate(lanes)}
    rows = max(n[2] for n in nodes) + 1
    height = HEAD + 60 + rows * ROW_H
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>',
             f'<mxCell id="title" value="{escape(title)}" style="text;html=1;fontSize=20;fontStyle=1;" '
             f'vertex="1" parent="1"><mxGeometry x="0" y="-60" width="{LANE_W * len(lanes)}" '
             f'height="40" as="geometry"/></mxCell>']
    for k, label in lanes:
        fill, stroke = COLORS[k]
        cells.append(f'<mxCell id="lane_{k}" value="{escape(label)}" style="swimlane;html=1;startSize={HEAD};'
                     f'fillColor={fill};strokeColor={stroke};fontStyle=1;fontSize=14;swimlaneFillColor=#FFFFFF;" '
                     f'vertex="1" parent="1"><mxGeometry x="{col[k] * LANE_W}" y="0" width="{LANE_W}" '
                     f'height="{height}" as="geometry"/></mxCell>')
    for nid, lane, row, shape, text in nodes:
        fill, stroke = COLORS[lane]
        style = SHAPES.get(shape, shape)  # a key, or a full style string
        is_dec = shape == "dec"
        w, h = (BOX_W - 20, BOX_H + 24) if is_dec else (BOX_W, BOX_H)
        x = col[lane] * LANE_W + (LANE_W - w) / 2
        y = HEAD + 30 + row * ROW_H + (BOX_H - h) / 2
        value = escape("<br>".join(escape(line) for line in text.split("\n")), {'"': "&quot;"})
        extra = f"fillColor={fill};strokeColor={stroke};" if shape in SHAPES else ""
        cells.append(f'<mxCell id="{nid}" value="{value}" style="{style}{extra}fontSize=12;" '
                     f'vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
                     f'as="geometry"/></mxCell>')
    for i, e in enumerate(edges):
        src, dst, label = e[0], e[1], e[2]
        style = EDGE
        if len(e) > 3 and e[3] in _SIDE:
            a = _SIDE[e[3]]; style += f"exitX={a[0]};exitY={a[1]};exitDx=0;exitDy=0;"
        if len(e) > 4 and e[4] in _SIDE:
            a = _SIDE[e[4]]; style += f"entryX={a[0]};entryY={a[1]};entryDx=0;entryDy=0;"
        cells.append(f'<mxCell id="e{i}" value="{escape(label, {chr(34): "&quot;"})}" style="{style}" '
                     f'edge="1" parent="1" source="{src}" target="{dst}">'
                     f'<mxGeometry relative="1" as="geometry"/></mxCell>')
    for i, (x, y, w, h, text) in enumerate(notes):
        value = escape("<br>".join(escape(line) for line in text.split("\n")), {'"': "&quot;"})
        cells.append(f'<mxCell id="n{i}" value="{value}" style="{SHAPES["note"]}fontSize=12;" '
                     f'vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
                     f'as="geometry"/></mxCell>')
    return (f'<diagram name="{escape(name)}" id="{name.lower().replace(" ", "-")}">'
            f'<mxGraphModel grid="1" gridSize="10" page="0"><root>{"".join(cells)}</root>'
            f'</mxGraphModel></diagram>')


def overview_page(name, title, boxes, edges, notes=()):
    """Free-positioned architecture page (no swimlanes).
    boxes: [(id, x, y, w, h, colour_key, header, body)]
    edges: [(src, dst, label)] or [(src, dst, label, exit_side, entry_side)]
    """
    maxx = max(b[1] + b[3] for b in boxes) + 40
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>',
             f'<mxCell id="title" value="{escape(title)}" style="text;html=1;fontSize=20;fontStyle=1;" '
             f'vertex="1" parent="1"><mxGeometry x="20" y="-60" width="{maxx-40}" height="40" '
             f'as="geometry"/></mxCell>']
    for nid, x, y, w, h, lane, header, body in boxes:
        fill, stroke = COLORS[lane]
        inner = f"<b>{escape(header)}</b><br>" + "<br>".join(escape(line) for line in body.split("\n"))
        text = escape(inner, {'"': "&quot;"})
        cells.append(f'<mxCell id="{nid}" value="{text}" style="rounded=1;whiteSpace=wrap;html=1;arcSize=8;'
                     f'fillColor={fill};strokeColor={stroke};fontSize=12;align=center;verticalAlign=top;'
                     f'spacingTop=6;" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" '
                     f'height="{h}" as="geometry"/></mxCell>')
    for i, e in enumerate(edges):
        src, dst, label = e[0], e[1], e[2]
        style = EDGE
        if len(e) > 3 and e[3] in _SIDE:
            a = _SIDE[e[3]]; style += f"exitX={a[0]};exitY={a[1]};exitDx=0;exitDy=0;"
        if len(e) > 4 and e[4] in _SIDE:
            a = _SIDE[e[4]]; style += f"entryX={a[0]};entryY={a[1]};entryDx=0;entryDy=0;"
        cells.append(f'<mxCell id="e{i}" value="{escape(label, {chr(34): "&quot;"})}" style="{style}" '
                     f'edge="1" parent="1" source="{src}" target="{dst}">'
                     f'<mxGeometry relative="1" as="geometry"/></mxCell>')
    for i, (x, y, w, h, text) in enumerate(notes):
        value = escape("<br>".join(escape(line) for line in text.split("\n")), {'"': "&quot;"})
        cells.append(f'<mxCell id="n{i}" value="{value}" style="{SHAPES["note"]}fontSize=12;" '
                     f'vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" '
                     f'as="geometry"/></mxCell>')
    return (f'<diagram name="{escape(name)}" id="{name.lower().replace(" ", "-")}">'
            f'<mxGraphModel grid="1" gridSize="10" page="0"><root>{"".join(cells)}</root>'
            f'</mxGraphModel></diagram>')


# ===== pages =====

decide = page(
    "Lock decision", "Which workspace lock does a call take?",
    [("caller", "Request"), ("conn", "Connector decides"), ("none", "No lock"), ("lock", "Lock taken")],
    [
        ("r0", "caller", 0, "start", "Action call\nURL + payload"),
        ("d1", "conn", 1, "dec", "get, workspace off,\nexempt URL or\nauto_lock_ws?"),
        ("n1", "none", 1, "end", "Run unlocked\n(log says why)"),
        ("d2", "conn", 2, "dec", "ADOM\nresolved?"),
        ("n2", "none", 2, "end", "Run unlocked\n+ WARNING"),
        ("d4", "conn", 3, "dec", "Minimal locking,\nnot global, device DB\nor onboarding?"),
        ("ladom", "lock", 3, "end", "ADOM lock\n(global ADOM:\nglobal lock)"),
        ("d5", "conn", 4, "dec", "Package or device\nresolved?"),
        ("lscope", "lock", 4, "end", "pkg/<path> or\ndev/<name> lock"),
        ("lfb", "lock", 5, "end", "ADOM lock\n(fallback, logged)"),
    ],
    [
        ("r0", "d1", "", "r", "t"),
        ("d1", "n1", "yes", "r", "l"),
        ("d1", "d2", "no", "b", "t"),
        ("d2", "n2", "no", "r", "l"),
        ("d2", "d4", "yes", "b", "t"),
        ("d4", "ladom", "no", "r", "l"),
        ("d4", "d5", "yes", "b", "t"),
        ("d5", "lscope", "yes", "r", "l"),
        ("d5", "lfb", "no", "b", "l"),
    ],
    [(0, 860, 640, 150,
      "API key auth: a key lock (Postgres advisory lock; file lock off-box)\n"
      "is taken first, on top of the scope above.\n"
      "Every lock: retry every 1-10s, WARNING each minute while waiting,\n"
      "INFO with the total wait once taken. -6 / -10 / -11 fail at once.\n"
      "Run the call, commit, release in finally.\n"
      "Installs and scripts: hold until the task finishes (next page).")],
)

hold = page(
    "Hold until task", "Installs and scripts: the lock outlives the RPC",
    [("conn", "Connector"), ("fmg", "FortiManager"), ("db", "Queued task")],
    [
        ("c0", "conn", 0, "start", "Lock (ADOM / pkg / dev)"),
        ("f0", "fmg", 0, "box", "Lock granted"),
        ("c1", "conn", 1, "box", "execute install/package,\ninstall/device,\nreinstall or script"),
        ("f1", "fmg", 1, "box", "Queue the task,\nreturn task id\n(status 0)"),
        ("t2", "db", 2, "box", "Task copies config or\nruns the script\n(needs the lock)"),
        ("c3", "conn", 3, "box", "Track the task until done\n(even with Track Task off)"),
        ("c4", "conn", 4, "end", "Commit, unlock, log out;\nreturn the task outcome"),
    ],
    [
        ("c0", "f0", "lock", "r", "l"),
        ("c0", "c1", "", "b", "t"),
        ("c1", "f1", "exec", "r", "l"),
        ("f1", "t2", "", "b", "t"),
        ("c1", "c3", "wait", "b", "t"),
        ("t2", "c3", "state 4 / 5", "b", "r"),
        ("c3", "c4", "", "b", "t"),
    ],
    [(0, 720, 640, 90,
      "Before: the lock was released when the RPC returned.\n"
      "The task then failed 'no write permission' (install) or\n"
      "saved nothing (script) while the call still reported 0.")],
)

shared = overview_page(
    "Shared API key", "One API key = one FortiManager session: the connector serialises it",
    [
        ("n1", 0, 0, 260, 90, "conn", "FortiSOAR node 1", "playbook A, API key K"),
        ("n2", 0, 200, 260, 90, "conn", "FortiSOAR node 2", "playbook B, API key K"),
        ("pg", 380, 90, 280, 110, "db", "Primary's Postgres",
         "pg_try_advisory_lock(\nhash(FMG, key, ADOM))\nshared by every HA node"),
        ("fmg", 780, 90, 260, 110, "fmg", "FortiManager",
         "every request with K is\nONE session: either unlock\nreleases both"),
        ("ag", 0, 380, 260, 110, "none", "Remote agent",
         "no FortiSOAR DB: file lock,\nthis host only. Give each\nagent its own key"),
    ],
    [
        ("n1", "pg", "1. take key lock", "r", "lt"),
        ("n2", "pg", "waits", "r", "lb"),
        ("pg", "fmg", "2. holder works", "r", "l"),
        ("ag", "fmg", "", "r", "b"),
    ],
)

preview = page(
    "Install preview", "install/preview: three calls in one session",
    [("caller", "Playbook"), ("conn", "Connector (one session)"), ("fmg", "FortiManager")],
    [
        ("p0", "caller", 0, "start", "One install/preview\ncall"),
        ("c0", "conn", 0, "box", "1. install with\nflags=preview\n(pkg lock if a package)"),
        ("f0", "fmg", 0, "box", "Task builds the\npreview (writes\nnothing to the device)"),
        ("c1", "conn", 1, "box", "2. install/preview"),
        ("c2", "conn", 2, "box", "3. preview/result"),
        ("f2", "fmg", 2, "box", "Diff text\n(kept per session)"),
        ("p3", "caller", 3, "end", "special_case_response\n= the diff"),
    ],
    [
        ("p0", "c0", "", "r", "l"),
        ("c0", "f0", "", "r", "l"),
        ("c0", "c1", "task done", "b", "t"),
        ("c1", "c2", "", "b", "t"),
        ("c2", "f2", "", "r", "l"),
        ("f2", "p3", "", "b", "r"),
    ],
    [(0, 600, 640, 70,
      "Split across playbook steps, each step is a new session,\n"
      "so FortiManager always answers 'No preview result'.")],
)

pages = [decide, hold, shared, preview]
out = Path(__file__).with_name("connector_locking.drawio")
out.write_text(f'<mxfile host="build_diagram.py">{"".join(pages)}</mxfile>\n')
print("wrote", out)

sys.path.insert(0, str(Path(__file__).parent))
from check_drawio import main as _check  # noqa: E402
if _check(["check_drawio.py", str(out)]) != 0:
    sys.exit("build_diagram.py: check_drawio flagged problems; fix layout above.")
