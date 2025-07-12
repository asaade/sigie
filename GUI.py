import streamlit as st
import requests
import time

# --- URLs del API ---
API_BASE_URL = "http://127.0.0.1:8000"
API_V1_STR = "/api/v1"
GENERATE_URL = f"{API_BASE_URL}{API_V1_STR}/items/generate"
BATCH_STATUS_URL = f"{API_BASE_URL}{API_V1_STR}/items/batch/"
ITEM_URL = f"{API_BASE_URL}{API_V1_STR}/items/"

# --- Opciones predefinidas y funciones de formato ---
NIVELES_COGNITIVOS = ["Recordar", "Comprender", "Aplicar", "Analizar", "Evaluar", "Crear"]
DIFICULTAD = ["Baja", "Media", "Alta"]
NIVELES_EDUCATIVOS = ["Secundaria", "Bachillerato", "Licenciatura"]
TIPOS_REACTIVO = ["cuestionamiento_directo", "completamiento", "ordenamiento", "relacion_de_elementos"]
NUMERO_DE_OPCIONES = [3, 4]

# --- Funciones para interactuar con el API ---
def start_generation(request_body):
    try:
        response = requests.post(GENERATE_URL, json=request_body, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"FALLO en la conexión con el API: {e}")
        st.warning("Verifica que el servidor backend (FastAPI) esté corriendo y accesible en la URL configurada.")
        return None

def check_batch_status(batch_id):
    try:
        response = requests.get(f"{BATCH_STATUS_URL}{batch_id}", timeout=10)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error al consultar el estado: {e}")
        return {"error": str(e)}

