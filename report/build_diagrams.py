"""Draw Figures 1-3 for the report with Pillow (already installed as a Streamlit dependency).

Figure 1  component architecture (module names are the real packages and files)
Figure 2  agent workflow, taken from the COMPILED LangGraph: the node and edge sets come from
          graph.get_graph(); only box positions and edge labels are hand-placed, and the script
          fails if the placement or labels disagree with the compiled graph
Figure 3  execution flow of one real hybrid question, drawn from its saved trace JSON
"""
from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "figures"
FONTS = Path("C:/Windows/Fonts")

NAVY, BLUE, GREEN, ORANGE, RED, GRAY, LIGHT = "#1f3a5f", "#dbe9fb", "#dff3e3", "#ffe6c7", "#f8d7da", "#e6e6e6", "#f7f7f7"
INK, MUTED = "#1a1a1a", "#555555"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(str(FONTS / ("arialbd.ttf" if bold else "arial.ttf")), size)


def text_size(d, text, f):
    box = d.textbbox((0, 0), text, font=f)
    return box[2] - box[0], box[3] - box[1]


def wrap(d, text, f, max_w):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = (cur + " " + word).strip()
            if text_size(d, trial, f)[0] <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def box(d, cx, cy, w, h, title, sub="", fill=BLUE, outline=NAVY, tf=None, sf=None, dashed=False):
    tf, sf = tf or font(26, True), sf or font(20)
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    d.rounded_rectangle((x0, y0, x1, y1), radius=14, fill=fill, outline=outline, width=3)
    lines = [(l, tf) for l in wrap(d, title, tf, w - 24)] + ([(l, sf) for l in wrap(d, sub, sf, w - 24)] if sub else [])
    total = sum(text_size(d, "Ag", f)[1] + 8 for _, f in lines)
    y = cy - total / 2
    for line, f in lines:
        tw, th = text_size(d, line, f)
        d.text((cx - tw / 2, y), line, font=f, fill=INK)
        y += th + 8
    return (x0, y0, x1, y1)


