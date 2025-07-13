import streamlit as st
import requests
import time
import json

# --- 1. Configuración y Constantes ---
BACKEND_URL = "http://web:8000/api/v1"
POLLING_INTERVAL_SECONDS = 12
MAX_POLLING_ATTEMPTS = 12

GENERATION_STEPS = [
    ("Ejecutando Agente de Validación de Solicitud...", 0.10, 15),
    ("Iniciando Agente de Dominio: generando borrador inicial...", 0.25, 30),
    ("Generando opciones y distractores basados en errores conceptuales...", 0.45, 30),
    ("Ejecutando Auditores de Contenido, Lógica Interna y Políticas de Equidad...", 0.70, 25),
    ("Aplicando refinamientos basados en los hallazgos encontrados...", 0.85, 20),
    ("Evaluando reactivos y preparando su calificación...", 0.95, 15),
]

# --- 2. Funciones de Lógica y Callbacks ---

def handle_form_submission():
    """Callback que construye los parámetros desde st.session_state y llama al backend."""
    params = {
        "n_items": st.session_state.n_items_input,
        "dominio": {"area": st.session_state.area_input, "asignatura": st.session_state.asignatura_input, "tema": st.session_state.tema_input},
        "objetivo_aprendizaje": st.session_state.objetivo_input,
        "audiencia": {"nivel_educativo": st.session_state.audiencia_nivel_input, "dificultad_esperada": st.session_state.audiencia_dificultad_input},
        "nivel_cognitivo": st.session_state.nivel_cognitivo_input,
        "formato": {"tipo_reactivo": st.session_state.tipo_reactivo_input, "numero_opciones": st.session_state.n_opciones_input}
    }
    st.session_state.n_items_solicitados = params["n_items"]
    try:
        response = requests.post(f"{BACKEND_URL}/items/generate", json=params, timeout=15)
        response.raise_for_status()
        st.session_state.batch_id = response.json().get("batch_id")
        st.session_state.generating = True
    except requests.exceptions.RequestException as e:
        st.error(f"Error al contactar al servidor de SIGIE: {e}")
        st.session_state.generating = False

def consultar_estado_del_lote(batch_id):
    """Consulta el estado de un lote en el backend."""
    try:
        response = requests.get(f"{BACKEND_URL}/items/batch/{batch_id}", timeout=10)
        if response.status_code == 404: return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException: return None

