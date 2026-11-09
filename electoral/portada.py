"""Portada y explicación de los métodos disponibles en el laboratorio."""

import streamlit as st


def mostrar_portada(eleccion: str) -> None:
    """Presenta el alcance y las fórmulas sin ejecutar cálculos adicionales."""
    st.html("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Libre+Franklin:wght@700;800&display=swap');
.le-stage{--le-ink:#f8f3fa;--le-muted:#c9bed0;--le-rule:#63546a;position:relative;overflow:hidden;
  min-height:510px;background:#1b1525;color:var(--le-ink);font-family:Arial,Helvetica,sans-serif}
.le-stage:before{content:"";position:absolute;inset:0 0 0 46%;background:#291d36;clip-path:polygon(14% 0,100% 0,100% 100%,0 100%)}
.le-stage:after{content:"";position:absolute;left:0;right:0;bottom:0;height:8px;
  background:linear-gradient(90deg,#4b9bd1 0 33.333%,#e9c258 33.333% 66.666%,#d75a58 66.666%)}
.le-stage-inner{position:relative;z-index:1;display:grid;grid-template-columns:1.06fr .94fr;min-height:510px}
.le-stage-copy{padding:clamp(32px,4vw,58px);display:flex;flex-direction:column;justify-content:space-between}
.le-stage h1{font-family:'Libre Franklin',Arial,sans-serif;font-size:clamp(3.5rem,6.1vw,6rem);line-height:.9;letter-spacing:-.04em;margin:0;
  font-weight:800;max-width:9ch;text-wrap:balance}
.le-stage h1 span{display:block;color:#e3bbf3}
.le-stage-lead{font-size:clamp(1.12rem,1.6vw,1.45rem);line-height:1.35;max-width:30ch;margin:32px 0 0;color:#f0e7f2}
.le-stage-foot{border-top:1px solid var(--le-rule);padding-top:17px;margin-top:42px;
  display:flex;justify-content:space-between;gap:15px;color:var(--le-muted);font-size:13px;line-height:1.35}
.le-stage-foot strong{color:#fff;font-weight:700}
.le-stage-map{position:relative;min-height:400px;display:flex;align-items:center;justify-content:center;
  background:url('/app/static/mexico_estados.svg') center 43%/118% auto no-repeat}
.le-stage-map:before{content:"";position:absolute;inset:9% 7% 17%;border:1px solid rgba(226,202,237,.15)}
.le-stage-map:after{content:"";position:absolute;left:8%;top:11%;height:78%;border-left:1px solid rgba(226,202,237,.15)}
.le-map-label{position:absolute;z-index:1;left:10%;bottom:12%;padding:10px 14px;background:#f5eff4;
  color:#211829;font-size:13px;font-weight:700;letter-spacing:.025em}
.le-map-label small{display:block;font-size:10px;letter-spacing:.12em;color:#65576b;margin-bottom:3px}
.le-overview{margin:24px 0 10px;padding:0 0 24px;border-bottom:1px solid #5c4a65;color:#f5eff6}
.le-overview-head{font-size:clamp(1.55rem,2.7vw,2.75rem);line-height:1.12;letter-spacing:-.025em;
  max-width:29ch;font-weight:700;margin:0 0 22px}
.le-methods{display:grid;grid-template-columns:1.15fr .9fr .9fr;gap:0;border-top:1px solid #5c4a65}
.le-method{padding:18px 25px 5px 0;min-width:0}
.le-method+.le-method{border-left:1px solid #5c4a65;padding-left:25px}
.le-method b{display:block;color:#f9f3fa;font-size:17px;line-height:1.2;margin-bottom:10px}
.le-method p{font-size:14px;line-height:1.45;color:#d4c8da;margin:0}
.le-method em{display:block;font-style:normal;font-family:Georgia,serif;color:#efca77;
  font-size:clamp(1.5rem,2.2vw,2.25rem);line-height:1.15;margin-bottom:13px}
@media(max-width:800px){.le-stage-inner{grid-template-columns:1fr}.le-stage{min-height:0}
  .le-stage-copy{padding:30px 26px 18px}.le-stage h1{font-size:clamp(3.6rem,12vw,6rem)}
  .le-stage-lead{margin-top:22px}.le-stage-foot{margin-top:28px}
  .le-stage-map{min-height:265px;background-size:92% auto}.le-map-label{left:8%;bottom:7%}
  .le-methods{grid-template-columns:1fr}.le-method,.le-method+.le-method{border-left:0;padding:16px 0;border-bottom:1px solid #5c4a65}}
@media(max-width:460px){.le-stage h1{font-size:clamp(3.15rem,13vw,4.5rem)}
  .le-stage-map{min-height:220px}.le-stage-foot{flex-direction:column;gap:5px}}
</style>
<section class="le-stage" aria-label="Presentación del Laboratorio Electoral">
  <div class="le-stage-inner">
    <div class="le-stage-copy">
      <div><h1>LABORATORIO<span>ELECTORAL</span></h1>
      <p class="le-stage-lead">Explora ventajas, derrotas ajustadas y apoyo mínimo en cada sección</p></div>
      <div class="le-stage-foot"><span><strong>Tres elecciones federales</strong> - cobertura actual 2024</span>
        <span>CPV 2020 por sección disponible cuando se carga el archivo local</span></div>
    </div>
    <div class="le-stage-map" role="img" aria-label="Contornos estatales de México">
      <div class="le-map-label"><small>UNIDAD DE ANÁLISIS</small>Sección electoral</div>
    </div>
  </div>
</section>
<section class="le-overview" aria-label="Métodos del laboratorio">
  <h2 class="le-overview-head">Tres preguntas, una misma geografía</h2>
  <div class="le-methods">
    <div class="le-method"><em>¿Dónde estuvo cerca?</em><b>Rentabilidad electoral</b>
      <p>Compara candidaturas, mide la ventaja o el faltante y clasifica cada sección</p></div>
    <div class="le-method"><em>¿Qué apoyo se repite?</em><b>Apoyo mínimo</b>
      <p>Observa el porcentaje menor de cada partido entre las tres boletas de 2024</p></div>
    <div class="le-method"><em>¿Por dónde empezar?</em><b>Priorización</b>
      <p>Ordena secciones y prueba metas con tus propios supuestos de costo</p></div>
  </div>
</section>
""")
    st.caption(
        f"Cobertura seleccionada: {eleccion}. Diagnóstico exploratorio con datos agregados. "
        "Los resultados de otros años aún no están integrados."
    )

    rent, apoyo, prioridad = st.tabs([
        "Rentabilidad electoral", "Apoyo mínimo (base electoral)",
        "Priorización",
    ])
    with rent:
        st.subheader("Rentabilidad electoral")
        st.markdown("#### Votos de la candidatura")
        st.write(
            "En cada sección se cuentan los votos marcados por los partidos de la candidatura "
            "y por sus combinaciones. Cada marca se suma una vez."
        )
        st.latex(r"V_{c,s}=\sum_{p\in P_c}V_{p,s}+\sum_{m\in M_c}V_{m,s}")
        st.markdown(
            "**$c$** - candidatura que se analiza  \n"
            "**$s$** - sección electoral  \n"
            "**$P_c$** - partidos que integran esa candidatura  \n"
            "**$M_c$** - combinaciones de esos partidos  \n"
            "**$V_{p,s}$** - votos marcados por el partido $p$  \n"
            "**$V_{m,s}$** - votos marcados por la combinación $m$  \n"
            "**$V_{c,s}$** - suma de votos de la candidatura en la sección"
        )

        st.markdown("#### Primer y segundo lugar")
        st.write("Se ordenan los votos de las candidaturas activas en la sección")
        st.latex(r"V_{1,s}=\max_c V_{c,s}")
        st.markdown(
            "**$V_{1,s}$** - votos de la candidatura en primer lugar en la sección $s$  \n"
            "**$V_{2,s}$** - votos del segundo lugar"
        )
        st.write(
            "Hay Victoria cuando la candidatura evaluada supera al segundo lugar. "
            "Si dos candidaturas comparten el primer lugar, hay Empate."
        )

        st.markdown("#### Distancia en votos")
        st.write("Si hubo victoria, el margen es la ventaja sobre el segundo lugar")
        st.latex(r"M_s=V_{c,s}-V_{2,s}\quad(\mathrm{victoria})")
        st.write("Si hubo derrota o empate, el faltante es la distancia al primer lugar")
        st.latex(r"F_s=V_{1,s}-V_{c,s}\quad(\mathrm{derrota\ o\ empate})")
        st.markdown(
            "**$M_s$** - margen de victoria en votos  \n"
            "**$F_s$** - votos que faltaron para igualar el primer lugar. En un empate, **$F_s=0$**"
        )

        st.markdown("#### Distancia en puntos porcentuales")
        st.write("Las dos distancias se dividen entre los votos válidos de la misma sección")
        st.latex(r"m_s=100\frac{M_s}{V_{\mathrm{validos},s}}")
        st.latex(r"f_s=100\frac{F_s}{V_{\mathrm{validos},s}}")
        st.markdown(
            "**$m_s$** - margen en puntos porcentuales  \n"
            "**$f_s$** - faltante en puntos porcentuales  \n"
            "**$V_{\\mathrm{validos},s}$** - total de votos válidos de la sección (`NUM_VOTOS_VALIDOS`)."
        )

        st.markdown("#### Votos para ganar")
        st.write("Para superar al primer lugar se necesita un voto más que el faltante")
        st.latex(r"G_s=F_s+1")
        st.markdown(
            "**$G_s$** - votos adicionales para ganar en una sección con derrota o empate. "
            "Si hubo empate, **$G_s=1$**."
        )

        st.markdown("#### Abstención corregida")
        st.write(
            "Para comparar esa meta con la abstención, se descuentan del total los votos "
            "de casillas especiales, que tienen lista nominal igual a cero."
        )
        st.latex(r"A_s=LN_s-(V_{\mathrm{total},s}-V_{S,s})")
        st.markdown(
            "**$A_s$** - abstención corregida  \n"
            "**$LN_s$** - lista nominal de la sección  \n"
            "**$V_{\\mathrm{total},s}$** - total de votos registrados en la sección  \n"
            "**$V_{S,s}$** - votos de casillas especiales no anuladas en esa sección"
        )
        st.caption(
            "Clases actuales: victoria sólida desde 15 pp de margen; derrota competitiva por debajo "
            "de 5 pp, derrota intermedia de 5 a menos de 15 pp y derrota lejana desde 15 pp."
        )
    with apoyo:
        st.subheader("Apoyo mínimo observado")
        st.write(
            "Para cada partido y sección se estima su porcentaje de votos válidos en las tres "
            "elecciones federales de 2024. El apoyo mínimo es el menor de esos tres porcentajes; "
            "el rango muestra cuánto cambió entre boletas."
        )
        st.latex(r"P_{p,s,e}=100\frac{V^A_{p,s,e}}{V_{\mathrm{validos},s,e}}")
        st.latex(r"\mathrm{piso}_{p,s}=\min_{e\in\{P,D,S\}}P_{p,s,e}")
        st.latex(r"R_{p,s}=\max_e P_{p,s,e}-\min_e P_{p,s,e}")
        st.write(
            "Las etiquetas «Bastión» y «Base fuerte» son una propuesta provisional: "
            "comparan el apoyo mínimo con el percentil del partido en el estado o en el país. "
            "Una sección volátil rebasa el umbral de Tukey del rango de su grupo."
        )
        st.caption(
            "El reparto A_propios de votos de coalición entre partidos es experimental. "
            "«Base electoral» nombra una medida agregada de 2024; no demuestra fidelidad individual."
        )
    with prioridad:
        st.subheader("Priorización de secciones")
        st.write(
            "El simulador ordena secciones con derrota o empate que tienen abstención positiva. "
            "Puedes indicar un costo estimado por voto, cambiarlo por sección, descartar secciones "
            "y probar un presupuesto. Son supuestos tuyos para comparar escenarios."
        )
        st.latex(r"C_s=(F_s+1)c_s")
        st.caption("Cₛ: costo estimado de la sección; cₛ: costo por voto supuesto por el usuario.")
        st.write(
            "La meta de un distrito usa su faltante agregado más un voto. El simulador compara "
            "esa meta con la abstención disponible de las secciones no descartadas, ordenadas por costo."
        )
        st.caption("No estima que una persona se abstuvo por una causa específica ni predice que votará por una candidatura.")

    st.html("""
<aside style="border-left:3px solid #b44fff;background:#1b1627;border-radius:8px;
  padding:15px 19px;color:#e5daec;font-family:Arial,Helvetica,sans-serif;line-height:1.45">
  <strong style="color:#e1b8ff;letter-spacing:.08em;font-size:12px">CRUCE SECCIONAL</strong><br>
  El bloque «¿Por qué?» compara perfiles del CPV 2020 con votos de 2024 cuando el archivo local está disponible.
  asociación, no causa.
</aside>
""")
