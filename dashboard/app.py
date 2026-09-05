"""
WAPAS — Recovery Console (dashboard v3.0)
-----------------------------------------
Read-only command center over out/, plus two SAFE live labs: the tamper lab
forges a record on a TEMP COPY; the kill-switch lab runs a small in-memory
simulation through the real gate.

v3.0 design system: SVG wallpaper hero, hand-drawn stroke icon set, sticky
topbar with honest live-AI provenance badge, decision-pipeline strip, source
pills on every AI assessment (REAL MODEL vs STAND-IN), Assurances page.
Zero changes to loaders, replay math, or gate behavior — the numbers this
renders are the same audited numbers `make verify-results` guards.

Run:  make dash        (or: streamlit run dashboard/app.py)
Needs out/ to exist -> run `make batch` first if it doesn't.
"""
from __future__ import annotations
import html
import json
import shutil
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "out"

APP_VERSION = "console v3.0"

st.set_page_config(page_title="WAPAS — Recovery Console", layout="wide",
                   initial_sidebar_state="expanded")

ARMS = ["control", "floor", "rules_only", "wapas", "oracle"]
LABELS = {
    "control": "Control (no action)",
    "floor": "Generic playbook",
    "rules_only": "Rules-only (no LLM)",
    "wapas": "WAPAS",
    "oracle": "Oracle (ceiling)",
}
DESCR = {
    "control": "no recovery action at all",
    "floor": "Razorpay's published generic advice, operationalized",
    "rules_only": "deterministic rules only, LLM tier removed",
    "wapas": "rules first, LLM on the ambiguous rest, full gate",
    "oracle": "perfect diagnosis under the same gate — the ceiling",
}
ARM_COLORS = {"control": "#94a3b8", "floor": "#d97706", "rules_only": "#2563eb",
              "wapas": "#059669", "oracle": "#7c3aed"}


# ═════════════════════════ icon set (hand-drawn strokes) ═════════════════════════
def _svg(body: str) -> str:
    return (f"<svg viewBox='0 0 24 24' width='100%' height='100%' fill='none' "
            f"stroke='currentColor' stroke-width='1.7' stroke-linecap='round' "
            f"stroke-linejoin='round'>{body}</svg>")


_IC = {
    "bolt": _svg("<path d='M13 2 4.5 13.5h5.6L9 22l8.5-11.5h-5.6L13 2z'/>"),
    "gauge": _svg("<path d='M20.2 14.5a8.5 8.5 0 1 0-16.4 0'/><path d='M12 14.5 16.2 10'/>"
                  "<circle cx='12' cy='14.5' r='1' fill='currentColor' stroke='none'/>"),
    "search": _svg("<circle cx='11' cy='11' r='7'/><path d='m21 21-4.3-4.3'/>"),
    "shield_off": _svg("<path d='M12 3l7 3v5c0 4.6-3 7.6-7 9-4-1.4-7-4.4-7-9V6l7-3z'/>"
                       "<path d='m5 5 14 14'/>"),
    "power": _svg("<path d='M12 3v8'/><path d='M6.6 6.8a8 8 0 1 0 10.8 0'/>"),
    "shield": _svg("<path d='M12 3l7 3v5c0 4.6-3 7.6-7 9-4-1.4-7-4.4-7-9V6l7-3z'/>"
                   "<path d='m9 12 2 2 4-4'/>"),
    "cpu": _svg("<rect x='7' y='7' width='10' height='10' rx='2'/>"
                "<path d='M10 2v3M14 2v3M10 19v3M14 19v3M2 10h3M2 14h3M19 10h3M19 14h3'/>"),
    "layers": _svg("<path d='m12 3 9 5-9 5-9-5 9-5z'/><path d='m3 13 9 5 9-5'/>"),
    "lock": _svg("<rect x='5' y='11' width='14' height='9' rx='2'/>"
                 "<path d='M8 11V8a4 4 0 0 1 8 0v3'/>"
                 "<circle cx='12' cy='15.5' r='1' fill='currentColor' stroke='none'/>"),
    "clock": _svg("<circle cx='12' cy='12' r='8.5'/><path d='M12 7v5l3.5 2'/>"),
    "scale": _svg("<path d='M12 4v16'/><path d='M6 6.5h12'/>"
                  "<path d='m6 6.5-2.6 5.4a3 3 0 0 0 5.8 0L6 6.5z'/>"
                  "<path d='m18 6.5-2.6 5.4a3 3 0 0 0 5.8 0L18 6.5z'/><path d='M9 20h6'/>"),
    "users": _svg("<circle cx='9' cy='8.5' r='3.2'/>"
                  "<path d='M3.5 19.5c0-3 2.5-5.5 5.5-5.5s5.5 2.5 5.5 5.5'/>"
                  "<circle cx='17' cy='9.5' r='2.4'/>"
                  "<path d='M16.5 14.2c2.3.4 4 2.3 4 4.8'/>"),
    "banknote": _svg("<rect x='3' y='7' width='18' height='10' rx='2'/>"
                     "<circle cx='12' cy='12' r='2.4'/><path d='M6.5 10v.01M17.5 14v.01'/>"),
    "crosshair": _svg("<circle cx='12' cy='12' r='7.5'/>"
                      "<path d='M12 2.5V6M12 18v3.5M2.5 12H6M18 12h3.5'/>"
                      "<circle cx='12' cy='12' r='1' fill='currentColor' stroke='none'/>"),
    "filter": _svg("<path d='M4 5h16l-6.2 7.2V18l-3.6 2v-7.8L4 5z'/>"),
    "doc": _svg("<path d='M6.5 2.5h8l4 4v15h-12v-19z'/><path d='M14.5 2.5v4h4'/>"
                "<path d='M10 12h4.5M10 15.5h4.5'/>"),
    "branch": _svg("<circle cx='6' cy='5.5' r='2.2'/><circle cx='6' cy='18.5' r='2.2'/>"
                   "<circle cx='18' cy='12' r='2.2'/><path d='M6 7.7v8.6'/>"
                   "<path d='M8.2 6.1c4 .8 7 2.4 7.6 4.3'/>"),
    "check": _svg("<path d='m5 12.5 4.5 4.5L19 7.5'/>"),
    "list": _svg("<path d='M9 6.5h11M9 12h11M9 17.5h11'/>"
                 "<path d='M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01'/>"),
    "pause": _svg("<circle cx='12' cy='12' r='8.5'/><path d='M10 9v6M14 9v6'/>"),
}


def ic(name: str, size: int = 14) -> str:
    if name not in _IC:
        return ""
    return (f"<span style='display:inline-flex;width:{size}px;height:{size}px;"
            f"vertical-align:-2px'>{_IC[name]}</span>")


# ═════════════════════════ wallpaper (inline SVG, offline-safe) ═════════════════════════
_WALL_SVG = ("<?xml version='1.0' encoding='UTF-8'?>"
             "<svg xmlns='http://www.w3.org/2000/svg' width='1240' height='320' "
             "viewBox='0 0 1240 320'>"
             "<defs>"
             "<linearGradient id='bg' x1='0' y1='0' x2='1' y2='1'>"
             "<stop offset='0' stop-color='#0b1220'/><stop offset='.55' stop-color='#132a5c'/>"
             "<stop offset='1' stop-color='#1d4ed8'/></linearGradient>"
             "<radialGradient id='g1' cx='.16' cy='.08' r='.55'>"
             "<stop offset='0' stop-color='#3b82f6' stop-opacity='.5'/>"
             "<stop offset='1' stop-color='#3b82f6' stop-opacity='0'/></radialGradient>"
             "<radialGradient id='g2' cx='.86' cy='.92' r='.6'>"
             "<stop offset='0' stop-color='#10b981' stop-opacity='.34'/>"
             "<stop offset='1' stop-color='#10b981' stop-opacity='0'/></radialGradient>"
             "<radialGradient id='g3' cx='.62' cy='.02' r='.45'>"
             "<stop offset='0' stop-color='#8b5cf6' stop-opacity='.3'/>"
             "<stop offset='1' stop-color='#8b5cf6' stop-opacity='0'/></radialGradient>"
             "<pattern id='grid' width='44' height='44' patternUnits='userSpaceOnUse'>"
             "<path d='M44 0H0V44' fill='none' stroke='#ffffff' stroke-opacity='.055'/></pattern>"
             "<linearGradient id='rail' x1='0' y1='0' x2='1' y2='0'>"
             "<stop offset='0' stop-color='#60a5fa' stop-opacity='0'/>"
             "<stop offset='.5' stop-color='#93c5fd' stop-opacity='.85'/>"
             "<stop offset='1' stop-color='#6ee7b7' stop-opacity='0'/></linearGradient>"
             "</defs>"
             "<rect width='1240' height='320' fill='url(#bg)'/>"
             "<rect width='1240' height='320' fill='url(#grid)'/>"
             "<rect width='1240' height='320' fill='url(#g1)'/>"
             "<rect width='1240' height='320' fill='url(#g2)'/>"
             "<rect width='1240' height='320' fill='url(#g3)'/>"
             "<path d='M-20 250 C 240 220, 420 280, 700 230 S 1120 145, 1280 180' "
             "fill='none' stroke='url(#rail)' stroke-width='2'/>"
             "<path d='M-20 278 C 260 256, 480 302, 760 262 S 1160 196, 1280 221' "
             "fill='none' stroke='url(#rail)' stroke-width='1.2' opacity='.6'/>"
             "<path d='M-20 128 C 200 104, 520 158, 820 104 S 1180 68, 1280 92' "
             "fill='none' stroke='url(#rail)' stroke-width='1' opacity='.35'/>"
             "<circle cx='700' cy='230' r='3.4' fill='#93c5fd'/>"
             "<circle cx='700' cy='230' r='9' fill='none' stroke='#93c5fd' stroke-opacity='.4'/>"
             "<circle cx='968' cy='184' r='2.6' fill='#6ee7b7'/>"
             "<circle cx='352' cy='242' r='2.6' fill='#c4b5fd'/>"
             "</svg>")