def get_item_payload(item_id):
    try:
        response = requests.get(f"{ITEM_URL}{item_id}", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return None

def format_tipo_reactivo(opcion_snake_case):
    """Convierte 'snake_case' a 'Title Case' para una mejor visualización."""
    return opcion_snake_case.replace("_", " ").capitalize()

# --- Inicialización del Estado de la Sesión ---
if 'app_state' not in st.session_state:
    st.session_state.app_state = 'initial'
    st.session_state.batch_id = None
    st.session_state.item_results_status = []
    st.session_state.final_payloads = []
    st.session_state.polling_attempts = 0

# --- Título Principal ---
st.title("✍️ SIGIE: Generador de Ítems")

# --- Lógica de renderizado según el estado de la app ---

if st.session_state.app_state == 'initial':
    st.markdown("Complete este formulario para generar un nuevo lote de reactivos.")
    with st.form(key="generation_form"):
        st.header("1. Parámetros de la Solicitud")
        st.subheader("Dominio Temático")
        col1, col2, col3 = st.columns(3)
        with col1:
            dominio_area = st.text_input("Área *", value="Ciencias")
        with col2:
            dominio_asignatura = st.text_input("Asignatura *", value="Física")
        with col3:
            dominio_tema = st.text_input("Tema *", value="Leyes de Newton")
        st.subheader("Objetivo y Audiencia")
        objetivo_aprendizaje = st.text_area("Objetivo de Aprendizaje *", value="El estudiante aplicará la segunda ley de Newton para resolver problemas de dinámica.")
        col_aud_1, col_aud_2, col_aud_3 = st.columns(3)
        with col_aud_1:
            audiencia_nivel = st.selectbox("Nivel Educativo *", options=NIVELES_EDUCATIVOS)
        with col_aud_2:
            audiencia_dificultad = st.selectbox("Dificultad Esperada *", options=DIFICULTAD)
        with col_aud_3:
            nivel_cognitivo = st.selectbox("Nivel Cognitivo (Bloom) *", options=NIVELES_COGNITIVOS, index=2)

        st.subheader("Especificaciones")
        spec_col1, spec_col2, spec_col3 = st.columns([2, 1, 1])
        with spec_col1:
            tipo_reactivo = st.selectbox("Tipo de Reactivo *", options=TIPOS_REACTIVO, format_func=format_tipo_reactivo, help="Define la estructura del reactivo.")
        with spec_col3:
            numero_opciones = st.selectbox(" # de Opciones *", options=NUMERO_DE_OPCIONES, index=0, help="Número de opciones de respuesta.")
        with spec_col3:
            n_items = st.number_input(" # de Reactivos *", min_value=1, max_value=10, value=1, help="Número de variaciones de reactivos a generar.")

        st.divider()
        submitted = st.form_submit_button("🚀 Generar Reactivos", type="primary", use_container_width=True)

        if submitted:
            if not all([dominio_area, dominio_asignatura, dominio_tema, objetivo_aprendizaje]):
                st.error("Por favor, complete todos los campos obligatorios (*).")
            else:
                request_body = {
                    "n_items": n_items,
                    "dominio": {"area": dominio_area, "asignatura": dominio_asignatura, "tema": dominio_tema},
                    "objetivo_aprendizaje": objetivo_aprendizaje,
                    "audiencia": {"nivel_educativo": audiencia_nivel, "dificultad_esperada": audiencia_dificultad.lower()},
                    "nivel_cognitivo": nivel_cognitivo,
                    "formato": {
                        "tipo_reactivo": tipo_reactivo,
                        "numero_opciones": numero_opciones
                    }
                }
                api_response = start_generation(request_body)
                if api_response and api_response.get("batch_id"):
                    st.session_state.batch_id = api_response.get("batch_id")
                    st.session_state.app_state = 'processing'
                    st.session_state.polling_attempts = 0
                    st.rerun()
                else:
                    st.error("No se recibió un 'batch_id' válido. La aplicación no puede continuar.")

elif st.session_state.app_state == 'processing':
    st.info(f"⚙️ Procesando lote. ID: `{st.session_state.batch_id}`")
    progress_bar = st.progress(0, "Esperando al servidor...")
    max_attempts = 10
    time.sleep(30)
    while st.session_state.polling_attempts < max_attempts:
        status_data = check_batch_status(st.session_state.batch_id)
        if status_data is None:
            st.session_state.polling_attempts += 1
            progress_bar.progress(st.session_state.polling_attempts / max_attempts, f"No se encuentra el lote. Reintentando... ({st.session_state.polling_attempts}/{max_attempts})")
            time.sleep(15)
            continue
        if status_data.get("error"):
            st.error(f"Error de conexión durante el sondeo: {status_data['error']}")
            break
        prog = status_data.get('processed_items', 0) / status_data.get('total_items', 1)
        progress_bar.progress(prog, f"Progreso: {status_data.get('processed_items', 0)} de {status_data.get('total_items', 0)} ítems procesados.")
        if status_data.get("is_complete"):
            st.session_state.item_results_status = status_data.get("results", [])
            st.session_state.app_state = 'fetching_results'
            st.rerun()
        time.sleep(10)
    if st.session_state.polling_attempts >= max_attempts:
        st.error(f"No se pudo encontrar el lote {st.session_state.batch_id} después de {max_attempts} intentos.")
        if st.button("⬅️ Volver al inicio"):
            st.session_state.app_state = 'initial'
            st.rerun()

elif st.session_state.app_state == 'fetching_results':
    st.info("Generación completada. Obteniendo los reactivos finales...")
    final_payloads = []
    VALID_SUCCESS_STATUSES = ["PERSISTENCE_SUCCESS", "evaluation_complete"]
    successful_items = [item for item in st.session_state.item_results_status if item.get('status') in VALID_SUCCESS_STATUSES]
    if not successful_items:
        st.session_state.final_payloads = []
        st.session_state.app_state = 'results_ready'
        st.rerun()
    else:
        progress_bar = st.progress(0, "Descargando reactivos...")
        for i, item_status in enumerate(successful_items):
            item_id = item_status.get("item_id")
            if item_id:
                payload = get_item_payload(item_id)
                if payload:
                    final_payloads.append(payload)
            progress_bar.progress((i + 1) / len(successful_items))
        st.session_state.final_payloads = final_payloads
        st.session_state.app_state = 'results_ready'
        st.rerun()

elif st.session_state.app_state == 'results_ready':
    st.success("✅ ¡Proceso finalizado!")
    st.header(f"Resultados del Lote: `{st.session_state.batch_id}`")
    if st.session_state.final_payloads:
        st.write(f"Se generaron **{len(st.session_state.final_payloads)}** reactivos con éxito.")
        for i, payload in enumerate(st.session_state.final_payloads):
            with st.container(border=True):
                st.markdown(f"**Reactivo {i+1}**")
                cuerpo = payload.get("cuerpo_item", {})
                clave = payload.get("clave_y_diagnostico", {})
                if cuerpo.get("estimulo"):
                    st.markdown(f"**Estímulo:** {cuerpo['estimulo']}")
                st.markdown(f"**Pregunta:** {cuerpo.get('enunciado_pregunta', 'N/A')}")
                for opcion in cuerpo.get("opciones", []):
                    if opcion.get("id") == clave.get("respuesta_correcta_id"):
                        st.success(f"✔️ {opcion.get('texto', '')} (Respuesta Correcta)")
                    else:
                        st.write(f"⚪ {opcion.get('texto', '')}")
                with st.expander("Ver retroalimentación detallada"):
                    for retro in clave.get("retroalimentacion_opciones", []):
                        st.markdown(f"**Opción {retro.get('id')}:** {retro.get('justificacion')}")
    else:
        st.warning("El proceso de generación finalizó, pero no se produjeron reactivos válidos.")
        st.info("Esto puede deberse a una falla temporal del servicio de IA o a que los reactivos no pasaron los filtros de calidad.")
    if st.button("⬅️ Generar un nuevo lote"):
        for key in st.session_state.keys():
            if key != 'app_state':
                del st.session_state[key]
        st.session_state.app_state = 'initial'
        st.rerun()
