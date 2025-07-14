import streamlit as st
import requests
import time
import json

# --- 1. Configuración y Constantes ---
BACKEND_URL = "http://web:8000/api/v1"
POLLING_INTERVAL_SECONDS = 15
MAX_POLLING_ATTEMPTS = 12

# Pasos de generación con un enfoque técnico y directo
GENERATION_STEPS = [
    ("Enviando la Solicitud...", 0.10, 10),
    ("Iniciando la generación del borrador inicial...", 0.25, 10),
    ("Generando opciones y distractores basados en errores conceptuales...", 0.45, 10),
    ("Ejecutando Auditores de Contenido, Lógica Interna y Políticas de Equidad...", 0.70, 25),
    ("Aplicando refinamientos basados en los hallazgos encontrados...", 0.85, 10),
    ("Evaluando reactivos y preparando su calificación...", 0.95, 10),
]

# --- 2. Funciones Auxiliares y Callbacks ---

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

def display_item_visualization(item_data):
    """Muestra un único reactivo de forma atractiva y funcional."""
    try:
        final_evaluation = item_data.get("final_evaluation")
        cuerpo = item_data.get("cuerpo_item", {})
        clave = item_data.get("clave_y_diagnostico", {})
        if final_evaluation:
            score = final_evaluation.get("score_total")
            areas_mejora = final_evaluation.get("justification", {}).get("areas_de_mejora")
            if score is not None:
                st.metric(label="Calificación de Calidad", value=f"{score} / 100")
                st.progress(score / 100)
            if areas_mejora: st.warning(f"**Áreas de Mejora:** {areas_mejora}")
            st.markdown("---")
        if not cuerpo or not clave:
            st.warning("El reactivo no tiene la estructura de cuerpo o clave esperada.")
            st.json(item_data)
            return
        if cuerpo.get("estimulo"):
            st.write("**Estímulo:**"); st.markdown(f"> {cuerpo['estimulo']}"); st.markdown("---")
        st.write("**Pregunta:**"); st.markdown(f"#### {cuerpo.get('enunciado_pregunta', 'N/A')}")
        st.write("**Opciones:**")
        for opcion in cuerpo.get("opciones", []):
            op_id, op_texto = opcion.get("id", ""), opcion.get("texto", "Opción sin texto")
            if op_id == clave.get("respuesta_correcta_id"): st.success(f"**{op_id.upper()})** {op_texto} (Correcta)")
            else: st.markdown(f"**{op_id.upper()})** {op_texto}")
        with st.expander("Ver retroalimentación detallada de cada opción"):
            for retro in clave.get("retroalimentacion_opciones", []):
                retro_id, justificacion = retro.get('id', '?'), retro.get('justificacion', 'No disponible.')
                if retro.get('es_correcta'): st.info(f"**Retroalimentación Opción {retro_id.upper()}:** {justificacion}")
                else: st.warning(f"**Retroalimentación Opción {retro_id.upper()}:** {justificacion}")
    except Exception as e:
        st.error(f"Ocurrió un error al visualizar este reactivo: {e}")
        st.json(item_data)

# --- 3. Inicialización y Diseño de la Interfaz ---
st.set_page_config(layout="wide", page_title="SIGIE GUI")
st.title("SIGIE: Interfaz de Generación de Ítems")

if 'generating' not in st.session_state:
    reset_to_initial_state()

# --- 4. Lógica de Renderizado Principal ---

if not st.session_state.generating:
    if st.session_state.final_results is not None:
        st.header("Análisis de Reactivos Generados")
        solicitados = st.session_state.n_items_solicitados
        generados = len(st.session_state.final_results)
        st.write(f"Se presenta un total de **{generados}** reactivos generados con éxito.")
        if solicitados > generados:
            st.warning(f"**Atención:** Se solicitaron {solicitados} reactivos, pero solo {generados} cumplieron todos los filtros de calidad.")
        if generados > 0:
            json_string = json.dumps(st.session_state.final_results, indent=4, ensure_ascii=False)
            st.download_button(label="📥 Descargar Lote en formato JSON", data=json_string, file_name=f"lote_{st.session_state.batch_id}.json", mime="application/json")
        st.markdown("---")
        for i, item_data in enumerate(st.session_state.final_results):
             with st.container(border=True):
                 st.subheader(f"Reactivo #{i+1}")
                 display_item_visualization(item_data)
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
            with col_form3: n_opciones_input = st.radio("Número de opciones", [3, 4], index=0, horizontal=True, key="n_opciones_input")
            st.divider()
            submit_button = st.form_submit_button(label="🚀 Generar Lote de Reactivos", on_click=handle_form_submission)

else:
    st.header("Procesando tu Solicitud...")
    if st.session_state.batch_id:
        st.success(f"Solicitud aceptada. Tu lote de generación es: **{st.session_state.batch_id}**")
        progress_bar = st.progress(0.0, "Iniciando proceso...")

        # --- Lógica de "Espera Inteligente" ---
        lote_completado = False
        for message, progress, wait_time in GENERATION_STEPS:
            progress_bar.progress(progress, text=message)

            # Realiza una comprobación de estado después de una espera parcial
            time.sleep(wait_time)
            estado_lote = consultar_estado_del_lote(st.session_state.batch_id)
            if estado_lote and estado_lote.get("is_complete"):
                lote_completado = True
                break # Interrumpe la animación si el lote ya está listo

        # Si el lote no se completó durante la animación, inicia el sondeo regular
        if not lote_completado:
            progress_bar.progress(1.0, text="✨ ¡Proceso creativo finalizado! Verificando estado final en el servidor...")
            for i in range(MAX_POLLING_ATTEMPTS):
                estado_lote = consultar_estado_del_lote(st.session_state.batch_id)
                if estado_lote and estado_lote.get("is_complete"):
                    lote_completado = True
                    break
                time.sleep(POLLING_INTERVAL_SECONDS)

        # Procede a obtener los resultados si el lote se completó en cualquier punto
        if lote_completado:
            VALID_SUCCESS_STATUSES = ["persistence_success", "evaluation_complete"]
            items_a_buscar = [res.get("item_id") for res in estado_lote.get("results", []) if res.get("status") in VALID_SUCCESS_STATUSES]
            final_results_data = []
            with st.spinner(f"Descargando {len(items_a_buscar)} reactivos generados..."):
                for item_id in items_a_buscar:
                    payload = obtener_item_por_id(item_id)
                    if payload: final_results_data.append(payload)
            st.session_state.final_results = final_results_data
            st.session_state.generating = False
            st.balloons()
            st.rerun()
        else:
            st.warning("El proceso está tardando más de lo normal. Si el problema persiste, puedes generar un nuevo lote.")
            st.button("Cancelar y volver a empezar", on_click=reset_to_initial_state)
    else:
        st.error("No se pudo iniciar la generación debido a un error al contactar al servidor.")
        st.button("Reintentar", on_click=reset_to_initial_state)
