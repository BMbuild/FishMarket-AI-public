"""Ocean theme: dark/light blue wave background and original inline SVG sea animals (no external images)."""
from __future__ import annotations

WAVE = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 320' preserveAspectRatio='none'>"
        "<path fill='%2338bdf8' fill-opacity='0.18' d='M0,224 C240,128 480,320 720,224 C960,128 1200,320 1440,192 L1440,320 L0,320Z'/>"
        "<path fill='%230ea5e9' fill-opacity='0.22' d='M0,256 C300,160 540,320 840,240 C1080,176 1260,272 1440,236 L1440,320 L0,320Z'/>"
        "<path fill='%231e3a8a' fill-opacity='0.35' d='M0,288 C260,224 520,320 800,272 C1040,232 1260,300 1440,276 L1440,320 L0,320Z'/></svg>")

CSS = f"""
<style>
:root {{
  color-scheme: dark;
  --fm-bg: #0b2a5b; --fm-panel: rgba(12, 38, 74, .78); --fm-panel-deep: #0a2147;
  --fm-teal: #54b9aa; --fm-coral: #ef9960; --fm-text: #e8f3ff; --fm-muted: #b5cbe0;
}}
/* dark-to-light blue water with three wave layers */
.stApp {{
  color: var(--fm-text);
  background:
    url("data:image/svg+xml;utf8,{WAVE}") bottom/100% 260px no-repeat fixed,
    linear-gradient(180deg, #08204a 0%, #0f3f80 40%, #1d6fb8 75%, #5fb4e8 100%) fixed;
}}
[data-testid="stHeader"] {{ background: rgba(8, 32, 74, .85); }}
[data-testid="stSidebar"] {{ background: var(--fm-panel-deep); }}
[data-testid="stSidebar"] * {{ color: var(--fm-text); }}
.stApp p, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp li, .stApp small {{ color: var(--fm-text); }}
[data-testid="stWidgetLabel"] p {{ color: var(--fm-muted); }}
[data-baseweb="select"] > div, [data-baseweb="input"] > div, [data-baseweb="textarea"] > div, [data-testid="stNumberInput"] input {{
  background: #123a6e; color: var(--fm-text); border-color: #3b78b8; }}
[data-baseweb="popover"], [role="listbox"] {{ background: #123a6e; color: var(--fm-text); }}
[role="option"]:hover {{ background: #1d5a9e; }}
[data-testid="stAlert"] {{ background: rgba(58, 52, 44, .92) !important; color: #f3c99c; border-left: 4px solid var(--fm-coral); }}
[data-testid="stAlert"] p {{ color: #f3c99c; }}
.stButton > button[kind="primary"] {{ background: var(--fm-teal); color: #0c2632; border: 0; font-weight: 700; }}
.stButton > button {{ border-color: #5fa0d8; }}
[data-testid="stMetric"] {{ background: var(--fm-panel); padding: 12px; border-radius: 12px; }}
[data-testid="stDataFrame"], [data-testid="stTable"] {{ background: var(--fm-panel); border-radius: 10px; }}
.fm-brand {{ padding: 8px 0 14px; }}
.fm-brand img {{ width: min(100%, 570px); height: auto; }}
.fm-hero {{ padding:.6rem 0 .3rem; }}
.fm-hero h1 {{ font-size:2.2rem; margin:0; }}
.fm-hero p {{ font-size:1.1rem; color: var(--fm-muted); max-width:46rem; }}
.fm-card {{ background: var(--fm-panel); border:1px solid #3b78b8; border-radius:14px; padding:1rem 1.2rem; margin:.5rem 0; color: var(--fm-text); }}
.fm-animals {{ display:flex; gap:1.2rem; flex-wrap:wrap; align-items:flex-end; margin:.6rem 0; }}
.fm-animals svg {{ height:84px; width:auto; }}
.fm-note {{ font-size:.85rem; opacity:.85; }}
.fm-pill {{ display:inline-block; padding:2px 10px; border-radius:999px; font-weight:700; font-size:.85rem; }}
.fm-real {{ background:#1f6fa8; }} .fm-web {{ background:#5b4b9a; }} .fm-synth {{ background:#8a5a14; }} .fm-ok {{ background:#1f8f6a; }} .fm-warn {{ background:#b8741a; }} .fm-flag {{ background:#b3382f; }}
</style>
"""


def brand_html(logo_svg_bytes: bytes) -> str:
    import base64
    b64 = base64.b64encode(logo_svg_bytes).decode("ascii")
    return ("<div class='fm-brand'><img src='data:image/svg+xml;base64," + b64 +
            "' alt='FishMarket AI - From Catch to Global Market'></div>")


def origin_pill(label: str) -> str:
    cls = "fm-synth" if ("SYNTH" in label or "FIXTURE" in label) else "fm-web" if label.startswith("WEB") else "fm-real"
    return f"<span class='fm-pill {cls}'>{label}</span>"