def obtener_item_por_id(item_id):
    """Obtiene el payload completo de un ítem por su ID."""
    try:
        response = requests.get(f"{BACKEND_URL}/items/{item_id}", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException: return None

def reset_to_initial_state():
    """Reinicia el estado de la sesión para una nueva generación."""
    st.session_state.generating = False
    st.session_state.batch_id = None
    st.session_state.final_results = None
    st.session_state.n_items_solicitados = 0

# --- 3. Funciones de Visualización (Refactorizadas) ---

def display_item_view(cuerpo, clave, item_id):
    """Muestra la vista limpia del reactivo, como lo vería un sustentante."""
    if cuerpo.get("estimulo"):
        st.markdown("**Estímulo:**")
        st.info(cuerpo['estimulo'])
    st.markdown("**Pregunta:**")
    st.markdown(f"*{cuerpo.get('enunciado_pregunta', 'N/A')}*")

    opciones_dict = {f"{opt.get('id', '').upper()}) {opt.get('texto', '')}": opt.get('id') for opt in cuerpo.get("opciones", [])}
    st.radio("Opciones:", opciones_dict.keys(), key=f"selection_{item_id}", index=None, label_visibility="collapsed")


def display_psychometric_analysis(clave, final_evaluation):
    """Muestra el análisis de calidad: score, áreas de mejora y retroalimentación."""
    if final_evaluation:
        score = final_evaluation.get("score_total")
        areas_mejora = final_evaluation.get("justification", {}).get("areas_de_mejora")
        if score is not None:
            st.metric(label="Calificación de Calidad del Ítem", value=f"{score} / 100")
            st.progress(score / 100)
        if areas_mejora:
            st.warning(f"**Áreas de Mejora Identificadas:** {areas_mejora}")

    st.markdown("---")
    st.markdown("##### Retroalimentación por Opción")
    for retro in clave.get("retroalimentacion_opciones", []):
        retro_id = retro.get('id', '?').upper()
        justificacion = retro.get('justificacion', 'No disponible.')
        if retro.get('es_correcta'):
            st.success(f"**Opción {retro_id} (Correcta):** {justificacion}")
        else:
            st.error(f"**Opción {retro_id} (Distractor):** {justificacion}")

def display_construction_details(item_data):
    """Muestra los parámetros de entrada que originaron el reactivo."""
    st.markdown("##### Parámetros de Solicitud")
    dominio = item_data.get("dominio", {})
    audiencia = item_data.get("audiencia", {})
    st.json({
        "Dominio": f"{dominio.get('area', 'N/A')} > {dominio.get('asignatura', 'N/A')} > {dominio.get('tema', 'N/A')}",
        "Objetivo de Aprendizaje": item_data.get("objetivo_aprendizaje"),
        "Audiencia": f"{audiencia.get('nivel_educativo')} - Dificultad {audiencia.get('dificultad_esperada')}",
        "Nivel Cognitivo (Bloom)": item_data.get("nivel_cognitivo"),
    })

def display_item_with_tabs(item_data):
    """Función principal que orquesta la visualización de un ítem usando pestañas."""
    try:
        item_id = item_data.get("item_id", str(time.time()))
        final_evaluation = item_data.get("final_evaluation")
        cuerpo = item_data.get("cuerpo_item", {})
        clave = item_data.get("clave_y_diagnostico", {})

        if not cuerpo or not clave:
            st.warning("El reactivo no tiene la estructura de datos completa.")
            st.json(item_data)
            return

        tab1, tab2, tab3 = st.tabs(["Vista del Reactivo", "Análisis de Opciones", "Detalles de Construcción"])
        with tab1:
            display_item_view(cuerpo, clave, item_id)
        with tab2:
            display_psychometric_analysis(clave, final_evaluation)
        with tab3:
            display_construction_details(item_data)

    except Exception as e:
        st.error(f"Ocurrió un error al visualizar este reactivo: {e}")
        st.json(item_data)

# --- 4. Inicialización y Diseño de la Interfaz ---
st.set_page_config(layout="wide", page_title="SIGIE GUI")
st.title("SIGIE: Interfaz de Generación y Análisis de Ítems")

if 'generating' not in st.session_state:
    reset_to_initial_state()

# --- 5. Lógica de Renderizado Principal ---

if not st.session_state.generating:
    if st.session_state.final_results is not None:
        st.header("Resultados de la Generación")
        solicitados = st.session_state.n_items_solicitados
        generados = len(st.session_state.final_results)

        st.write(f"Se generó un total de **{generados}** reactivos de los **{solicitados}** solicitados.")
        if solicitados > generados:
            st.warning(f"**Atención:** {solicitados - generados} reactivo(s) no cumplieron los filtros de calidad y fueron descartados.")

        if generados > 0:
            json_string = json.dumps(st.session_state.final_results, indent=4, ensure_ascii=False)
            st.download_button(label="📥 Descargar Lote en formato JSON", data=json_string, file_name=f"lote_{st.session_state.batch_id}.json", mime="application/json")

        st.markdown("---")

        for i, item_data in enumerate(st.session_state.final_results):
             with st.container(border=True):
                 st.subheader(f"Análisis del Reactivo #{i+1}")
                 display_item_with_tabs(item_data)

        st.button("Generar un Nuevo Lote", on_click=reset_to_initial_state, use_container_width=True, type="primary")

    else:
        st.header("Parámetros para la Generación de Reactivos")
        with st.form(key="generation_form"):
            st.markdown("##### 1. Objetivo y Dominio")
            objetivo_input = st.text_area("Objetivo de Aprendizaje", "El estudiante aplicará la segunda ley de Newton para resolver problemas de dinámica.", height=100, key="objetivo_input", help="Describe qué habilidad o conocimiento debe medir el reactivo.")
            col1, col2, col3 = st.columns(3)
            with col1: area_input = st.text_input("Área de Dominio", "Ciencias", key="area_input")
            with col2: asignatura_input = st.text_input("Asignatura", "Física", key="asignatura_input")
            with col3: tema_input = st.text_input("Tema Específico", "Leyes de Newton", key="tema_input")

            st.markdown("##### 2. Audiencia y Complejidad")
            col_aud1, col_aud2 = st.columns(2)
            with col_aud1: audiencia_nivel_input = st.selectbox("Nivel educativo", ["Secundaria", "Bachillerato", "Licenciatura"], key="audiencia_nivel_input")
            with col_aud2: audiencia_dificultad_input = st.selectbox("Dificultad esperada", ["Baja", "Media", "Alta"], index=1, key="audiencia_dificultad_input")

            nivel_cognitivo_input = st.selectbox("Nivel Cognitivo (Taxonomía de Bloom)", ["Recordar", "Comprender", "Aplicar", "Analizar", "Evaluar", "Crear"], index=2, key="nivel_cognitivo_input")

            st.markdown("##### 3. Formato y Cantidad")
            col_form1, col_form2, col_form3 = st.columns(3)
            with col_form1: n_items_input = st.number_input("Número de reactivos", 1, 5, 1, key="n_items_input")
            with col_form2: tipo_reactivo_input = st.selectbox("Tipo de reactivo", ["cuestionamiento_directo", "completamiento"], key="tipo_reactivo_input")
            with col_form3: n_opciones_input = st.radio("Número de opciones", [3, 4], index=1, horizontal=True, key="n_opciones_input")

            st.divider()
            submit_button = st.form_submit_button(label="🚀 Generar Lote de Reactivos", on_click=handle_form_submission)

else:
    st.header("Procesando tu Solicitud...")
    if st.session_state.batch_id:
        st.success(f"Solicitud aceptada. Tu lote de generación es: **{st.session_state.batch_id}**")
        progress_bar = st.progress(0.0, "Iniciando proceso...")

        for message, progress, wait_time in GENERATION_STEPS:
            progress_bar.progress(progress, text=message)
            time.sleep(wait_time)

        progress_bar.progress(1.0, text="✨ ¡Proceso creativo finalizado! Verificando estado final en el servidor...")

        final_results_data = []
        for i in range(MAX_POLLING_ATTEMPTS):
            estado_lote = consultar_estado_del_lote(st.session_state.batch_id)
            if estado_lote and estado_lote.get("is_complete"):
                VALID_SUCCESS_STATUSES = ["persistence_success", "evaluation_complete"]
                items_a_buscar = [res.get("item_id") for res in estado_lote.get("results", []) if res.get("status") in VALID_SUCCESS_STATUSES]

                with st.spinner(f"Descargando {len(items_a_buscar)} reactivos generados..."):
                    for item_id in items_a_buscar:
                        payload = obtener_item_por_id(item_id)
                        if payload: final_results_data.append(payload)

                st.session_state.final_results = final_results_data
                st.session_state.generating = False
                st.balloons()
                st.rerun()

            time.sleep(POLLING_INTERVAL_SECONDS)

        st.warning("El proceso está tardando más de lo normal. Si el problema persiste, puedes generar un nuevo lote.")
        st.button("Cancelar y volver a empezar", on_click=reset_to_initial_state)
    else:
        st.error("No se pudo iniciar la generación debido a un error al contactar al servidor.")
        st.button("Reintentar", on_click=reset_to_initial_state)