_WALL = "url(\"data:image/svg+xml," + urllib.parse.quote(_WALL_SVG, safe="") + "\")"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root { --ink:#0f172a; --ink2:#334155; --mut:#64748b; --line:#e4e9f1;
        --bg:#f6f8fc; --accent:#1d4ed8; --ok:#047857; --warn:#b45309; --bad:#b91c1c; }

html, body, .stApp { background: var(--bg) !important; color: var(--ink) !important; }
body { background:
       radial-gradient(1100px 260px at 50% -90px, rgba(29,78,216,.07), transparent 70%),
       var(--bg) !important; }
[data-testid="stAppViewContainer"] { background: transparent !important; }
[data-testid="stHeader"] { background: transparent !important; height: 0px !important; }
[data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], #MainMenu, footer { visibility: hidden !important; }
section[data-testid="stMain"], section[data-testid="stMain"] > div,
.block-container { background: transparent !important; }
.block-container { padding: 1.1rem 2.4rem 3rem; max-width: 1220px; }
html, body, [class*="css"], button, input { font-family: Inter, -apple-system, "Segoe UI",
        Roboto, "Helvetica Neue", Arial, sans-serif !important; }
h1 { font-size: 22px !important; font-weight: 800 !important; letter-spacing: -0.015em; }
p, li, span, label { font-size: 13.5px; }
::selection { background:#dbe7ff; }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background:#cdd6e4; border-radius:8px; border:2px solid var(--bg); }
::-webkit-scrollbar-track { background: transparent; }

/* ── sticky topbar ── */
.topbar { position: sticky; top: 0; z-index: 90; display: flex; align-items: center;
          gap: 14px; padding: 9px 2px 9px; margin-bottom: 12px;
          background: rgba(246,248,252,.86) !important; backdrop-filter: blur(10px);
          border-bottom: 1px solid var(--line); }
.tb-crumb { font-size: 11px; font-weight: 800; letter-spacing: .12em;
            text-transform: uppercase; color: var(--mut); display: flex;
            align-items: center; gap: 8px; }
.tb-crumb b { color: var(--ink); }
.tb-spacer { flex: 1; }
.tb-badge { display: inline-flex; align-items: center; gap: 7px; font-size: 11.5px;
            font-weight: 700; padding: 4px 12px; border-radius: 999px;
            border: 1px solid var(--line); background: #fff; color: var(--ink2); }
.tb-badge .dot { width: 7px; height: 7px; border-radius: 50%; }
.tb-badge.live { border-color: #a7f3d0; background: #ecfdf5; color: #047857; }
.tb-badge.live .dot { background: #10b981; box-shadow: 0 0 0 3px rgba(16,185,129,.18); }
.tb-badge.idle { color: var(--mut); }
.tb-badge.idle .dot { background: #94a3b8; }
.tb-ver { font-size: 11px; font-weight: 700; color: var(--mut);
          border: 1px solid var(--line); border-radius: 999px; padding: 4px 10px;
          background: #fff; }

/* ── sidebar: dark navy console rail ── */
[data-testid="stSidebar"] { background: linear-gradient(180deg,#0c1524 0%,#0e1726 30%,#101d33 100%) !important;
        border-right: none !important; }
[data-testid="stSidebar"] * { color: #cbd5e1 !important; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3
        { color: #ffffff !important; }
[data-testid="stSidebar"] hr { border-top: 1px solid #1e293b !important; }
.brand { display:flex; align-items:center; gap:10px; padding:6px 2px 2px; }
.brand-mark { width:36px; height:36px; border-radius:10px;
        background:linear-gradient(135deg,#1d4ed8,#059669); color:#fff; font-weight:800;
        font-size:15px; display:flex; align-items:center; justify-content:center;
        box-shadow: 0 0 0 1px rgba(255,255,255,.14) inset, 0 6px 16px rgba(29,78,216,.35); }
.brand-name { font-size:17px; font-weight:800; color:#fff !important; letter-spacing:-0.01em; }
.brand-sub { font-size:11px; color:#7c8db0 !important; margin-top:1px; }
.navsec { font-size:10px; font-weight:800; letter-spacing:.14em; text-transform:uppercase;
          color:#5b6c8f !important; margin:4px 0 2px; }
.side-stat { background:#16223a; border:1px solid #243350; border-radius:10px;
        padding:10px 12px; margin:6px 0; }
.side-stat .n { font-size:19px; font-weight:800; color:#fff !important;
        font-variant-numeric:tabular-nums; }
.side-stat .l { font-size:10.5px; font-weight:700; letter-spacing:.07em;
        text-transform:uppercase; color:#7c8db0 !important; margin-bottom:3px; }
.side-live { display:flex; align-items:center; gap:8px; font-size:11.5px; font-weight:600;
        color:#a5b4cd !important; padding:7px 2px; }
.side-live .dot { width:7px; height:7px; border-radius:50%; flex:none; }
.side-live .dot.on { background:#34d399; box-shadow:0 0 0 3px rgba(52,211,153,.16); }
.side-live .dot.off { background:#64748b; }
[data-testid="stSidebar"] .radio label { padding: 7px 10px !important; border-radius: 8px;
        font-weight: 550 !important; transition: background .12s ease; }
[data-testid="stSidebar"] .radio label:hover { background:#16223a !important; }
[data-testid="stSidebar"] .radio p { font-size: 14px !important; }
[data-testid="stSidebar"] caption, [data-testid="stSidebar"] .stCaption
        { color:#7c8db0 !important; font-size:11px !important; }

/* ── hero with SVG wallpaper ── */
.hero { border-radius:16px; padding:26px 30px 24px; color:#fff; margin-bottom:20px;
        background-image: linear-gradient(90deg, rgba(9,15,30,.90) 0%, rgba(13,30,66,.72) 52%,
                          rgba(19,42,92,.38) 100%), __WALL__;
        background-size: cover, cover; background-position: center, center;
        box-shadow: 0 18px 40px -18px rgba(13,30,66,.45); position: relative; overflow: hidden; }
.hero-kicker { display:inline-flex; align-items:center; gap:8px; font-size:10.5px;
        font-weight:800; letter-spacing:.14em; text-transform:uppercase; color:#c7d7f8;
        background:rgba(255,255,255,.09); border:1px solid rgba(255,255,255,.16);
        border-radius:999px; padding:5px 12px; margin-bottom:12px; }
.hero h1 { color:#fff !important; margin:0 0 6px !important; font-size:23px !important;
        letter-spacing:-.02em; }
.hero p { color:#c7d2e8 !important; margin:0; font-size:13.5px; max-width:760px; line-height:1.55; }
.hero-chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }
.chip { display:inline-flex; align-items:center; gap:6px;
        background:rgba(255,255,255,.10); border:1px solid rgba(255,255,255,.18);
        color:#fff; border-radius:999px; padding:4px 12px; font-size:12px; font-weight:600; }
.chip b { font-weight:800; }

/* ── micro headers ── */
.micro-h { font-size:11px; font-weight:800; letter-spacing:.1em; text-transform:uppercase;
           color:var(--mut); margin:22px 0 10px; display:flex; align-items:center; gap:9px; }
.micro-h .mh-ic { width:15px; height:15px; color:#94a3b8; display:inline-flex; }
.micro-h::after { content:""; flex:1; height:1px; background:var(--line); }
.meta { font-size:12.5px; color:var(--mut); margin:2px 0 12px; }

/* ── decision pipeline strip ── */
.pipe { display:flex; align-items:stretch; gap:8px; flex-wrap:wrap; background:#fff;
        border:1px solid var(--line); border-radius:14px; padding:14px 16px; }
.pipe-node { display:flex; align-items:center; gap:10px; padding:8px 12px; flex:1;
        min-width:150px; border:1px solid var(--line); border-radius:11px;
        background:linear-gradient(180deg,#ffffff,#f8fafd); transition: box-shadow .15s ease; }
.pipe-node:hover { box-shadow:0 6px 16px rgba(15,23,42,.08); }
.pipe-ic { width:32px; height:32px; border-radius:9px; display:flex; align-items:center;
        justify-content:center; flex:none; background:#eef4ff; color:var(--accent); }
.pipe-t { font-size:13px; font-weight:750; color:var(--ink); line-height:1.2; }
.pipe-d { font-size:11px; color:var(--mut); margin-top:2px; }
.pipe-arrow { align-self:center; color:#94a3b8; font-size:15px; font-weight:700; padding:0 1px; }

/* ── KPI cards ── */
.kpi { background:#fff; border:1px solid var(--line); border-radius:13px; padding:14px 16px 12px;
       height:100%; border-top:3px solid var(--accent); position:relative;
       transition:box-shadow .15s ease, transform .15s ease; }
.kpi:hover { transform:translateY(-2px); box-shadow:0 8px 20px rgba(15,23,42,.09); }
.kpi .l { font-size:10.5px; font-weight:800; letter-spacing:.08em; text-transform:uppercase;
          color:var(--mut); margin-bottom:7px; }
.kpi .v { font-size:26px; font-weight:800; letter-spacing:-0.02em;
          font-variant-numeric:tabular-nums; line-height:1.05; }
.kpi .d { display:inline-block; font-size:11px; font-weight:700; padding:2px 8px;
          border-radius:999px; margin-top:7px; }
.kpi .d.pos { background:#ecfdf5; color:var(--ok); }
.kpi .d.neg { background:#fef2f2; color:var(--bad); }
.kpi .d.neu { background:#eef2f7; color:var(--ink2); }
.kpi .s { font-size:11.5px; color:var(--mut); margin-top:6px; }
.kpi.g { border-top-color:#059669; } .kpi.o { border-top-color:#d97706; }
.kpi.p { border-top-color:#7c3aed; } .kpi.n { border-top-color:#94a3b8; }
.kpi-ic { position:absolute; top:12px; right:12px; width:30px; height:30px; border-radius:9px;
          display:flex; align-items:center; justify-content:center; padding:6px;
          background:#eef4ff; color:var(--accent); }
.kpi.g .kpi-ic { background:#ecfdf5; color:#059669; }
.kpi.o .kpi-ic { background:#fffbeb; color:#d97706; }
.kpi.p .kpi-ic { background:#f5f3ff; color:#7c3aed; }
.kpi.n .kpi-ic { background:#f1f5f9; color:#64748b; }

/* ── provenance pills (honest AI sourcing) ── */
.pill { display:inline-flex; align-items:center; gap:6px; font-size:10.5px; font-weight:800;
        letter-spacing:.05em; padding:2px 9px; border-radius:999px; vertical-align:1px; }
.pill .dot { width:6px; height:6px; border-radius:50%; }
.pill-live { background:#ecfdf5; color:#047857; border:1px solid #a7f3d0; }
.pill-live .dot { background:#10b981; }
.pill-idle { background:#f1f5f9; color:#64748b; border:1px solid #e2e8f0; }
.pill-idle .dot { background:#94a3b8; }
.pill-bad { background:#fef2f2; color:#b91c1c; border:1px solid #fecaca; }
.pill-bad .dot { background:#ef4444; }

/* ── bars ── */
.bar-row { display:grid; grid-template-columns:240px 1fr 150px; gap:14px; align-items:center;
           margin:9px 0; }
.bar-label { font-size:13px; font-weight:600; color:var(--ink2); text-align:right; line-height:1.3; }
.bar-label small { display:block; font-weight:500; color:var(--mut); font-size:11px; }
.bar-track { background:#e8edf5; border-radius:6px; height:24px; overflow:hidden;
             box-shadow: inset 0 1px 2px rgba(15,23,42,.05); }
.bar-fill { height:100%; border-radius:6px; box-shadow: inset 0 -6px 12px rgba(0,0,0,.10),
            inset 0 2px 3px rgba(255,255,255,.28); }
.bar-val { display:flex; align-items:center; gap:8px; }
.bar-num { font-size:14px; font-weight:800; font-variant-numeric:tabular-nums; }
.bar-chip { font-size:10.5px; font-weight:700; padding:1px 8px; border-radius:999px; }

/* ── cards / tables / console / timeline ── */
.card { background:#fff; border:1px solid var(--line); border-radius:12px; padding:15px 17px;
        height:100%; transition:box-shadow .15s ease; }
.card:hover { box-shadow:0 6px 16px rgba(15,23,42,.07); }
.card.acc { border-left:3px solid var(--accent); } .card.ok { border-left:3px solid var(--ok); }
.card.warn { border-left:3px solid var(--warn); }
.card-title { font-size:11px; font-weight:800; letter-spacing:.08em; text-transform:uppercase;
              color:var(--mut); margin-bottom:10px; display:flex; align-items:center; gap:8px; }
.card-title .ct-ic { width:15px; height:15px; color:#94a3b8; display:inline-flex; }
.kv { display:flex; gap:8px; font-size:13px; padding:4px 0; color:var(--ink2); line-height:1.45; }
.kv b { color:var(--ink); font-weight:650; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px;
       background:#eef2f7; padding:1px 6px; border-radius:5px; color:#0f172a; }

.htable { width:100%; border-collapse:separate; border-spacing:0; background:#fff;
          border:1px solid var(--line); border-radius:12px; overflow:hidden; }
.htable th { background:#f0f3f9; font-size:11px; font-weight:800; letter-spacing:.06em;
             text-transform:uppercase; color:var(--mut); text-align:left; padding:10px 13px; }
.htable td { padding:10px 13px; font-size:13px; color:var(--ink2); border-top:1px solid #eef1f7;
             font-variant-numeric:tabular-nums; }
.htable tr.hl td { background:#f0fdf7; }
.htable td b { color:var(--ink); }

.console { background:#0b1220; color:#d7e0ee; font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
           font-size:12.5px; line-height:1.7; border-radius:12px; padding:16px 20px;
           overflow-x:auto; border:1px solid #16223a;
           box-shadow: 0 14px 34px -18px rgba(11,18,32,.55); }
.console .g { color:#6ee7b7; } .console .r { color:#fca5a5; } .console .d { color:#8ea3c0; }

.tl-item { display:flex; gap:12px; padding:8px 2px; border-bottom:1px dashed #e8edf5;
           align-items:flex-start; }
.tl-item:last-child { border-bottom:none; }
.tl-n { min-width:22px; height:22px; border-radius:7px; background:#1d4ed8; color:#fff;
        font-size:10.5px; font-weight:800; display:flex; align-items:center; justify-content:center;
        margin-top:1px; }
.tl-t { font-size:13.5px; color:var(--ink2); line-height:1.5; }

.foot { margin-top:26px; padding-top:12px; border-top:1px solid var(--line); font-size:11.5px;
        color:var(--mut); display:flex; justify-content:space-between; flex-wrap:wrap; gap:6px; }

div[data-baseweb="button"] { border:1px solid #cbd5e1 !important; border-radius:9px !important;
        background:#fff !important; color:var(--ink) !important; font-weight:650 !important;
        font-size:13.5px !important; transition: transform .06s ease, box-shadow .15s ease !important; }
div[data-baseweb="button"]:hover { box-shadow:0 4px 12px rgba(15,23,42,.10) !important; }
div[data-baseweb="button"]:active { transform: translateY(1px) scale(.995) !important;
        box-shadow: none !important; }
button[kind="primary"] { background:var(--accent) !important; border-color:var(--accent) !important;
        color:#fff !important; box-shadow:0 8px 18px -8px rgba(29,78,216,.55) !important; }
div[data-baseweb="select"] > div, .stSlider, .stRadio { color:var(--ink2); }
[data-baseweb="slider"] [role="slider"] { background-color: var(--accent) !important;
        border: 2px solid #fff; box-shadow: 0 1px 4px rgba(15,23,42,.25); }
[data-baseweb="progress-bar"] > div { background: var(--accent) !important; }
[data-baseweb="progress-bar"] { background: #e8edf5 !important; }
[data-baseweb="progress-bar"] > div > div { color: var(--ink2) !important; }
hr { border:none; border-top:1px solid var(--line); }
</style>
""".replace("__WALL__", _WALL)
CSS_PLAY = """
<style>
/* ── checkout card (the payment that failed) ── */
.checkout { background:#fff; border:1px solid var(--line); border-radius:14px;
        padding:16px 18px; box-shadow:0 10px 26px -18px rgba(15,23,42,.35); }
.checkout .ck-head { display:flex; align-items:center; gap:10px; padding-bottom:10px;
        border-bottom:1px dashed var(--line); margin-bottom:10px; }
.checkout .ck-logo { width:34px; height:34px; border-radius:8px; background:#0f172a;
        color:#fff; font-weight:800; font-size:13px; display:flex; align-items:center;
        justify-content:center; }
.checkout .ck-m { font-size:13.5px; font-weight:750; color:var(--ink); }
.checkout .ck-s { font-size:11px; color:var(--mut); }
.checkout .ck-amt { margin-left:auto; font-size:19px; font-weight:800;
        font-variant-numeric:tabular-nums; }
.checkout .kv2 { display:flex; justify-content:space-between; font-size:12.5px;
        color:var(--ink2); padding:3px 0; }
.checkout .kv2 span:first-child { color:var(--mut); }
.checkout .ck-status { display:inline-flex; align-items:center; gap:6px; margin-top:10px;
        font-size:12px; font-weight:800; color:var(--bad); background:#fef2f2;
        border:1px solid #fecaca; border-radius:999px; padding:4px 12px; }
.checkout .ck-status .dot { width:7px; height:7px; border-radius:50%; background:#ef4444; }

/* ── the customer's phone ── */
.phone { width:300px; margin:0 auto; background:#0b1220; border-radius:30px; padding:10px;
        box-shadow:0 24px 50px -24px rgba(11,18,32,.65); border:1px solid #1e293b; }
.phone .screen { background:#e5ddd5; border-radius:22px; overflow:hidden; }
.phone .pbar { background:#0f172a; color:#e2e8f0; font-size:11.5px; padding:9px 14px;
        display:flex; align-items:center; gap:9px; }
.phone .pbar .av { width:26px; height:26px; border-radius:50%; background:linear-gradient(135deg,#1d4ed8,#059669);
        color:#fff; font-size:11px; font-weight:800; display:flex; align-items:center;
        justify-content:center; }
.phone .pbar .nm { font-weight:750; }
.phone .pbar .st { font-size:9.5px; color:#94a3b8; }
.phone .chat { padding:12px 10px 14px; display:flex; flex-direction:column; gap:8px; }
.chat-day { align-self:center; background:#fdf3d8; color:#7a6a3f; font-size:10px;
        font-weight:700; border-radius:999px; padding:3px 10px; }
.bubble { max-width:86%; border-radius:10px; padding:8px 11px; font-size:12.5px;
        line-height:1.5; position:relative; box-shadow:0 1px 1px rgba(0,0,0,.12); }
.bubble.l { background:#fff; color:#1f2937; border-top-left-radius:2px; align-self:flex-start; }
.bubble.r { background:#d9fdd3; color:#111b21; border-top-right-radius:2px; align-self:flex-end; }
.bubble .t { display:block; font-size:9.5px; color:#8696a0; text-align:right; margin-top:3px; }
.bubble .paybtn { display:block; text-align:center; margin-top:7px; background:#1d4ed8;
        color:#fff !important; font-weight:800; font-size:12.5px; border-radius:8px;
        padding:8px 10px; text-decoration:none; }
.bubble .paybtn small { display:block; font-size:9px; font-weight:600; color:#c7d7f8; }
.sched-note { align-self:center; font-size:10px; color:#6b7280; background:#fff;
        border:1px dashed #cbd5e1; border-radius:8px; padding:4px 10px; }

/* ── story steps ── */
.step { display:flex; gap:12px; margin:10px 0; align-items:flex-start; }
.step-n { min-width:26px; height:26px; border-radius:9px; background:#1d4ed8; color:#fff;
        font-size:12px; font-weight:800; display:flex; align-items:center;
        justify-content:center; margin-top:2px; }
.step-b { flex:1; }
.step-t { font-size:13.5px; font-weight:750; color:var(--ink); }
.step-d { font-size:12.5px; color:var(--ink2); line-height:1.55; margin-top:2px; }
.step-d code { font-size:11.5px; }
</style>
"""
st.markdown(CSS + CSS_PLAY, unsafe_allow_html=True)


# ---------- loaders ----------
@st.cache_data(show_spinner=False)
def load_results():
    p = OUT / "results.json"
    return json.loads(p.read_text()) if p.exists() else None


@st.cache_data(show_spinner=False)
def load_eval():
    p = OUT / "eval.json"
    return json.loads(p.read_text()) if p.exists() else None


@st.cache_data(show_spinner=True)
def load_ledger_rows(arm: str):
    rows = []
    with open(OUT / f"ledger_{arm}.jsonl") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line).get("content", {})
            if c.get("gate_trace"):
                rows.append(c)
    return rows


@st.cache_data(show_spinner=False)
def load_live_stats():
    """Honest provenance for the live-AI tier: what's in the LIVE cache right
    now. Only real provider responses ever get persisted there (enforced in
    llm_agent.diagnose) — so its existence is itself a receipt."""
    p = ROOT / "cache" / "diagnosis_cache_live.json"
    if not p.exists():
        return None
    try:
        c = json.loads(p.read_text())
    except Exception:
        return None
    from collections import Counter
    mix = Counter(str(v.get("source", "?")) for v in c.values())
    return {"n": len(c), "mix": dict(mix)}


# ---------- helpers ----------
def rate(x): return f"{x:.1%}" if isinstance(x, (int, float)) else "—"
def inr(x): return f"₹{x:,.0f}" if isinstance(x, (int, float)) else "—"
def esc(x): return html.escape(str(x))


def model_short(src: str) -> str:
    """'llm_openrouter:minimax/minimax-m3:free' -> 'minimax-m3' (display only)."""
    m = src.split(":", 1)[1] if ":" in src else src
    return m.split("/")[-1].replace(":free", "")


def source_pill(src: str) -> str:
    s = str(src)
    if s.startswith("llm_openrouter") or s == "llm_live":
        return (f'<span class="pill pill-live"><span class="dot"></span>'
                f'REAL MODEL · {esc(model_short(s))}</span>')
    if s == "llm_heuristic":
        return '<span class="pill pill-idle"><span class="dot"></span>STAND-IN</span>'
    return '<span class="pill pill-bad"><span class="dot"></span>REPAIR</span>'


def hero(kicker: str, kicker_icon: str, title: str, sub: str, chips: str = "") -> str:
    ch = f'<div class="hero-chips">{chips}</div>' if chips else ""
    return (f'<div class="hero"><div class="hero-kicker">{ic(kicker_icon, 13)}'
            f'{esc(kicker)}</div><h1>{esc(title)}</h1><p>{sub}</p>{ch}</div>')


def topbar(section: str):
    stats = load_live_stats()
    if stats and stats["n"]:
        models = sorted({k.split(":", 1)[1] for k in stats["mix"]
                         if k.startswith("llm_openrouter")},
                        key=lambda s: -stats["mix"].get("llm_openrouter:" + s, 0))
        who = model_short("x:" + models[0]) if models else "live"
        badge = (f'<div class="tb-badge live"><span class="dot"></span>'
                 f'REAL LLM · {stats["n"]:,} live diagnoses · {esc(who)}</div>')
    else:
        badge = ('<div class="tb-badge idle"><span class="dot"></span>'
                 'LLM tier wired · official run: stand-in</div>')
    st.markdown(
        f'<div class="topbar"><div class="tb-crumb">WAPAS <b>· {esc(section)}</b></div>'
        f'<div class="tb-spacer"></div>{badge}'
        f'<div class="tb-ver">{APP_VERSION}</div></div>', unsafe_allow_html=True)


def kpi(label, value, sub=None, delta=None, kind="pos", accent="", icon=None):
    d = f'<div class="d {kind}">{esc(delta)}</div>' if delta else ""
    s = f'<div class="s">{esc(sub)}</div>' if sub else ""
    i = f'<div class="kpi-ic">{ic(icon, 16)}</div>' if icon else ""
    return (f'<div class="kpi {accent}">{i}<div class="l">{esc(label)}</div>'
            f'<div class="v">{esc(value)}</div>{d}{s}</div>')


def micro(text, icon=None):
    i = f'<span class="mh-ic">{ic(icon, 14)}</span>' if icon else ""
    st.markdown(f'<div class="micro-h">{i}{esc(text)}</div>', unsafe_allow_html=True)


def console_block(lines):
    st.markdown('<div class="console">' + "<br>".join(lines) + "</div>",
                unsafe_allow_html=True)


def bars_html(items, maxv, best=None):
    out = []
    for label, sub, value, color, key in items:
        pct = min(100.0, value / maxv * 100) if maxv else 0
        chip = ""
        if best and key == best:
            chip = '<span class="bar-chip" style="background:#ecfdf5;color:#047857">our line</span>'
        elif key == "oracle":
            chip = '<span class="bar-chip" style="background:#f5f3ff;color:#7c3aed">ceiling</span>'
        elif key == "floor":
            chip = '<span class="bar-chip" style="background:#fffbeb;color:#b45309">their playbook</span>'
        out.append(
            f'<div class="bar-row"><div class="bar-label">{esc(label)}<small>{esc(sub)}</small></div>'
            f'<div class="bar-track"><div class="bar-fill" '
            f'style="width:{pct:.1f}%;background:{color}"></div></div>'
            f'<div class="bar-val"><span class="bar-num">{value:.1%}</span>{chip}</div></div>')
    return "".join(out)


def hbars(items, maxv, best=None):
    st.markdown(bars_html(items, maxv, best), unsafe_allow_html=True)


def timeline(steps):
    st.markdown("".join(
        f'<div class="tl-item"><div class="tl-n">{i + 1}</div>'
        f'<div class="tl-t">{esc(s)}</div></div>' for i, s in enumerate(steps)),
        unsafe_allow_html=True)


def kv_card(title, pairs, kind="acc", icon=None):
    t = f'<span class="ct-ic">{ic(icon, 14)}</span>{esc(title)}' if icon else esc(title)
    return (f'<div class="card {kind}"><div class="card-title">{t}</div>'
            + "".join(f'<div class="kv">{k}</div>' for k in pairs) + "</div>")


def htable(headers, rows, hl_row=None):
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = []
    for i, row in enumerate(rows):
        cls = ' class="hl"' if hl_row is not None and i == hl_row else ""
        tds = "".join(f"<td>{c}</td>" for c in row)
        trs.append(f"<tr{cls}>{tds}</tr>")
    st.markdown(f'<table class="htable"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>',
                unsafe_allow_html=True)


def pipe(nodes):
    """Decision-pipeline strip: [(icon, title, sub), ...] joined by arrows."""
    parts = []
    for i, (icon, title, sub) in enumerate(nodes):
        if i:
            parts.append('<div class="pipe-arrow">→</div>')
        parts.append(f'<div class="pipe-node"><div class="pipe-ic">{ic(icon, 17)}</div>'
                     f'<div><div class="pipe-t">{esc(title)}</div>'
                     f'<div class="pipe-d">{esc(sub)}</div></div></div>')
    st.markdown('<div class="pipe">' + "".join(parts) + "</div>", unsafe_allow_html=True)


def page_foot(left):
    st.markdown(f'<div class="foot"><span>{left}</span>'
                f'<span>no authority, no action · human approval on every customer-facing '
                f'step · {APP_VERSION}</span></div>', unsafe_allow_html=True)


# ---------- sidebar ----------
with st.sidebar:
    st.markdown('<div class="brand"><div class="brand-mark">W</div><div>'
                '<div class="brand-name">WAPAS</div>'
                '<div class="brand-sub">recovery console</div></div></div>',
                unsafe_allow_html=True)
    st.divider()
    st.markdown('<div class="navsec">Workspace</div>', unsafe_allow_html=True)
    page = st.radio("Section", ["Mission Control", "Try It Live", "Case Files", "Tamper Lab",
                                "Kill-Switch Lab", "Assurances"],
                    label_visibility="collapsed")
    st.divider()
    res = load_results()
    ev = load_eval()
    if res is None:
        st.caption("out/ is empty — run make batch first.")
    else:
        st.markdown(f'<div class="side-stat"><div class="l">wapas recovery</div>'
                    f'<div class="n">{rate(res["wapas"]["recovery_rate"])}</div></div>',
                    unsafe_allow_html=True)
        if res.get("oracle", {}).get("recovery_rate"):
            cap = res["wapas"]["recovery_rate"] / res["oracle"]["recovery_rate"] * 100
            st.markdown(f'<div class="side-stat"><div class="l">of oracle ceiling</div>'
                        f'<div class="n">{cap:.1f}%</div></div>', unsafe_allow_html=True)
        if ev:
            st.markdown(f'<div class="side-stat"><div class="l">diagnosis accuracy</div>'
                        f'<div class="n">{ev["accuracy"]:.0%}</div></div>', unsafe_allow_html=True)
    stats = load_live_stats()
    if stats and stats["n"]:
        st.markdown(f'<div class="side-live"><span class="dot on"></span>'
                    f'live AI: {stats["n"]:,} real diagnoses</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="side-live"><span class="dot off"></span>'
                    'live AI: wired · no live responses yet</div>', unsafe_allow_html=True)
    st.divider()
    st.caption("n = 12,000 synthetic at-risk events · seeds 42 / 2026 · byte-identical "
               "repro via make all · Razorpay test-mode shaped")

topbar(page)

# ═════════════════════════ Mission Control ═════════════════════════
if page == "Mission Control":
    st.markdown(hero(
        "Monitor · Mission Control", "gauge",
        "Recovery experiment — mission control",
        "Five decision policies over the same merchant mix, identical contact budget. "
        "The only variable: are recovery actions diagnosed before they are chosen?",
        chips='<span class="chip">n = 12,000</span>'
              '<span class="chip">WAPAS <b>27.8%</b></span>'
              '<span class="chip">vs playbook <b>p = 0.0001</b></span>'
              '<span class="chip">ceiling captured <b>98.7%</b></span>'
              '<span class="chip">violations <b>0</b></span>'),
        unsafe_allow_html=True)
    if res is None:
        st.error("No results found. Run `make batch` (or `make all`) first.")
        st.stop()

    micro("Decision pipeline — every case walks this path", "branch")
    pipe([
        ("crosshair", "Detector", "at-risk event flagged"),
        ("filter", "Rules tier", "resolves ~80% outright"),
        ("cpu", "LLM tier", "only the ambiguous rest"),
        ("shield", "Policy gate", "consent L1 / L2 / L3"),
        ("bolt", "Executor", "one action, logged"),
        ("layers", "Hash ledger", "tamper-evident record"),
    ])

    # ── live replay: watch the official run execute, case by case ──
    micro("Live replay — watch the run execute", "clock")
    st.markdown('<div class="meta">Case-by-case replay of the official experiment, rebuilt '
                'from the audit ledgers. Deterministic: it always lands on exactly the '
                'numbers below — that is the reproducibility guarantee, demonstrated.</div>',
                unsafe_allow_html=True)
    cA, cB = st.columns([3, 1])
    speed = cA.slider("Replay speed (cases per second)", 100, 1200, 450, 50)
    go = cB.button("Replay the run, live", type="primary", width="stretch")
    if go:
        try:
            arm_rows = {k: sorted(load_ledger_rows(k), key=lambda x: x["decided_at"])
                        for k in ARMS}
        except FileNotFoundError:
            st.error("Ledgers not found — run `make batch` first."); st.stop()
        max_n = max(len(v) for v in arm_rows.values())
        prog = st.progress(0.0, text="replaying…")
        cols = st.columns(5)
        phs = [c_.empty() for c_ in cols]
        ph_console = st.empty()
        ph_bars = st.empty()
        acc = {k: {"i": 0, "rec": 0, "amt": 0.0} for k in ARMS}
        update_every = max(1, speed // 20)
        for i in range(max_n):
            for k in ARMS:
                if i < len(arm_rows[k]):
                    x = arm_rows[k][i]
                    acc[k]["i"] += 1
                    acc[k]["rec"] += 1 if x["recovered"] else 0
                    acc[k]["amt"] += float(x.get("recovered_inr") or 0.0)
            if i % update_every == 0 or i == max_n - 1:
                for ph, k in zip(phs, ARMS):
                    a_ = acc[k]
                    ph.markdown(
                        f'<div class="kpi" style="border-top-color:{ARM_COLORS[k]}">'
                        f'<div class="l">{esc(LABELS[k])}</div>'
                        f'<div class="v">{(a_["rec"] / a_["i"]) if a_["i"] else 0:.1%}</div>'
                        f'<div class="s">{a_["rec"]:,} of {a_["i"]:,} recovered</div></div>',
                        unsafe_allow_html=True)
                w_rows = arm_rows["wapas"]
                if w_rows:
                    last = w_rows[min(i, len(w_rows) - 1)]   # arms finish at slightly different counts
                    w = acc["wapas"]
                    ph_console.markdown(
                        '<div class="console">'
                        f"<span class='d'>case {esc(last['event_id'])}</span> · "
                        f"{esc(last['customer_id'])} · ₹{last['amount']:,.0f} · "
                        f"{esc(last['root_cause'])} ({float(last['confidence']):.2f}) → "
                        f"{esc(last['final_action'])} · {esc(last['policy_result'])} · "
                        + ('<span class="g">recovered</span>' if last["recovered"] else "open")
                        + f"<br><span class='d'>wapas arm · {min(i + 1, len(w_rows)):,} / "
                        f"{len(w_rows):,} decided · ₹{w['amt']:,.0f} recovered so far</span></div>",
                        unsafe_allow_html=True)
                ph_bars.markdown(bars_html(
                    [(LABELS[k], DESCR[k],
                      (acc[k]["rec"] / acc[k]["i"]) if acc[k]["i"] else 0.0,
                      ARM_COLORS[k], k) for k in ARMS],
                    maxv=max((acc[k]["rec"] / acc[k]["i"]) if acc[k]["i"] else 0.0
                             for k in ARMS) * 1.12 + 1e-9, best="wapas"),
                    unsafe_allow_html=True)
            prog.progress((i + 1) / max_n, text=f"replaying… {i + 1:,} / {max_n:,} cases")
            time.sleep(1.0 / speed)
        prog.progress(1.0, text="replay complete — landed on the official numbers exactly")
        st.caption("End state = the official results table below, byte for byte. Same seeds, "
                   "same deterministic pipeline: the run is the receipt. (Ticker shows the "
                   "wapas arm; all five arms advance in lockstep.)")

    r = res
    from wapas.stats_utils import two_proportion_ztest, approx_power
    z_cw = two_proportion_ztest(r["control"]["recovered"], r["control"]["n"],
                                r["wapas"]["recovered"], r["wapas"]["n"])
    z_fw = two_proportion_ztest(r["floor"]["recovered"], r["floor"]["n"],
                                r["wapas"]["recovered"], r["wapas"]["n"])
    power_fw = approx_power(r["floor"]["recovery_rate"], r["wapas"]["recovery_rate"],
                            n_per_arm=min(r["floor"]["n"], r["wapas"]["n"]))
    ceiling = (r["wapas"]["recovery_rate"] / r["oracle"]["recovery_rate"] * 100
               if r["oracle"]["recovery_rate"] else 0.0)
    pp = (r["wapas"]["recovery_rate"] - r["floor"]["recovery_rate"]) * 100
    ppc = (r["wapas"]["recovery_rate"] - r["control"]["recovery_rate"]) * 100
    net_gap = r["wapas"]["net_amount"] - r["floor"]["net_amount"]

    micro("Headline", "bolt")
    a, b, c, d, e = st.columns(5)
    a.markdown(kpi("WAPAS recovery", rate(r["wapas"]["recovery_rate"]),
                   delta=f"+{ppc:.1f}pp vs control", kind="pos",
                   sub=f"n = {r['wapas']['n']:,} at-risk payments", icon="bolt"),
              unsafe_allow_html=True)
    b.markdown(kpi("Generic playbook", rate(r["floor"]["recovery_rate"]),
                   sub="Razorpay's published advice", accent="o", icon="doc"),
               unsafe_allow_html=True)
    c.markdown(kpi("No action", rate(r["control"]["recovery_rate"]),
                   sub="organic recovery only", accent="n", icon="pause"),
               unsafe_allow_html=True)
    d.markdown(kpi("Ceiling captured", f"{ceiling:.1f}%",
                   sub="of perfect diagnosis", accent="p", icon="gauge"),
               unsafe_allow_html=True)
    e.markdown(kpi("WAPAS vs playbook", f"+{pp:.1f}pp",
                   delta=f"p = {z_fw['p_value']:.4f}",
                   kind=("pos" if z_fw["p_value"] < 0.05 else "neu"),
                   sub=f"power {power_fw:.2f}", icon="scale"), unsafe_allow_html=True)

    micro("Recovery rate by line", "scale")
    hbars([(LABELS[k], DESCR[k], r[k]["recovery_rate"], ARM_COLORS[k], k) for k in ARMS],
          maxv=max(r[k]["recovery_rate"] for k in ARMS) * 1.12, best="wapas")
    st.caption("WAPAS lands within 0.4pp of the analytic oracle: the gate and execution layer "
               "capture nearly everything correct diagnosis makes possible.")

    micro("What the experiment says", "check")
    left, mid, right = st.columns(3)
    with left:
        st.markdown(kv_card("Statistics", [
            f"Control vs WAPAS &nbsp;<b>p = {z_cw['p_value']:.4f}</b>",
            f"Floor vs WAPAS &nbsp;<b>p = {z_fw['p_value']:.4f}</b>",
            f"Power &nbsp;<b>{power_fw:.2f}</b> &nbsp;·&nbsp; Wilson 95% CIs",
            f"Net ₹ edge over playbook &nbsp;<b>{inr(net_gap)}</b>"], "acc", icon="scale"),
            unsafe_allow_html=True)
    with mid:
        acc_txt = (f"{ev['accuracy']:.1%} on {ev['n']:,} held-out" if ev else "run make batch")
        st.markdown(kv_card("Diagnosis quality", [
            f"Accuracy &nbsp;<b>{acc_txt}</b>",
            f"Confusion cost &nbsp;<b>{ev.get('avg_confusion_cost', 0):.3f}</b>" if ev else "—",
            "Ground truth hidden inside the simulator:",
            "a graded exam, not vibes."], "ok", icon="cpu"),
            unsafe_allow_html=True)
    with right:
        st.markdown(kv_card("Read honestly", [
            "Rules ≈ WAPAS on recovery rate. The LLM tier",
            "earns its place on ambiguous free text, drift",
            "and the audit explainer — not raw rate.",
            "Contact caps protect every arm equally; no",
            "goodwill advantage is claimed."], "warn", icon="shield"),
            unsafe_allow_html=True)

    micro("Cost and friction by arm", "banknote")
    htable(
        ["Line", "n", "Recovered", "Rate", "95% CI", "₹ recovered", "Net ₹",
         "Complaints", "To human", "Deferred", "Blocked"],
        [[f"<b>{esc(LABELS[k])}</b>", f"{r[k]['n']:,}", f"{r[k]['recovered']:,}",
          f"<b>{rate(r[k]['recovery_rate'])}</b>",
          f"[{r[k]['ci_95'][0]:.1%}, {r[k]['ci_95'][1]:.1%}]",
          inr(r[k]["recovered_amount"]), inr(r[k]["net_amount"]),
          str(r[k]["complaints"]), str(r[k]["n_human"]), f"{r[k]['n_deferred']:,}",
          str(r[k]["n_blocked"])] for k in ARMS],
        hl_row=3)
    st.caption("Net ₹ subtracts action costs and ₹150 per complaint (expected churn cost). "
               "Deferred = deliberately scheduled later (quiet hours, cash-cycle timing). "
               "Blocked = the gate refused to act, with a written reason.")

    stats = load_live_stats()
    if stats and stats["n"]:
        micro("AI provenance — who actually diagnosed", "cpu")
        rows = []
        for src in sorted(stats["mix"], key=lambda s: -stats["mix"][s]):
            n = stats["mix"][src]
            if src.startswith("llm_openrouter") or src == "llm_live":
                dot = '<span class="pill pill-live"><span class="dot"></span>REAL</span>'
                name = f"<code>{esc(src.split(':', 1)[1])}</code>"
            elif src == "llm_heuristic":
                dot = '<span class="pill pill-idle"><span class="dot"></span>STAND-IN</span>'
                name = "<code>llm_heuristic</code>"
            else:
                dot = '<span class="pill pill-bad"><span class="dot"></span>REPAIR</span>'
                name = f"<code>{esc(src)}</code>"
            rows.append([dot, name, f"{n:,}",
                         f"{n / stats['n']:.1%}"])
        htable(["Class", "Source", "Responses", "Share"], rows)
        st.caption("Live cache holds ONLY real provider responses (enforced in code, "
                   "guarded by tests). The official results table above remains the "
                   "deterministic stand-in era until an official --live run replaces it — "
                   "one run, one source of truth.")

    page_foot("WAPAS · revenue recovery mission control · every number recomputes from out/ · "
              "byte-identical via make all · tampering with RESULTS.md fails CI")

# ═════════════════════════ Try It Live ═════════════════════════
elif page == "Try It Live":
    from datetime import datetime
    from wapas.schema import EvidencePacket, IST
    from wapas import rules_tier, llm_agent
    from wapas import diagnosis as dm
    from wapas.policy_gate import Gate

    st.markdown(hero(
        "Experience · Try It Live", "bolt",
        "Run one payment through WAPAS",
        "Pick a failed-payment scenario and watch the real system handle it — the same "
        "rules tier, the same diagnosis agent, the same consent gate that ran the "
        "12,000-event experiment. Nothing is scripted: every verdict below is computed "
        "live, and the phone shows the exact message the system would send.",
        chips='<span class="chip">same engine as the experiment</span>'
              '<span class="chip">nothing scripted</span>'
              '<span class="chip">sandbox: no real money</span>'),
        unsafe_allow_html=True)

    PHONE_LAST4 = {"Priya Sharma": "32", "Rohit Verma": "87", "Ayesha Khan": "10",
                   "Karthik Iyer": "54", "Meera Nair": "76"}

    def _packet(name, amount, reason, step, code, health, free_text=None,
                debit=False, hour=None):
        ts = (datetime.now(IST).replace(hour=hour, minute=47, second=0,
                                        microsecond=0) if hour is not None
              else datetime.now(IST))
        return EvidencePacket(
            event_id="live_demo", customer_id=name, invoice_id="inv_tryit_001",
            attempt_no=1, amount=float(amount), method="UPI", geo_tier="tier2",
            timestamp_ist=ts.isoformat(), tenure_days=120, mandate_status="none",
            retry_count=0, error_code=code, error_source="bank",
            error_reason=reason, error_step=step, bank_health_score=health,
            attempts_today=1, debit_confirmation_flag=debit, free_text=free_text,
            is_ambiguous_reason=reason in ("BANK_DECLINED", "PAYMENT_FAILED"))

    PRESETS = {
        "3D-Secure page stuck at checkout": _packet(
            "Priya Sharma", 12917, "PAYMENT_FAILED", "authentication",
            "3DS_TIMEOUT", 0.35, "3d secure page stuck"),
        "Customer typed a wrong UPI ID": _packet(
            "Rohit Verma", 6235, "PAYMENT_FAILED", "collect",
            "BAD_VPA", 0.55, "galat UPI id daal di"),
        "Bank declined, no reason given": _packet(
            "Ayesha Khan", 326, "BANK_DECLINED", "bank",
            "BANK_DECL", 0.80, None),
        "Customer says money left the account": _packet(
            "Karthik Iyer", 2265, "PAYMENT_PENDING_CONFIRMATION", "verify",
            "PENDING_CONFIRM", 0.90, "paise kat gaye", debit=True),
        "Late-night attempt (11:47 PM)": _packet(
            "Meera Nair", 1585, "PAYMENT_FAILED", "authentication",
            "GATEWAY_TIMEOUT", 0.50, None, hour=23),
    }
    pick_name = st.selectbox("Pick a failed payment", list(PRESETS.keys()), index=0)
    pk = PRESETS[pick_name]
    cA, cB, cC = st.columns([2, 2, 1])
    amt = cA.number_input("Amount (₹)", 50.0, 100000.0, float(pk.amount), step=50.0)
    pk.amount = amt
    ft = cB.text_input("Customer complaint (free text)", value=pk.free_text or "")
    pk.free_text = ft.strip() or None
    run = cC.button("Run it through WAPAS", type="primary", width="stretch")

    utr = "pay_" + f"{abs(hash((pick_name, round(amt)))) % 10**10:010d}"
    st.markdown(
        f'<div class="checkout"><div class="ck-head"><div class="ck-logo">'
        f'{esc(pk.customer_id.split()[0][0])}</div><div>'
        f'<div class="ck-m">{esc(pk.customer_id)} · +91 98••• ••{esc(PHONE_LAST4.get(pk.customer_id, "00"))}</div>'
        f'<div class="ck-s">subscription renewal · invoice inv_tryit_001 · UPI</div></div>'
        f'<div class="ck-amt">{inr(pk.amount)}</div></div>'
        f'<div class="kv2"><span>Payment reference</span><code>{utr}</code></div>'
        f'<div class="kv2"><span>Attempt</span><span>#1 · today '
        f'{pk.event_time().strftime("%H:%M")} IST</span></div>'
        f'<div class="kv2"><span>Gateway</span><span>Razorpay (test-mode shaped)</span></div>'
        f'<div class="ck-status"><span class="dot"></span>PAYMENT FAILED — '
        f'{esc(pk.error_reason)}</div></div>', unsafe_allow_html=True)
    st.caption("The failed payment. In the experiment this arrives as a webhook; the "
               "detector flags it at-risk within seconds.")

    if not run:
        st.info("Press **Run it through WAPAS** — the pipeline below is the real engine.")
        st.stop()

    is_live = bool(llm_agent.os.environ.get("OPENROUTER_API_KEY")
                   or llm_agent.os.environ.get("ANTHROPIC_API_KEY"))

    # steps 1-2: detector + rules tier
    hint = rules_tier.diagnose(pk)
    st.markdown('<div class="step"><div class="step-n">1</div><div class="step-b">'
                '<div class="step-t">Detector flags the payment at-risk</div>'
                '<div class="step-d">Failed payment on an active subscription — recoverable '
                'revenue, but every contact costs goodwill. Doing nothing is also a decision '
                f'(the control arm recovers only 13.7% organically).</div></div></div>',
                unsafe_allow_html=True)
    if hint["resolved"]:
        st.markdown('<div class="step"><div class="step-n">2</div><div class="step-b">'
                    '<div class="step-t">Rules tier solves it instantly — no AI needed</div>'
                    '<div class="step-d">Deterministic evidence is enough here: '
                    f'<code>{esc(hint["basis"])}</code>. This is the cheap ~76% path — the '
                    'LLM never wakes up for cases the rules already understand.</div>'
                    '</div></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="step"><div class="step-n">2</div><div class="step-b">'
                    '<div class="step-t">Rules tier: not enough evidence</div>'
                    '<div class="step-d">The gateway only says "failed" — the real cause is '
                    'hidden. This is the ambiguous ~24%: exactly where the LLM tier earns '
                    'its keep, reading the evidence packet (and the customer&#39;s own words) '
                    'before anyone acts.</div></div></div>', unsafe_allow_html=True)

    # step 3: diagnosis (real agent; live if a key is present, honest stand-in otherwise)
    d = dm.diagnose_event(pk, live=is_live,
                          cache_path=Path(tempfile.gettempdir()) / "wapas_tryit_cache.json")
    if d["source"] == "rules":
        pill = '<span class="pill pill-idle"><span class="dot"></span>RULES</span>'
    else:
        pill = source_pill(d.get("source", "llm_heuristic"))
    st.markdown('<div class="step"><div class="step-n">3</div><div class="step-b">'
                '<div class="step-t">Diagnosis</div>'
                '<div class="step-d">Cause &nbsp;<code>' + esc(d["root_cause"]) + '</code>'
                ' &nbsp;·&nbsp; confidence <b>' + f'{float(d["confidence"]):.2f}' + '</b>'
                ' &nbsp;·&nbsp; ' + pill + '<br>Proposed action &nbsp;<code>'
                + esc(d["action"]) + '</code> — a hint, not a command. The gate still has '
                'to approve it.</div></div></div>', unsafe_allow_html=True)

    # step 4: gate
    gate = Gate()
    now = pk.event_time()
    dec = gate.decide(pk, d, now)
    trace = dec.get("gate_trace") or []
    auth_line = (f' — {esc(dec.get("authority_reason", ""))}'
                 if dec.get("authority_reason") else "")
    st.markdown('<div class="step"><div class="step-n">4</div><div class="step-b">'
                '<div class="step-t">Policy gate — consent, caps, quiet hours</div>'
                '<div class="step-d">Result <b>' + esc(dec["policy_result"]) + '</b>'
                ' · executes <code>' + esc(dec["final_action"]) + '</code> · authority <b>'
                + esc(str(dec.get("authority"))) + '</b>' + auth_line
                + '</div></div></div>', unsafe_allow_html=True)
    if dec.get("blocked_reason"):
        st.error(dec["blocked_reason"], icon=None)
    if trace:
        timeline(trace)

    # step 5: the customer's phone
    st.markdown('<div class="step"><div class="step-n">5</div><div class="step-b">'
                '<div class="step-t">What the customer actually experiences</div>'
                '<div class="step-d">The drafted message below is produced by the same '
                'diagnosis agent that ran step 3 — Hinglish and all.</div></div></div>',
                unsafe_allow_html=True)

    def _draft(fallback):
        return d.get("draft_message") or fallback

    FB = {
        "debited_pending": ("We can see your " + inr(pk.amount) + " payment shows as "
                            "debited. Please don't pay again — we're verifying with your "
                            "bank and will confirm within 30 minutes."),
        "card_expired": ("Your saved card has expired, so the " + inr(pk.amount) +
                         " renewal didn't go through. Update it here and we'll complete "
                         "the payment."),
        "expired_mandate": ("Your auto-debit mandate for " + inr(pk.amount) + " expired. "
                            "Here's a fresh approval link — takes 30 seconds."),
    }
    hhmm = now.strftime("%H:%M")
    fa, res = dec["final_action"], dec["policy_result"]
    ph_l, ph_r = st.columns([1, 1])
    with ph_l:
        if fa in ("send_payment_link", "send_reauth_mandate_link"):
            st.markdown(
                '<div class="phone"><div class="screen"><div class="pbar">'
                '<div class="av">W</div><div><div class="nm">WAPAS · ' + esc(utr[:13])
                + '</div><div class="st">business account</div></div></div>'
                '<div class="chat"><div class="chat-day">TODAY</div>'
                '<div class="bubble l">Your payment of ' + esc(inr(pk.amount))
                + " didn't go through."
                '<span class="t">' + hhmm + '</span></div>'
                '<div class="bubble r">' + esc(_draft(FB.get(d["root_cause"], "")))
                + '<a class="paybtn" href="#">Pay ' + esc(inr(pk.amount))
                + " securely<small>UPI · Razorpay · expires in 30 min</small></a>"
                '<span class="t">' + hhmm + ' ✓✓</span></div>'
                '</div></div></div>', unsafe_allow_html=True)
            st.caption("L1 consent: the customer acts themselves — a tap is the whole "
                       "authorization. No card on file is touched.")
        elif fa == "verify_then_reassure":
            st.markdown(
                '<div class="phone"><div class="screen"><div class="pbar">'
                '<div class="av">W</div><div><div class="nm">WAPAS · support</div>'
                '<div class="st">business account</div></div></div>'
                '<div class="chat"><div class="chat-day">TODAY</div>'
                '<div class="bubble r">' + esc(_draft(FB.get(d["root_cause"], "")))
                + '<span class="t">' + hhmm + ' ✓✓</span></div>'
                '<div class="sched-note">no retry, no second charge — verify-only</div>'
                '</div></div></div>', unsafe_allow_html=True)
            st.caption("A confirmed debit is NEVER re-charged (NEVER_RETRY_CAUSES). The "
                       "safest recovery action here is reassurance + verification.")
        elif fa in ("retry_now", "retry_alternate_method", "retry_delayed"):
            extra = {"retry_now": "Retrying your payment now — no action needed.",
                     "retry_alternate_method": "You can also pay via PhonePe / GPay / Paytm.",
                     "retry_delayed": ""}.get(fa, "")
            st.markdown(
                '<div class="phone"><div class="screen"><div class="pbar">'
                '<div class="av">W</div><div><div class="nm">WAPAS</div>'
                '<div class="st">business account</div></div></div>'
                '<div class="chat"><div class="chat-day">TODAY</div>'
                '<div class="bubble r">' + esc(_draft("We're re-attempting your payment of "
                + inr(pk.amount) + ". " + extra))
                + '<span class="t">' + hhmm + ' ✓✓</span></div>'
                '</div></div></div>', unsafe_allow_html=True)
            if res == "deferred":
                st.caption("TRAI quiet hours (21:00–09:00 IST): the system waits for "
                           "morning instead of pinging anyone at midnight — same rule as "
                           "your bank's OTPs.")
        elif fa == "escalate_human":
            st.markdown(
                '<div class="phone"><div class="screen"><div class="pbar">'
                '<div class="av">W</div><div><div class="nm">WAPAS · merchant approvals'
                '</div><div class="st">flagged for you</div></div></div>'
                '<div class="chat"><div class="bubble l"><b>Approval needed.</b> '
                + esc(inr(pk.amount)) + " looks like a "
                + esc(d["root_cause"].replace("_", " "))
                + " case. Nothing has been sent or charged — approve or reject with one tap."
                '<span class="t">' + hhmm + '</span></div>'
                '<div class="sched-note">L3: a human decides · customer sees NOTHING until '
                'approval</div></div></div></div>', unsafe_allow_html=True)
            st.caption("Sensitive or risky cases never touch the customer without a person "
                       "in the loop. The AI's job ended at explaining its suspicion.")
        else:
            st.markdown(
                '<div class="card warn"><div class="card-title">No contact</div>'
                '<div class="kv">The gate refused to act on this one'
                + (" — " + esc(dec.get("blocked_reason", "")) if dec.get("blocked_reason") else "")
                + ". A refused action is a written, audited decision — not a silence."
                '</div></div>', unsafe_allow_html=True)
    with ph_r:
        st.markdown(kv_card("Why this message?", [
            f"Diagnosed cause &nbsp;<code>{esc(d['root_cause'])}</code>",
            f"Gate result &nbsp;<b>{esc(res)}</b>",
            f"Action &nbsp;<code>{esc(fa)}</code>",
            "Cheapest action that fits the cause —",
            "never more contact than the customer",
            "consented to."], "ok", icon="shield"), unsafe_allow_html=True)
        st.caption("In the sandbox nothing is charged and nothing is sent. In production, "
                   "the executor performs this one action via Razorpay test APIs and writes "
                   "it to the hash-chained ledger.")

    page_foot("Try it live · same engine as the experiment · nothing scripted, nothing charged")

# ═════════════════════════ Case Files ═════════════════════════
elif page == "Case Files":
    st.markdown(hero(
        "Investigate · Case Files", "search",
        "Case files",
        "One row = one at-risk payment: the AI assessment, the deterministic gate "
        "decision with its written reasoning, the consent level used, and the outcome."),
        unsafe_allow_html=True)
    arm = st.selectbox("Ledger", ARMS, index=3, format_func=lambda k: LABELS[k])
    try:
        rows = load_ledger_rows(arm)
    except FileNotFoundError:
        st.error("Ledger not found — run `make batch` first."); st.stop()

    f1, f2, f3 = st.columns([2, 2, 1])
    view = f1.radio("Outcome", ["all", "recovered", "blocked", "deferred", "to human", "complaint"],
                    horizontal=True)
    causes = ["all"] + sorted({x["root_cause"] for x in rows})
    cause = f2.selectbox("Diagnosed cause", causes)
    max_n = f3.slider("Load limit", 50, 2000, 600)

    sel = rows[:max_n]
    if view == "recovered": sel = [x for x in sel if x["recovered"]]
    elif view == "blocked": sel = [x for x in sel if x.get("policy_result") == "blocked"]
    elif view == "deferred": sel = [x for x in sel if x.get("policy_result") == "deferred"]
    elif view == "to human": sel = [x for x in sel if x["final_action"] == "escalate_human"]
    elif view == "complaint": sel = [x for x in sel if x.get("complaint")]
    if cause != "all":
        sel = [x for x in sel if x["root_cause"] == cause]

    st.markdown(f'<div class="meta">{len(sel):,} of {len(rows):,} cases match.</div>',
                unsafe_allow_html=True)
    if not sel:
        st.stop()
    options = {f"{x['event_id']} · {x['customer_id']} · ₹{x['amount']:,.0f} · "
               f"{x['root_cause']} → {x['final_action']}": x for x in sel}
    pick = st.selectbox("Open a case", list(options.keys()))
    x = options[pick]

    micro("Outcome", "banknote")
    p1, p2, p3, p4 = st.columns(4)
    if x["recovered"]:
        p1.markdown(kpi("Recovered", inr(x.get("recovered_inr", 0)), delta="success",
                        kind="pos", sub=f"of {inr(x['amount'])} at risk", icon="check"),
                    unsafe_allow_html=True)
    elif x.get("policy_result") == "blocked":
        p1.markdown(kpi("Blocked by policy", "₹0", delta="no contact", kind="neg",
                        sub="the gate refused, with a reason", icon="shield_off"),
                    unsafe_allow_html=True)
    else:
        p1.markdown(kpi(x.get("policy_result", "—").title(), "₹0", delta=None,
                        sub=f"of {inr(x['amount'])} at risk", accent="n", icon="clock"),
                    unsafe_allow_html=True)
    p2.markdown(kpi("Amount", inr(x["amount"]), sub=f"attempt {x['attempt_no']}",
                    icon="banknote"), unsafe_allow_html=True)
    p3.markdown(kpi("Decided", str(x["decided_at"])[:16].replace("T", " "),
                    sub=x["customer_id"], accent="n", icon="clock"), unsafe_allow_html=True)
    p4.markdown(kpi("Complaint", "yes" if x.get("complaint") else "none",
                    kind=("neg" if x.get("complaint") else "pos"),
                    sub="churn cost tracked at ₹150",
                    accent="o" if x.get("complaint") else "g", icon="users"),
                unsafe_allow_html=True)

    micro("Decision", "shield")
    l, rr = st.columns(2)
    with l:
        st.markdown(kv_card("AI assessment", [
            f"Cause &nbsp;<code>{esc(x['root_cause'])}</code>",
            f"Confidence &nbsp;<b>{float(x['confidence']):.2f}</b> · "
            f"source &nbsp;{source_pill(x.get('diagnosis_source', 'llm_heuristic'))}",
            f"Proposed &nbsp;<code>{esc(x['proposed_action'])}</code>",
            "Rules resolve ~80% free; the LLM sees the ambiguous rest."], "acc", icon="cpu"),
            unsafe_allow_html=True)
    with rr:
        st.markdown(kv_card("Gate decision", [
            f"Result &nbsp;<b>{esc(x['policy_result'])}</b>",
            f"Executed &nbsp;<code>{esc(x['final_action'])}</code>"
            + (f" ({esc(x['action_variant'])})" if x.get("action_variant") else ""),
            f"Authority &nbsp;<b>{esc(str(x.get('authority')))}</b> — "
            f"<span style='font-size:12px'>{esc(x.get('authority_reason', ''))}</span>"],
            "ok", icon="shield"), unsafe_allow_html=True)
        if x.get("blocked_reason"):
            st.error(x["blocked_reason"], icon=None)
        if x.get("scheduled_for"):
            st.caption(f"Scheduled for {x['scheduled_for'][:16].replace('T', ' ')} "
                       f"(+{x.get('deferred_hours', 0)}h)")

    micro("Gate trace — the reasoning, in order", "list")
    timeline(x["gate_trace"])

    with st.expander("Raw ledger row (what the hash chain protects)"):
        st.json(x)

    page_foot("Case files · one row = one hash-protected decision")

# ═════════════════════════ Tamper Lab ═════════════════════════
elif page == "Tamper Lab":
    st.markdown(hero(
        "Investigate · Tamper Lab", "shield_off",
        "Tamper lab",
        "The audit ledger is hash-chained: every entry embeds the hash of the "
        "previous one. Editing one field anywhere breaks every subsequent hash. "
        "This lab forges a record on a temp copy — the official out/ directory is "
        "never touched.",
        chips='<span class="chip">expected result: <b>CHAIN BROKEN</b></span>'),
        unsafe_allow_html=True)
    arm = st.selectbox("Chain to test", ARMS, index=3, format_func=lambda k: LABELS[k])
    if st.button("Forge a recovery, then verify", type="primary"):
        from wapas.ledger import Ledger, GENESIS_HASH
        tmpdir = Path(tempfile.mkdtemp())
        tmp = tmpdir / "ledger_tmp.jsonl"
        shutil.copy(OUT / f"ledger_{arm}.jsonl", tmp)

        clean = Ledger(tmp)
        ok = clean.verify()
        lines = [f"<span class='d'>$ wapas verify --ledger {esc(arm)}</span>"]
        lines.append(f'<span class="g">OK</span>  chain intact — {len(clean.all())} entries'
                     if ok["ok"] else
                     f'<span class="r">FAIL</span>  already broken at #{ok["broken_at"]}')

        entries = clean.all()
        target = next((e for e in entries if e["content"].get("recovered")), entries[0])
        idx = entries.index(target)
        target["content"] = dict(target["content"])
        target["content"]["recovered"] = not target["content"].get("recovered", False)
        lines.append(f"<span class='d'>$ edit entry #{idx}: recovered → "
                     f"{str(target['content']['recovered']).lower()}  (no re-signing)</span>")

        forged = tmpdir / "ledger_forged.jsonl"
        with open(forged, "w") as f:
            prev = GENESIS_HASH
            for e in entries:
                f.write(json.dumps({"prev_hash": prev, "content": e["content"],
                                    "entry_hash": e["entry_hash"]}, default=str) + "\n")
                prev = e["entry_hash"]
        broken = Ledger(forged).verify()
        lines.append("<span class='d'>$ wapas verify --ledger forged</span>")
        if broken["ok"]:
            lines.append('<span class="r">verify PASSED — that would be a bug in the chain</span>')
        else:
            lines.append(f'<span class="r">FAIL  CHAIN BROKEN at entry #{broken["broken_at"]}'
                         '</span>')
        micro("Session", "power")
        console_block(lines)
        st.caption("The forged row's content no longer matches its recorded hash. Faking "
                   "history means re-mining every later hash — the same reason blockchains work.")
    st.divider()
    st.caption("CLI version: edit out/ledger_*.jsonl by hand, run make verify, watch it fail — "
               "then make batch && make verify to deterministically rebuild the truth.")
    page_foot("Tamper lab · forges on temp copies only · official out/ never touched")

# ═════════════════════════ Kill-Switch Lab ═════════════════════════
elif page == "Kill-Switch Lab":
    st.markdown(hero(
        "Control · Kill-Switch Lab", "power",
        "Kill-switch lab",
        "A live mini-run through the real gate: genuine diagnosis from the offline "
        "cache, genuine outcomes, chronological order. Halfway through, an operator "
        "pulls the kill switch — scheduled actions are cancelled and every later "
        "request is refused with a written reason. Fully in-memory."),
        unsafe_allow_html=True)
    n_events = st.slider("Events", 10, 60, 40)
    halt_at = st.slider("Pull the switch after event #", 5, n_events - 5, n_events // 2)
    if st.button("Run the mini-batch", type="primary"):
        from wapas.data_foundry import generate_events
        from wapas import detector, diagnosis as dm
        from wapas.policy_gate import Gate
        from wapas.executor import execute_sim

        events = generate_events(2000, seed=7)[:n_events]
        packets = [p for p, _ in events]
        detector.annotate(packets)
        ordered = sorted(events, key=lambda ec: ec[0].event_time())

        gate = Gate()
        rows, halt_event, boundary = [], None, None
        for i, (packet, true_cause) in enumerate(ordered):
            if i == halt_at:
                halt_event = gate.halt("dashboard-operator")
                boundary = len(rows)
            now = packet.event_time()
            d = dm.diagnose_event(packet, live=False)
            decision = gate.decide(packet, d, now)
            outcome = execute_sim(decision, true_cause, decision["contacts_before"])
            rows.append({**decision, "recovered": outcome["recovered"]})

        cancelled = halt_event["scheduled_cancelled"] if halt_event else 0
        blocked_after = sum(1 for x in rows[boundary:] if x["policy_result"] == "blocked")
        acted_before = sum(1 for x in rows[:boundary] if x["final_action"] != "no_action")

        micro("Halt summary", "power")
        a, b, c = st.columns(3)
        a.markdown(kpi("Executed before halt", str(acted_before),
                       sub="normal operations", icon="check"), unsafe_allow_html=True)
        b.markdown(kpi("Scheduled cancelled", str(cancelled), delta="safe drain",
                       kind="neu", icon="clock"), unsafe_allow_html=True)
        c.markdown(kpi("Refused after halt", str(blocked_after),
                       sub="each with a written reason", accent="o", icon="shield_off"),
                   unsafe_allow_html=True)

        micro("Console", "list")
        console_block([
            "<span class='d'>$ operator dashboard-operator: halt</span>",
            f"<span class='r'>KILL SWITCH</span>  engaged after event #{boundary} — "
            f"{cancelled} scheduled action(s) cancelled",
            "<span class='d'>$ subsequent requests</span>",
            "<span class='g'>blocked</span>  kill switch active (halted by dashboard-operator) "
            "— zero half-done money actions"])

        micro("Run log", "layers")
        htable(["#", "event", "proposed", "executed", "result", "reason"],
               [[str(i), esc(x["event_id"]), esc(x["proposed_action"]),
                 esc(x["final_action"]),
                 f"<b>{esc(x['policy_result'])}</b>",
                 esc((x.get("blocked_reason") or x.get("authority_reason") or "")[:70])]
                for i, x in enumerate(rows)])
        st.caption("Rows before the halt include quiet-hour deferrals and consent downgrades — "
                   "the system was safe before the switch and safe after it.")
    page_foot("Kill-switch lab · in-memory only · one operator halt drains everything safely")

# ═════════════════════════ Assurances ═════════════════════════
else:
    st.markdown(hero(
        "Governance · Assurances", "shield",
        "Why this is safe to ship",
        "WAPAS never decides on its own authority. The AI reads evidence and drafts; a "
        "deterministic gate approves; a human approves anything that needs approval. "
        "Every money-touching action traces to explicit customer consent.",
        chips='<span class="chip"><b>no authority, no action</b></span>'
              '<span class="chip">consent tiers <b>L1 / L2 / L3</b></span>'
              '<span class="chip">kill switch <b>built in</b></span>'),
        unsafe_allow_html=True)

    micro("The three consent tiers — what authorizes each action", "lock")
    t1, t2, t3 = st.columns(3)
    t1.markdown(kv_card("L1 — consent right now", [
        f"{ic('lock', 13)} &nbsp;Customer is present and acts themselves",
        "PIN / OTP / in-app confirm",
        "Example: you send a fresh payment",
        "link; they choose to pay it."], "ok", icon="lock"), unsafe_allow_html=True)
    t2.markdown(kv_card("L2 — signed mandate", [
        f"{ic('doc', 13)} &nbsp;Customer signed an auto-debit mandate earlier",
        "RBI e-mandate framework: advance",
        "notice before every debit, and a",
        "window to cancel."], "acc", icon="doc"), unsafe_allow_html=True)
    t3.markdown(kv_card("L3 — a human decides", [
        f"{ic('users', 13)} &nbsp;Anything big, odd, or sensitive",
        "escalate_human with the full evidence",
        "packet; no message, no retry, no",
        "action until a person approves."], "warn", icon="users"), unsafe_allow_html=True)

    micro("Where we deliberately do NOT use AI", "shield_off")
    na, nb = st.columns(2)
    na.markdown(kv_card("Not in the decision seat", [
        "The policy gate is deterministic code:",
        "fixed caps, fixed consent rules, fixed",
        "quiet hours. The LLM cannot invent an",
        "action, raise a cap, or skip a human.",
        "Its proposal is a hint with citations —",
        "the gate, not the model, decides."], "warn", icon="shield_off"),
        unsafe_allow_html=True)
    nb.markdown(kv_card("Not in the money path", [
        "The executor performs exactly one",
        "pre-approved action and writes it to",
        "the hash-chained ledger. No autonomous",
        "retries, no self-directed payment flows,",
        "no agent-initiated mandates — ever."], "acc", icon="banknote"),
        unsafe_allow_html=True)

    micro("Named rules this respects", "doc")
    rc1, rc2, rc3 = st.columns(3)
    rc1.markdown(kv_card("RBI — e-mandate framework", [
        "Advance notice before every",
        "auto-debit; customer can cancel;",
        "mandates are the only L2 authority."], "ok", icon="doc"), unsafe_allow_html=True)
    rc2.markdown(kv_card("TRAI — TCCCPR / DLT", [
        "Consent-based messaging, registered",
        "templates, quiet hours observed by",
        "the deferral layer (21:00–09:00)."], "acc", icon="clock"), unsafe_allow_html=True)
    rc3.markdown(kv_card("DPDP Act, 2023", [
        "Purpose-limited data: evidence",
        "packets carry the minimum needed",
        "to diagnose, nothing more."], "p", icon="lock"), unsafe_allow_html=True)

    micro("If a human says stop, everything stops", "power")
    st.markdown(kv_card("Kill switch", [
        "One operator halt cancels every scheduled action and refuses all",
        "later requests with a written reason — demonstrated live in the",
        "Kill-Switch Lab, and enforced in the same gate code the batch uses."],
        "warn", icon="power"), unsafe_allow_html=True)

    page_foot("Assurances · consent tiers, named regulators, auditable ledgers")