def arrow(d, pts, color=NAVY, width=3, dashed=False, head=14):
    for a, b in zip(pts[:-1], pts[1:]):
        if dashed:
            dx, dy = b[0] - a[0], b[1] - a[1]
            dist = math.hypot(dx, dy) or 1
            n = int(dist // 18)
            for i in range(0, n, 2):
                s, e = i / n, min((i + 1) / n, 1)
                d.line((a[0] + dx * s, a[1] + dy * s, a[0] + dx * e, a[1] + dy * e), fill=color, width=width)
        else:
            d.line((a, b), fill=color, width=width)
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    ang = math.atan2(y1 - y0, x1 - x0)
    p1 = (x1 - head * math.cos(ang - 0.4), y1 - head * math.sin(ang - 0.4))
    p2 = (x1 - head * math.cos(ang + 0.4), y1 - head * math.sin(ang + 0.4))
    d.polygon([(x1, y1), p1, p2], fill=color)


def label(d, xy, text, f=None, color=MUTED, bg="white"):
    f = f or font(19)
    w, h = text_size(d, text, f)
    x, y = xy
    d.rectangle((x - w / 2 - 4, y - h / 2 - 3, x + w / 2 + 4, y + h / 2 + 5), fill=bg)
    d.text((x - w / 2, y - h / 2 - 2), text, font=f, fill=color)


def edge_point(b, toward):
    """Point on a node's border in the direction of `toward` (b = x0, y0, x1, y1)."""
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == 0 and dy == 0:
        return cx, cy
    sx = (b[2] - b[0]) / 2 / abs(dx) if dx else 1e9
    sy = (b[3] - b[1]) / 2 / abs(dy) if dy else 1e9
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


# ------------------------------------------------------------------ Figure 1
def figure1() -> Path:
    W, H = 2340, 1420
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 24), "Hybrid Analyst: overall system architecture", font=font(40, True), fill=NAVY)

    def band(y0, y1, title):
        d.rounded_rectangle((30, y0, W - 30, y1), radius=22, fill=LIGHT, outline="#b9b9b9", width=2)
        d.text((52, y0 + 10), title, font=font(23, True), fill=MUTED)

    band(90, 330, "Presentation and external services")
    band(350, 600, "Agent core: LangGraph StateGraph (graph/). Nodes in typical order; exact paths per route are in Figure 2")
    band(620, 860, "Tools (tools/): called by the graph nodes above them")
    band(880, 1190, "Data and knowledge stores")
    band(1210, 1390, "Supporting modules")

    user = box(d, 260, 215, 300, 100, "User (browser)", "asks, approves or rejects", fill="white")
    ui = box(d, 760, 215, 400, 120, "Streamlit UI", "app.py, graph/ui_support.py", fill=BLUE)
    llm = box(d, 1900, 215, 620, 120, "LLM provider (external, free tier)", "Groq or Gemini (Ollama option untested), set in config.py", fill=GRAY)
    arrow(d, [(user[2], 215), (ui[0], 215)])

    names = [("router", "route + rewrite", BLUE), ("retrieve_docs", "policy search", GREEN), ("retrieve_schema", "tables + examples", GREEN),
             ("generate_sql", "writes SQLite", BLUE), ("validate_sql", "safety check", GREEN), ("approval", "human decides", ORANGE),
             ("execute_sql", "read-only run", GREEN), ("synthesize", "writes answer", BLUE)]
    bw, gap, x0 = 236, 40, 70
    cx = [x0 + bw / 2 + i * (bw + gap) for i in range(len(names))]
    nb = {}
    for (n, s, c), x in zip(names, cx):
        nb[n] = box(d, x, 480, bw, 110, n, s, fill=c, tf=font(25, True), sf=font(20))
    for a, b in zip(names[:-1], names[1:]):
        arrow(d, [(nb[a[0]][2], 480), (nb[b[0]][0], 480)])
    arrow(d, [(ui[0] + 40, ui[3]), (ui[0] + 40, 392), (cx[0], 392), (cx[0], nb["router"][1])])
    # the three LLM nodes share one bar, then a single arrow into the provider box
    bar_y = 306
    xs = [(nb[n][0] + nb[n][2]) / 2 + 70 for n in ("router", "generate_sql", "synthesize")]
    for x, n in zip(xs, ("router", "generate_sql", "synthesize")):
        d.line((x, nb[n][1], x, bar_y), fill="#7a7a7a", width=2)
    d.line((xs[0], bar_y, xs[-1], bar_y), fill="#7a7a7a", width=2)
    arrow(d, [(llm[0] + 310, bar_y), (llm[0] + 310, llm[3])], color="#7a7a7a", dashed=True, width=2)
    d.text((xs[1] - 60, bar_y + 6), "LLM calls", font=font(19), fill=MUTED)
    xa = (nb["approval"][0] + nb["approval"][2]) / 2
    arrow(d, [(xa, nb["approval"][1]), (xa, 238), (ui[2], 238)], color="#b25b00", dashed=True, width=2)
    d.text((ui[2] + 30, 205), "interrupt: Approve / Reject", font=font(19), fill="#b25b00")

    tools = [("retrieve_docs", "doc_retriever.py", "retrieve_docs(q, k=4,\nmin_score=0.30)"),
             ("retrieve_schema", "schema_search.py", "search_schema(q): top tables\n+ 2 similar example SQLs"),
             ("validate_sql", "sql_validator.py", "validate_sql(sql): one SELECT,\nallow-list, LIMIT, sensitive"),
             ("execute_sql", "sql_executor.py", "run_sql(sql): mode=ro,\n10 s timeout, row cap")]
    tb = {}
    for node, title, sub in tools:
        x = (nb[node][0] + nb[node][2]) / 2
        tb[node] = box(d, x, 745, 250, 150, title, sub, fill=GREEN, tf=font(23, True), sf=font(18))
        arrow(d, [(x, nb[node][3]), (x, tb[node][1])], color=MUTED)
    mem = box(d, cx[0], 745, 250, 150, "MemorySaver", "per-thread conversation\nmemory (checkpointer)", fill=GRAY, tf=font(23, True), sf=font(18))
    arrow(d, [(cx[0], nb["router"][3]), (cx[0], mem[1])], color=MUTED)
    trc = box(d, cx[7], 745, 250, 150, "trace writer", "graph/trace.py: one JSON\ntrace per question", fill=GRAY, tf=font(23, True), sf=font(18))
    arrow(d, [(cx[7], nb["synthesize"][3]), (cx[7], trc[1])], color=MUTED)

    xs_mid = (tb["retrieve_docs"][0] + tb["retrieve_schema"][2]) / 2
    chroma = box(d, xs_mid, 1030, 640, 190, "ChromaDB (chroma_db/)", "policy_docs: 6 documents, chunked\nschema_notes: tables + columns\nexample_queries: 12 question/SQL pairs", fill=BLUE, tf=font(25, True), sf=font(19))
    ex_x = (tb["execute_sql"][0] + tb["execute_sql"][2]) / 2
    sqlite = box(d, ex_x, 1030, 300, 190, "SQLite (data/olist.db)", "Olist e-commerce data,\n9 tables, read-only access", fill=BLUE, tf=font(25, True), sf=font(19))
    emb = box(d, (tb["validate_sql"][0] + tb["validate_sql"][2]) / 2 + 20, 1030, 290, 150, "sentence-transformers", "all-MiniLM-L6-v2, local CPU", fill=GREEN, tf=font(23, True), sf=font(18))
    for node in ("retrieve_docs", "retrieve_schema"):
        x = (tb[node][0] + tb[node][2]) / 2
        arrow(d, [(x, tb[node][3]), (x, chroma[1])], color=MUTED)
    arrow(d, [(ex_x, tb["execute_sql"][3]), (ex_x, sqlite[1])], color=MUTED)
    arrow(d, [(emb[0], 1030), (chroma[2], 1030)], color=MUTED)
    box(d, cx[7] + 6, 1030, 220, 120, "traces/", "JSON files", fill=GRAY, tf=font(23, True), sf=font(18))
    arrow(d, [(cx[7], trc[3]), (cx[7], 970)], color=MUTED)

    box(d, 330, 1300, 520, 110, "config.py + .env", "LLM / embedding choice, paths, limits; keys only in .env", fill=GRAY, tf=font(23, True), sf=font(18))
    box(d, 1000, 1300, 640, 110, "evaluation/", "30-question test set, baseline, report (runs the graph, writes results)", fill="white", tf=font(23, True), sf=font(18))
    box(d, 1780, 1300, 760, 110, "scripts/ + data/", "load_olist.py builds olist.db; policy documents, schema notes, example queries", fill="white", tf=font(23, True), sf=font(18))
    img.save(OUT / "fig1_architecture.png")
    return OUT / "fig1_architecture.png"


