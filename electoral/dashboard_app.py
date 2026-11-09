"""Entrada del tablero electoral para la presentación de Querétaro."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from electoral.boletas_tab import mostrar_explorador_boletas
from electoral.dashboard_casillas import mostrar_dashboard_casillas
from electoral.dashboard_portada import mostrar_portada_dashboard


st.set_page_config(page_title="Cartografunk · decisiones territoriales",
                   page_icon=":material/map:", layout="wide",
                   initial_sidebar_state="collapsed")
st.html("""
<style>
.stApp{background:radial-gradient(ellipse at 52% -18%,#073556 0%,#031c31 39%,#021321 78%);color:#eaf5ff}
.stMainBlockContainer{padding-top:1.5rem;padding-bottom:3rem;max-width:1600px}
.stApp [data-testid="stMetric"]{background:linear-gradient(155deg,#07324d,#05243b);
  border:1px solid #115076;border-radius:16px;padding:1rem 1.15rem}
.stApp [data-testid="stMetricValue"]{color:#f6fbff}
.stApp [data-testid="stCaptionContainer"]{color:#a9cbe0}
.stApp [data-testid="stDataFrame"]{border:1px solid #124767;border-radius:12px}
.stApp button[kind="secondary"]{border-color:#12628b;background:#062b45;color:#e4f6ff}
.stApp button[kind="secondary"]:hover{border-color:#26baff;color:#fff}
.electoral-eyebrow{color:#59d6f4;font-size:.78rem;font-weight:700;
  letter-spacing:.14em;text-transform:uppercase;margin-bottom:.3rem}
.electoral-header{border-bottom:1px solid #105071;padding-bottom:1rem;margin-bottom:1.2rem}
.electoral-header strong{font-size:1.25rem;letter-spacing:.015em}
.electoral-header span{color:#9ec8dd;margin-left:.7rem}
@media(max-width:700px){.stMainBlockContainer{padding-top:.8rem}
  .electoral-header span{display:block;margin:.35rem 0 0}}
</style>
<div class="electoral-header"><strong>Cartografunk Electoral</strong>
<span>Evidencia territorial · Querétaro</span></div>
""")
VISTAS = ("Inicio", "Boletas y apoyo mínimo", "Cuatro preguntas")
st.session_state.setdefault("dashboard_vista", "Inicio")
vista = st.segmented_control("Vista", VISTAS, key="dashboard_vista", width="stretch")
if vista == "Inicio":
    mostrar_portada_dashboard(ROOT)
elif vista == "Boletas y apoyo mínimo":
    mostrar_explorador_boletas(ROOT)
else:
    mostrar_dashboard_casillas(22, ROOT)
