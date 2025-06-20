# USER PROMPT – Plantilla general
<!--
Los placeholders entre llaves {asignatura} … {dificultad_prevista} serán
reemplazados dinámicamente por el orquestador.
-->

Genera {n_items} ítem(s) de opción múltiple con una sola respuesta correcta,
cumpliendo las reglas del sistema (ya incluidas en el prompt de sistema).

Parámetros:
- idioma_item: {idioma_item}
- area: {area}
- asignatura: {asignatura}
- tema: {tema}
- contexto_regional: {contexto_regional}
- nivel_destinatario: {nivel_destinatario}
- nivel_cognitivo: {nivel_cognitivo}
- dificultad_prevista: {dificultad_prevista}
- tipo_reactivo: {tipo_reactivo}

<!-- Si existe fragmento_contexto  -->
{fragmento_contexto}

<!-- Si existe recurso_visual como JSON embebido -->
{recurso_visual}

Devuelve solo un array JSON con los ítems.