# ------------------------------------------------------------------ Figure 2
POS = {
    "__start__": (120, 470), "router": (360, 470), "out_of_scope": (360, 800),
    "retrieve_docs": (660, 250), "retrieve_schema": (940, 470), "generate_sql": (1220, 470),
    "validate_sql": (1500, 470), "approval": (1780, 250), "execute_sql": (1780, 690),
    "synthesize": (2060, 470), "fail": (1220, 960), "__end__": (2300, 470),
}
KIND = {"router": BLUE, "generate_sql": BLUE, "synthesize": BLUE, "retrieve_docs": GREEN, "retrieve_schema": GREEN,
        "validate_sql": GREEN, "execute_sql": GREEN, "approval": ORANGE, "out_of_scope": GRAY, "fail": RED}
LABELS = {
    ("router", "retrieve_schema"): "SQL", ("router", "retrieve_docs"): "DOCS or BOTH", ("router", "out_of_scope"): "OUT_OF_SCOPE",
    ("retrieve_docs", "retrieve_schema"): "BOTH", ("retrieve_docs", "synthesize"): "DOCS",
    ("validate_sql", "generate_sql"): "invalid SQL: retry (max 3)", ("validate_sql", "approval"): "sensitive columns",
    ("validate_sql", "execute_sql"): "valid", ("approval", "execute_sql"): "approved",
    ("execute_sql", "generate_sql"): "SQL error or 0 rows: retry", ("execute_sql", "synthesize"): "rows returned",
    ("approval", "fail"): "declined",
}