def pill(status: str) -> str:
    cls = {"OK": "fm-ok", "WARNING": "fm-warn", "FLAGGED": "fm-flag"}.get(status, "fm-warn")
    return f"<span class='fm-pill {cls}'>{status}</span>"


def _svg(inner: str, vb: str = "0 0 120 80") -> str:
    return f"<svg viewBox='{vb}' xmlns='http://www.w3.org/2000/svg' role='img'>{inner}</svg>"

WHALE = _svg("<title>Whale</title><path d='M6 46 C20 14 70 10 96 34 C104 22 112 20 116 14 C116 28 112 40 104 46 C112 50 114 58 116 66 C106 62 100 58 96 54 C70 74 24 74 6 46Z' fill='#1d4ed8'/>"
             "<path d='M20 52 C40 66 70 66 92 50 C70 58 40 58 20 52Z' fill='#bfdbfe'/><circle cx='28' cy='40' r='2.5' fill='#fff'/>"
             "<path d='M44 14 q4 -10 0 -14 M48 14 q6 -8 10 -10' stroke='#7dd3fc' stroke-width='2.5' fill='none' stroke-linecap='round'/>")
FISH = _svg("<title>Fish</title><path d='M10 40 C30 12 70 12 92 40 C70 68 30 68 10 40Z' fill='#f59e0b'/><path d='M92 40 L116 20 L110 40 L116 60Z' fill='#d97706'/>"
            "<circle cx='30' cy='36' r='3.5' fill='#fff'/><circle cx='29' cy='36' r='1.6' fill='#111'/><path d='M50 22 C54 40 54 40 50 58' stroke='#b45309' stroke-width='2' fill='none'/>")
CRAB = _svg("<title>Crab</title><ellipse cx='60' cy='46' rx='30' ry='20' fill='#ef4444'/><path d='M34 40 C14 40 10 20 22 14 C20 26 30 30 38 32Z M86 40 C106 40 110 20 98 14 C100 26 90 30 82 32Z' fill='#dc2626'/>"
            "<path d='M34 54 L18 66 M38 60 L26 74 M86 54 L102 66 M82 60 L94 74' stroke='#b91c1c' stroke-width='4' stroke-linecap='round'/>"
            "<circle cx='50' cy='30' r='4' fill='#fff'/><circle cx='70' cy='30' r='4' fill='#fff'/><circle cx='50' cy='30' r='1.8' fill='#111'/><circle cx='70' cy='30' r='1.8' fill='#111'/>")
JELLY = _svg("<title>Jellyfish</title><path d='M20 44 C20 8 100 8 100 44Z' fill='#c084fc' fill-opacity='.85'/>"
             "<path d='M30 44 q-4 14 2 28 M48 44 q4 14 -2 30 M66 44 q-4 14 2 28 M84 44 q4 14 -2 26' stroke='#a855f7' stroke-width='3' fill='none' stroke-linecap='round'/>"
             "<circle cx='48' cy='28' r='3' fill='#fff'/><circle cx='72' cy='28' r='3' fill='#fff'/>")
TURTLE = _svg("<title>Sea turtle</title><ellipse cx='60' cy='42' rx='34' ry='22' fill='#16a34a'/><path d='M40 42 h40 M52 24 v36 M68 24 v36' stroke='#14532d' stroke-width='2.5'/>"
              "<circle cx='100' cy='38' r='9' fill='#4ade80'/><circle cx='103' cy='35' r='1.8' fill='#111'/>"
              "<path d='M34 58 L18 74 L40 66Z M80 58 L96 74 L72 66Z M34 26 L16 14 L40 20Z' fill='#4ade80'/>")
OCTOPUS = _svg("<title>Octopus</title><path d='M30 40 C30 6 90 6 90 40 C90 52 82 56 78 56 L42 56 C38 56 30 52 30 40Z' fill='#f472b6'/>"
               "<path d='M36 56 q-12 8 -6 20 M50 56 q-4 12 -10 18 M64 56 q4 12 10 18 M78 56 q12 8 6 20' stroke='#ec4899' stroke-width='5' fill='none' stroke-linecap='round'/>"
               "<circle cx='50' cy='34' r='5' fill='#fff'/><circle cx='70' cy='34' r='5' fill='#fff'/><circle cx='51' cy='35' r='2.2' fill='#111'/><circle cx='71' cy='35' r='2.2' fill='#111'/>")

def animals(*names: str) -> str:
    m = {"whale": WHALE, "fish": FISH, "crab": CRAB, "jelly": JELLY, "turtle": TURTLE, "octopus": OCTOPUS}
    return "<div class='fm-animals'>" + "".join(m[n] for n in names) + "</div>"


def chart(kind: str, data, x_label: str, y_label: str) -> None:
    """st.line_chart / st.bar_chart with axis labels (Streamlit 1.36+); older versions draw it without them."""
    import streamlit as st
    fn = {"line": st.line_chart, "bar": st.bar_chart}[kind]
    try:
        fn(data, x_label=x_label, y_label=y_label)
    except TypeError:
        fn(data)
        st.caption(f"x: {x_label} · y: {y_label}")
