from __future__ import annotations

import json
import tempfile
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd
import streamlit as st

# Carga variables desde .env antes de inicializar agentes/LLMs
load_dotenv()

from src.graph.builder import am_change_control_agent


st.set_page_config(
    page_title="Aura | Migracion de metodo analitico",
    page_icon="",
    layout="wide",
    initial_sidebar_state="collapsed",
)

PRIMARY = "#009688"
PRIMARY_DARK = "#007c70"
NAVY = "#0c2c6a"
BORDER = "#d7e3ea"

CUSTOM_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&family=Manrope:wght@400;500;600&display=swap');

* {{ font-family: 'Poppins', 'Manrope', 'Segoe UI', sans-serif; }}
html, body, .stApp {{
    background: linear-gradient(180deg, #d7e6f4 0%, #c7dbef 45%, #c0d5ea 100%);
}}

.app-wrapper {{
    padding: 10px 14px 38px 14px;
}}

.hero {{
    background: linear-gradient(120deg, {PRIMARY} 0%, #00a69c 60%, #00b3a4 100%);
    color: #fff;
    padding: 18px 22px;
    border-radius: 12px;
    box-shadow: 0 10px 30px rgba(0, 138, 130, 0.26);
}}

.hero-title {{
    font-size: 26px;
    font-weight: 600;
    letter-spacing: -0.3px;
    margin: 0;
}}

.hero-sub {{
    margin: 2px 0 0 0;
    opacity: 0.92;
}}

.top-logo {{
    height: 46px;
    object-fit: contain;
}}

.badge {{
    background: rgba(255, 255, 255, 0.14);
    padding: 8px 14px;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 500;
}}

.card {{
    background: #fff;
    border-radius: 14px;
    padding: 18px 18px 24px 18px;
    border: 1px solid {BORDER};
    box-shadow: 0 8px 20px rgba(12, 44, 106, 0.03);
    margin-bottom: 18px;
}}

.section-title {{
    color: {PRIMARY};
    font-weight: 600;
    margin-bottom: 10px;
    letter-spacing: -0.15px;
}}

.stepper {{
    display: flex;
    flex-direction: column;
    gap: 10px;
}}

.step-pill {{
    border: 1px solid {BORDER};
    background: linear-gradient(180deg, #f4fbfa, #ffffff);
    border-radius: 12px;
    padding: 12px 14px;
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 14px;
    color: #29405d;
    box-shadow: 0 8px 16px rgba(0, 150, 136, 0.05);
}}

.step-index {{
    width: 28px;
    height: 28px;
    border-radius: 9px;
    display: grid;
    place-items: center;
    color: #fff;
    background: {PRIMARY};
    font-weight: 600;
    box-shadow: 0 4px 10px rgba(0, 150, 136, 0.25);
}}

.upload-box {{
    border: 1.5px dashed {BORDER};
    background: #f7fbfc;
    border-radius: 12px;
    padding: 14px;
}}

.status {{
    color: {NAVY};
    font-weight: 600;
}}

.stButton>button {{
    background: {PRIMARY};
    color: #fff;
    border: none;
    border-radius: 12px;
    padding: 12px 20px;
    font-weight: 600;
    letter-spacing: 0.1px;
    box-shadow: 0 8px 18px rgba(0, 150, 136, 0.28);
}}

.stButton>button:hover {{ background: {PRIMARY_DARK}; }}

.pill-input .stTextInput>div>input,
.pill-input .stSelectbox>div>div>input {{
    border-radius: 10px;
    border: 1.5px solid #17306a;
}}
</style>
"""


def _load_logo() -> Path | None:
    logo_path = Path(__file__).resolve().parent / "Sofgen-Pharma.png"
    return logo_path if logo_path.exists() else None


def render_hero() -> None:
    logo_path = _load_logo()
    with st.container():
        cols = st.columns([6, 1.4])
        with cols[0]:
            st.markdown(
                """
                <div class="hero">
                    <div class="hero-title">Aura · Migracion de metodo analitico</div>
                    <div class="hero-sub">Registro, control de cambios y planificacion de insumos.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with cols[1]:
            if logo_path:
                st.image(str(logo_path), width=180)
            else:
                st.markdown(
                    """
                    <div class="hero" style="display:flex;align-items:center;justify-content:center;min-height:68px;">
                        <div class="badge">Logo Sofgen pendiente</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def render_stepper() -> None:
    steps = [
        "Metodo anterior",
        "Nuevo metodo",
        "Soportes y anexos",
        "Listado",
    ]
    pills = "".join(
        f'<div class="step-pill"><div class="step-index">{idx + 1}</div><div>{title}</div></div>'
        for idx, title in enumerate(steps)
    )
    st.markdown(f'<div class="card"><div class="stepper">{pills}</div></div>', unsafe_allow_html=True)


def render_old_method_section() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Registro de nuevo metodo analitico</div>', unsafe_allow_html=True)
    cols = st.columns(2, gap="large")
    with cols[0]:
        st.text_input("Codigo Material", placeholder="Ej: USGP-0522", key="codigo_material")
    with cols[1]:
        st.text_input("Numero Metodo", placeholder="Ej: 01-4906", key="numero_metodo")

    st.markdown("#### PDF del metodo antiguo (obligatorio)")
    upload = st.file_uploader(
        "Cargar o arrastrar aqui el PDF del metodo viejo",
        type=["pdf"],
        key="pdf_antiguo",
        label_visibility="collapsed",
    )
    status = "No hay nada adjunto." if upload is None else f"Cargado: **{upload.name}**"
    st.markdown(
        f'<div class="upload-box"><div class="status">{status}</div><div style="margin-top:6px;font-size:13px;color:#4d5d7a;">Adjuntar un archivo</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


def render_new_method_section() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Informacion del metodo analitico</div>', unsafe_allow_html=True)
    cols = st.columns(2, gap="large")
    with cols[0]:
        st.text_input("Nombre del Metodo", placeholder="Ej: Determinacion de pH", key="nombre_metodo")
    with cols[1]:
        st.selectbox(
            "Area",
            ["Seleccionar", "Area de Calidad", "Investigacion y Desarrollo", "Produccion", "Validacion"],
            key="area_metodo",
        )
    cols = st.columns(2, gap="large")
    with cols[0]:
        st.text_input("Version", placeholder="Ej: V00", key="version_metodo")
    with cols[1]:
        st.text_input("Codigo Antiguo", placeholder="Ej: 23424", key="codigo_antiguo")
    st.markdown("</div>", unsafe_allow_html=True)


def render_support_section() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Documentos de soporte</div>', unsafe_allow_html=True)
    cols = st.columns(2, gap="large")
    with cols[0]:
        st.markdown("##### Control de Cambios")
        st.file_uploader("Adjuntar control de cambios", type=["pdf", "docx"], key="control_cambios")
    with cols[1]:
        st.markdown("##### Soportes del metodo (referencia)")
        st.file_uploader(
            "Adjuntar soportes (puedes cargar varios)",
            type=["pdf", "docx", "xlsx"],
            key="soportes_metodo",
            accept_multiple_files=True,
        )
    cols = st.columns(2, gap="large")
    with cols[0]:
        st.markdown("##### Anexos (Side_by_side)")
        st.file_uploader("Adjuntar anexos", type=["pdf", "docx", "xlsx"], key="anexos_side")
    with cols[1]:
        st.markdown("##### Evidencias adicionales")
        st.file_uploader("Adjuntar evidencias", type=["pdf", "png", "jpg"], key="evidencias")
    st.markdown("</div>", unsafe_allow_html=True)


def _persist_upload(uploaded_file, tmp_dir: Path) -> Path:
    target = tmp_dir / uploaded_file.name
    target.write_bytes(uploaded_file.getbuffer())
    return target


def _persist_uploads(files, tmp_dir: Path) -> list[Path]:
    return [_persist_upload(f, tmp_dir) for f in files]


def render_table_section() -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Metodos analiticos</div>', unsafe_allow_html=True)
    search = st.text_input("Buscar por codigo o nombre", placeholder="Ej: USGP o pH", key="search_table")
    cols = st.columns([2, 1])
    with cols[0]:
        st.markdown("Consulta, crea y gestiona metodos analiticos.")
    with cols[1]:
        st.button("+ Nuevo metodo", use_container_width=True, key="nuevo_metodo")

    area_filter = st.selectbox(
        "Area",
        ["Todas", "Area de Calidad", "Investigacion y Desarrollo", "Produccion", "Validacion"],
        key="area_filter",
    )

    data = pd.DataFrame(
        [
            {
                "ID": 24,
                "Doc_cargados": "Adjunto",
                "Codigo": "Prueba FH 2512\nCodigo Material",
                "Nombre": "Prueba FH 2512\nNombre del metodo",
                "Area": "Area de Calidad",
                "Version": "V00",
                "Documentos_Final": "Final",
            },
            {
                "ID": 26,
                "Doc_cargados": "Adjunto",
                "Codigo": "6",
                "Nombre": "Ensayo disolucion",
                "Area": "Area de Calidad",
                "Version": "01",
                "Documentos_Final": "Final",
            },
            {
                "ID": 27,
                "Doc_cargados": "Adjunto",
                "Codigo": "a",
                "Nombre": "Validacion API",
                "Area": "Produccion",
                "Version": "01",
                "Documentos_Final": "Final",
            },
        ]
    )

    if search:
        data = data[data.apply(lambda row: search.lower() in str(row).lower(), axis=1)]
    if area_filter != "Todas":
        data = data[data["Area"] == area_filter]

    st.dataframe(
        data,
        use_container_width=True,
        hide_index=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


def render_cta() -> None:
    cols = st.columns([5, 1.2])
    with cols[1]:
        if st.button("Iniciar migracion", use_container_width=True, key="cta_iniciar"):
            # Preparamos carpeta temporal para guardar los uploads y construir el mensaje para DeepAgents.
            tmp_dir = Path(st.session_state.get("_tmp_upload_dir") or tempfile.mkdtemp(prefix="aura_uploads_"))
            st.session_state["_tmp_upload_dir"] = str(tmp_dir)

            legacy = st.session_state.get("pdf_antiguo")
            control = st.session_state.get("control_cambios")
            sbs = st.session_state.get("anexos_side")
            soporte = st.session_state.get("soportes_metodo")  # puede ser lista
            evidencia = st.session_state.get("evidencias")

            if legacy is None:
                st.error("Falta el PDF del metodo antiguo (obligatorio).")
                return

            payload_lines = []
            legacy_path = _persist_upload(legacy, tmp_dir).as_posix()
            payload_lines.append(f"- Metodo analitico legado: '{legacy_path}'.")

            if control:
                control_path = _persist_upload(control, tmp_dir).as_posix()
                payload_lines.append(f"- Control de cambio: '{control_path}'.")
            if sbs:
                sbs_path = _persist_upload(sbs, tmp_dir).as_posix()
                payload_lines.append(f"- Anexo Side by Side: '{sbs_path}'.")
            if soporte:
                soporte_files = soporte if isinstance(soporte, list) else [soporte]
                soporte_paths = _persist_uploads(soporte_files, tmp_dir)
                for sp in soporte_paths:
                    payload_lines.append(f"- Soportes del metodo: '{sp.as_posix()}'.")
            if evidencia:
                evidencia_path = _persist_upload(evidencia, tmp_dir).as_posix()
                payload_lines.append(f"- Evidencias adicionales: '{evidencia_path}'.")

            content = (
                "Por favor procede con tu flujo de proceso completo, empezando con los llamados "
                "al legacy agent, side by side y control de cambios, luego procede con change_implementation_agent:\n\n"
                + "\n".join(payload_lines)
            )
            message = {"messages": [{"content": content, "type": "human"}]}

            st.success("Payload generado para DeepAgents.")

            with st.spinner("Ejecutando Aura (DeepAgents)..."):
                try:
                    result = am_change_control_agent.invoke(message)
                    st.success("Ejecucion completada. Buscando DOCX final en output/ ...")

                    docx_path = None
                    output_dir = Path("output")
                    if output_dir.exists():
                        docx_files = sorted(output_dir.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
                        if docx_files:
                            docx_path = docx_files[0]

                    if docx_path and docx_path.exists():
                        st.markdown(f"Documento final listo: `{docx_path}`")
                        dcol, link_col = st.columns([2, 1])
                        with dcol:
                            st.download_button(
                                "Descargar Word final",
                                data=docx_path.read_bytes(),
                                file_name=docx_path.name,
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                use_container_width=True,
                            )
                        with link_col:
                            st.markdown(f"[Abrir en carpeta]({docx_path.as_uri()})")
                    else:
                        st.warning("No se encontró un DOCX en la carpeta output/. Revisa el log del agente o ejecuta render_method_docx.")

                    with st.expander("Detalles de ejecucion (payload y respuesta)", expanded=False):
                        st.code(content, language="text")
                        try:
                            st.json(result)
                        except Exception:
                            st.write(result)
                except Exception as exc:  # pragma: no cover - defensivo en UI
                    st.error(f"Fallo al ejecutar el agente: {exc}")
                    st.code(json.dumps(message, indent=2), language="json")


def main() -> None:
    st.markdown('<div class="app-wrapper">', unsafe_allow_html=True)
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    render_hero()
    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
    stepper_col, form_col = st.columns([0.95, 3.05], gap="large")
    with stepper_col:
        render_stepper()
    with form_col:
        render_old_method_section()
        render_new_method_section()
        render_support_section()

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    render_cta()
    render_table_section()

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