def compiled_graph():
    from graph.build_graph import build_graph
    from graph.nodes import Deps
    return build_graph(Deps(llm=None, docs_fn=None, schema_fn=None, run_fn=None)).get_graph()


def figure2() -> Path:
    g = compiled_graph()
    nodes = set(g.nodes)
    edges = {(e.source, e.target): e.conditional for e in g.edges}
    assert nodes == set(POS), f"layout out of date: {nodes ^ set(POS)}"
    missing = [k for k in LABELS if k not in edges]
    assert not missing, f"labels for edges that do not exist: {missing}"

    W, H = 2440, 1180
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 24), "Agent workflow: compiled LangGraph (nodes and edges read from graph.get_graph())", font=font(38, True), fill=NAVY)

    bx = {}
    for n, (x, y) in POS.items():
        if n in ("__start__", "__end__"):
            r = 52
            d.ellipse((x - r, y - r, x + r, y + r), fill=NAVY if n == "__start__" else "white", outline=NAVY, width=4)
            t = "START" if n == "__start__" else "END"
            f = font(22, True)
            tw, th = text_size(d, t, f)
            d.text((x - tw / 2, y - th / 2 - 3), t, font=f, fill="white" if n == "__start__" else NAVY)
            bx[n] = (x - r, y - r, x + r, y + r)
        else:
            bx[n] = box(d, x, y, 250, 86, n, fill=KIND[n])

    def ctr(n):
        b = bx[n]
        return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2

    def straight(s, t, **kw):
        a, b = edge_point(bx[s], ctr(t)), edge_point(bx[t], ctr(s))
        arrow(d, [a, b], **kw)
        return a, b

    for (s, t), cond in edges.items():
        kw = dict(dashed=cond, color=NAVY)
        if t == "fail":
            kw["color"] = "#b04a52"
            kw["dashed"] = True
            sx, sy = ctr(s)
            if s == "router":
                arrow(d, [(sx - 70, bx[s][3]), (sx - 70, 1000), (bx["fail"][0], 1000)], **kw)
            else:
                arrow(d, [edge_point(bx[s], ctr(t)), edge_point(bx[t], ctr(s))], width=2, **{k: v for k, v in kw.items() if k != "width"})
        elif (s, t) == ("retrieve_docs", "synthesize"):
            arrow(d, [(ctr(s)[0], bx[s][1]), (ctr(s)[0], 130), (ctr(t)[0], 130), (ctr(t)[0], bx[t][1])], **kw)
        elif (s, t) == ("validate_sql", "generate_sql"):
            arrow(d, [(ctr(s)[0] - 40, bx[s][3]), (ctr(s)[0] - 40, 600), (ctr(t)[0] + 40, 600), (ctr(t)[0] + 40, bx[t][3])], color="#b25b00", dashed=True)
        elif (s, t) == ("execute_sql", "generate_sql"):
            arrow(d, [(bx[s][0], ctr(s)[1]), (ctr(t)[0] - 40, ctr(s)[1]), (ctr(t)[0] - 40, bx[t][3])], color="#b25b00", dashed=True)
        elif t == "__end__" and s in ("out_of_scope", "fail"):
            yy = ctr(s)[1]
            arrow(d, [(bx[s][2], yy), (ctr(t)[0], yy), (ctr(t)[0], bx[t][3])], **kw)
        else:
            straight(s, t, **kw)

    # labels (positions chosen by hand, text keyed by real edges)
    where = {("router", "retrieve_schema"): (655, 440), ("router", "retrieve_docs"): (480, 330), ("router", "out_of_scope"): (440, 640),
             ("retrieve_docs", "retrieve_schema"): (830, 345), ("retrieve_docs", "synthesize"): (1360, 130),
             ("validate_sql", "generate_sql"): (1360, 625), ("validate_sql", "approval"): (1650, 335), ("validate_sql", "execute_sql"): (1620, 600),
             ("approval", "execute_sql"): (1780, 470), ("execute_sql", "generate_sql"): (1490, 745),
             ("execute_sql", "synthesize"): (1960, 600), ("approval", "fail"): (1400, 790)}
    for k, text in LABELS.items():
        label(d, where[k], text)
    label(d, (1220, 1042), "any node error, retries exhausted, or declined approval", color="#b04a52")

    # legend
    y = 1110
    for x, fill, text in [(60, BLUE, "LLM node"), (330, GREEN, "tool node"), (600, ORANGE, "human-in-the-loop"), (940, GRAY, "refusal"), (1200, RED, "failure")]:
        d.rounded_rectangle((x, y - 16, x + 44, y + 16), radius=6, fill=fill, outline=NAVY, width=2)
        d.text((x + 56, y - 14), text, font=font(22), fill=INK)
    arrow(d, [(1490, y), (1570, y)])
    d.text((1585, y - 14), "always", font=font(22), fill=INK)
    arrow(d, [(1730, y), (1810, y)], dashed=True)
    d.text((1825, y - 14), "conditional", font=font(22), fill=INK)
    img.save(OUT / "fig2_workflow.png")
    return OUT / "fig2_workflow.png"


