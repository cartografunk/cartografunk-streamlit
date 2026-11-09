"""Entrada directa para presentar las cuatro preguntas del piloto Querétaro."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from electoral.boletas_tab import mostrar_explorador_boletas
from electoral.dashboard_casillas import mostrar_dashboard_casillas


st.set_page_config(page_title="Cartografunk · decisiones de campaña", layout="wide",
                   initial_sidebar_state="collapsed")
st.html("""
<style>
.stMainBlockContainer{padding-top:1.3rem;padding-bottom:2rem}
.presentacion-header{padding:2px 0 12px;border-bottom:1px solid #38204d;
  font:700 12px Arial,sans-serif;letter-spacing:.14em;color:#e8d6f4}
</style>
<header class="presentacion-header">CARTOGRAFUNK / DIAGNÓSTICO ELECTORAL</header>
""")
explorador, diagnostico = st.tabs(["Boletas y apoyo mínimo", "Cuatro preguntas · piloto diputaciones"])
with explorador:
    mostrar_explorador_boletas(ROOT)
with diagnostico:
    mostrar_dashboard_casillas(22, ROOT)
