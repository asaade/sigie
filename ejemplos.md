{
  "n_items": 1,
  "dominio": {
    "area": "Ciencias Sociales",
    "asignatura": "Historia Universal",
    "tema": "Revolución Francesa"
  },
  "objetivo_aprendizaje": "Ordenar cronológicamente las etapas principales de la Revolución Francesa.",
  "audiencia": {
    "nivel_educativo": "Bachillerato",
    "dificultad_esperada": "media"
  },
  "nivel_cognitivo": "Comprender",
  "formato": {
    "tipo_reactivo": "ordenamiento"
  }
}



1. Ítem que requiere FÓRMULAS MATEMÁTICAS en las opciones

Este payload le pide al sistema un ítem de física donde las opciones de respuesta no son números, sino las ecuaciones mismas, lo que requiere el uso de formato LaTeX.
JSON

{
  "n_items": 1,
  "dominio": {
    "area": "Ciencias Exactas",
    "asignatura": "Física",
    "tema": "Leyes de Newton"
  },
  "objetivo_aprendizaje": "Identificar la expresión matemática correcta que representa la Segunda Ley de Newton.",
  "audiencia": {
    "nivel_educativo": "Bachillerato",
    "dificultad_esperada": "baja"
  },
  "nivel_cognitivo": "Recordar",
  "formato": {
    "tipo_reactivo": "cuestionamiento_directo"
  }
}

2. Ítem que requiere una TABLA en el estímulo

Esta solicitud obligará al generador a crear un estímulo que contenga una tabla en formato Markdown, a partir de la cual el sustentante debe realizar un cálculo.
JSON

{
  "n_items": 1,
  "dominio": {
    "area": "Ciencias Económico-Administrativas",
    "asignatura": "Contabilidad de Costos",
    "tema": "Análisis de Punto de Equilibrio"
  },
  "objetivo_aprendizaje": "Calcular el punto de equilibrio en unidades a partir de una tabla que presenta el precio de venta unitario, el costo variable unitario y los costos fijos totales de una empresa.",
  "audiencia": {
    "nivel_educativo": "Licenciatura en Contaduría",
    "dificultad_esperada": "media"
  },
  "nivel_cognitivo": "Aplicar",
  "formato": {
    "tipo_reactivo": "cuestionamiento_directo"
  }
}

3. Ítem que requiere un GRÁFICO en el estímulo

Esta solicitud instruye al sistema a crear un ítem que no puede ser resuelto sin la interpretación de una gráfica, forzando la generación de un recurso_grafico de tipo prompt_para_imagen.
JSON

{
  "n_items": 1,
  "dominio": {
    "area": "Ciencias Biológicas",
    "asignatura": "Ecología",
    "tema": "Dinámica de Poblaciones"
  },
  "objetivo_aprendizaje": "Analizar una gráfica de crecimiento poblacional logístico (curva S) para identificar la fase en la que la tasa de crecimiento comienza a disminuir debido a factores limitantes.",
  "audiencia": {
    "nivel_educativo": "Universidad (Primeros semestres)",
    "dificultad_esperada": "media-alta"
  },
  "nivel_cognitivo": "Analizar",
  "formato": {
    "tipo_reactivo": "cuestionamiento_directo"
  }
}