# ------------------------------------------------------------------ Figure 3
def figure3() -> Path:
    path = sorted(glob.glob(str(ROOT / "evaluation" / "traces" / "hyb-01-*.json")))[0]
    tr = json.load(open(path, encoding="utf-8"))
    entries = tr["trace"]
    W, H = 2300, 980
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 24), "Execution of one real hybrid question (evaluation test hyb-01), step by step", font=font(38, True), fill=NAVY)
    d.text((40, 76), '"' + tr["question"] + '"', font=font(25), fill=MUTED)

    per_row, cw, ch = 5, 400, 250
    x0, y0, gapx, gapy = 150, 210, 440, 400
    centers = []
    for i, e in enumerate(entries):
        r, c = divmod(i, per_row)
        cx, cy = x0 + c * gapx + cw / 2 - 40, y0 + r * gapy + ch / 2
        centers.append((cx, cy))
        fill = RED if not e["success"] else ({"router": BLUE, "generate_sql": BLUE, "synthesize": BLUE}.get(e["node"], GREEN))
        b = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        d.rounded_rectangle(b, radius=14, fill=fill, outline=NAVY, width=3)
        d.text((b[0] + 18, b[1] + 14), f"{i + 1}. {e['node']}", font=font(28, True), fill=INK)
        meta = f"{e['duration_ms'] / 1000:.2f} s" if e["duration_ms"] >= 100 else f"{e['duration_ms']:.0f} ms"
        meta += f"   LLM calls: {e['llm_calls']}   {'ok' if e['success'] else 'FAILED'}"
        d.text((b[0] + 18, b[1] + 62), meta, font=font(21, True), fill=INK)
        summ = " ".join(e["summary"].split())
        for k, line in enumerate(wrap(d, summ, font(20), cw - 36)[:5]):
            d.text((b[0] + 18, b[1] + 104 + k * 28), line, font=font(20), fill=MUTED)
    for i in range(len(entries) - 1):
        (ax, ay), (bx_, by) = centers[i], centers[i + 1]
        if abs(ay - by) < 5:
            arrow(d, [(ax + cw / 2, ay), (bx_ - cw / 2, by)])
        else:  # wrap to the next row
            arrow(d, [(ax, ay + ch / 2), (ax, ay + ch / 2 + 70), (bx_, ay + ch / 2 + 70), (bx_, by - ch / 2)])
    fails = [i for i, e in enumerate(entries) if not e["success"]]
    if fails:
        note = ("Observe and repair: execute_sql failed (red), the error text is fed back into generate_sql, "
                "and the second attempt succeeds. This is the bounded retry loop (at most 3 retries).")
        d.rounded_rectangle((150, 880, 2200, 950), radius=12, fill="#fff4f4", outline="#b04a52", width=2)
        d.text((175, 898), note, font=font(24), fill=INK)
    img.save(OUT / "fig3_execution.png")
    return OUT / "fig3_execution.png"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in (figure1, figure2, figure3):
        print("wrote", fn())


if __name__ == "__main__":
    main()
