"""
Modelo de datos mejorado para extracción estructurada de métodos analíticos farmacéuticos.
Versión 2.2 - SST dentro de Procedimiento + preservación verbatim.

Cambios principales:
1. Añadido modelo Calculos con fórmula y definición de variables
2. Mejorado OrdenInyeccion con campo anexo_no
3. Notas simplificadas como List[str] (sin numeración)
4. Corregido CondicionesCromatograficas en TestSolution
5. **SST ahora está DENTRO de Procedimiento** (procedimiento.sst)
6. Añadido modelo TablaParametros para uniformidad de contenido
7. Eliminadas todas las numeraciones internas (numero_subseccion, numero_nota)
8. Énfasis en preservación VERBATIM del texto para generación de DOCX
"""

from __future__ import annotations
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


#######################################################################################
# Modelos auxiliares
#######################################################################################

# NOTA: Las notas se capturan como listas de strings simples (List[str])
# Se eliminó el modelo Nota con numero_nota para simplificar la estructura


class CondicionCromatografica(BaseModel):
    """Par nombre-valor de una condición cromatográfica individual."""
    nombre_condicion: str = Field(
        ...,
        description="Nombre de la condición cromatográfica. Ejemplos: 'Modo', 'Columna', 'Temperatura de la columna', 'Fase Móvil', 'Detector UV/DAD', 'Celda', 'Flujo', 'Volumen de Inyección', 'Tiempo de Corrida'"
    )
    valor_condicion: str = Field(
        ...,
        description="Valor de la condición cromatográfica. Ejemplos: 'HPLC', 'C18 (250 x 4.6) mm; 5 µm', '25°C', 'Metanol: Agua (1:3). Ver preparación ítem 7.5.2.1', '243 nm', '10 µL', '10 minutos'"
    )


class ProporcionesTiempo(BaseModel):
    """Fila de una tabla de gradiente de fase móvil."""
    tiempo: float = Field(..., description="Tiempo en minutos")
    proporcion_a: float = Field(..., description="Proporción o porcentaje de fase móvil A")
    proporcion_b: float = Field(..., description="Proporción o porcentaje de fase móvil B")


class CondicionesCromatograficas(BaseModel):
    """Conjunto completo de condiciones cromatográficas de una prueba HPLC."""
    condiciones: List[CondicionCromatografica] = Field(
        ...,
        description="Lista de condiciones cromatográficas como pares nombre-valor"
    )
    tabla_gradiente: Optional[List[ProporcionesTiempo]] = Field(
        None,
        description="Tabla de gradiente de fase móvil si aplica (tiempos vs proporciones A/B)"
    )
    solventes_fase_movil: Optional[List[str]] = Field(
        None,
        description=(
            "Lista de solventes que componen la fase móvil, extraídos de los encabezados de la tabla de gradiente "
            "o de la descripción de Fase Móvil A/B. "
            "Ejemplos: ['Agua (grado HPLC)', 'Acetonitrilo (grado HPLC)'], ['Metanol', 'Buffer fosfato pH 3.0'], "
            "['Agua con 0.1% TFA', 'Acetonitrilo con 0.1% TFA']. "
            "Extraer el nombre completo del solvente incluyendo grado o modificadores si se especifican."
        )
    )
    notas: Optional[List[str]] = Field(
        None,
        description="Lista de notas como texto simple (ej: ['El tamaño del cilindro...', 'Las proporciones a preparar...'])"
    )


#######################################################################################
# Modelo de Soluciones
#######################################################################################

class Solucion(BaseModel):
    """Representa una solución descrita en el método analítico."""
    nombre_solucion: str = Field(
        ...,
        description=(
            "Nombre de la solución SIN numeración. "
            "Ejemplos: 'Fase móvil', 'Solución Stock Estándar', 'Solución Estándar', "
            "'Solución Stock Muestra', 'Solución Muestra', 'Solución Amortiguadora', "
            "'Solución Diluyente', 'Fase Móvil A', 'Fase Móvil B', 'Solución Estándar de Sensibilidad', "
            "'Solución Estándar Mixto'. NO incluir números de sección (7.5.2.1, etc.)."
        )
    )
    preparacion_solucion: str = Field(
        ...,
        description=(
            "⚠️ COPIAR VERBATIM. Texto COMPLETO de la preparación exactamente como aparece, "
            "incluyendo saltos de línea, símbolos (µm, °C, mL), paréntesis y referencias. "
            "NO resumir, NO corregir ortografía, NO cambiar unidades. "
            "Incluir la concentración teórica si aparece (ej: 'Esta solución contiene una concentración teórica de...')."
        )
    )
    concentracion_teorica: Optional[str] = Field(
        None,
        description="Concentración teórica de la solución si se especifica (ej: '0.5 mg ó 500 µg de Acetaminofén por mL')"
    )
    notas: Optional[List[str]] = Field(
        None,
        description="Notas específicas relacionadas con esta solución (sin número de nota, solo texto)"
    )


#######################################################################################
# Modelo de Orden de Inyección / SST
#######################################################################################

class OrdenInyeccion(BaseModel):
    """Fila de la tabla de Orden de Inyección y Test de Adecuabilidad del Sistema (SST)."""
    solucion: str = Field(
        ...,
        description="Nombre de la solución a inyectar (ej: 'Fase Móvil', 'Solución Estándar (1 ó 2)', 'Solución Muestra')"
    )
    numero_inyecciones: str = Field(
        ...,
        description="Número de inyecciones. Puede ser un número o texto como '1 (Por cada réplica)', '5', '6'"
    )
    test_adecuabilidad: Optional[str] = Field(
        None,
        description=(
            "Nombre del test de adecuabilidad aplicado. Ejemplos: 'N.A.', 'Desviación Estándar Relativa de las Áreas (RSD)', "
            "'Asimetría', 'Factor de Exactitud', 'Señal/Ruido (S/N)', 'Resolución'. "
            "Si hay múltiples tests, separarlos con ';'"
        )
    )
    especificacion: Optional[str] = Field(
        None,
        description=(
            "Especificación o criterio del test. Ejemplos: 'N.A.', 'El valor de RSD debe ser menor o igual a 2.0%', "
            "'El factor USP tailing no debe ser mayor de 2.0', 'Ver ítem 7.5.5'"
        )
    )
    anexo_no: Optional[str] = Field(
        None,
        description="Número de anexo de referencia si aplica (ej: '1', '2', 'N.A.')"
    )


class ProcedimientoSST(BaseModel):
    """Sección de Procedimiento y Test de Adecuabilidad del Sistema."""
    descripcion: Optional[str] = Field(
        None,
        description="Texto introductorio del procedimiento SST (ej: 'Realizar el orden de Inyección según lo establecido en la siguiente tabla:')"
    )
    tabla_orden_inyeccion: List[OrdenInyeccion] = Field(
        ...,
        description="Tabla de orden de inyección con tests de adecuabilidad"
    )
    notas: Optional[List[str]] = Field(
        None,
        description="Notas asociadas al procedimiento SST"
    )


#######################################################################################
# Modelo de Cálculos
#######################################################################################

class VariableCalculo(BaseModel):
    """Definición de una variable usada en una fórmula de cálculo."""
    simbolo: str = Field(
        ...,
        description="Símbolo de la variable (ej: 'ru', 'rs', 'Ws', '[ ]', 'Wm', 'Wp', 'T')"
    )
    definicion: str = Field(
        ...,
        description="Definición de la variable tal como aparece en el documento"
    )


class Calculos(BaseModel):
    """Sección de cálculos de una prueba analítica."""
    formulas: List[str] = Field(
        ...,
        description=(
            "Lista de fórmulas de cálculo tal como aparecen en el documento. "
            "Copiar la fórmula completa incluyendo el resultado esperado "
            "(ej: 'mg Acetaminofen/tab = ru x Ws(mg) x 2(mL) x ...')"
        )
    )
    variables: Optional[List[VariableCalculo]] = Field(
        None,
        description="Lista de definiciones de variables que aparecen en la sección 'Dónde:'"
    )
    instrucciones_adicionales: Optional[str] = Field(
        None,
        description="Instrucciones adicionales de cálculo (ej: 'Para expresar el resultado en porcentaje...')"
    )
    notas: Optional[List[str]] = Field(
        None,
        description="Notas asociadas a los cálculos"
    )


#######################################################################################
# Modelo de Procedimiento
#######################################################################################

class TiempoRetencion(BaseModel):
    """Tiempo de retención relativo de un compuesto (para tablas de impurezas)."""
    nombre: str = Field(..., description="Nombre del compuesto o impureza")
    tiempo_relativo_retencion: Optional[str] = Field(None, description="Tiempo relativo de retención (TRR)")
    factor_respuesta_relativa: Optional[str] = Field(None, description="Factor de respuesta relativa (FRR)")


class Procedimiento(BaseModel):
    """
    Procedimiento de una prueba analítica.
    Incluye el texto del procedimiento general y la sección SST si existe.
    """
    texto: str = Field(
        ...,
        description=(
            "⚠️ COPIAR VERBATIM - NO PARAFRASEAR. "
            "Texto EXACTO del procedimiento tal como aparece en el documento. "
            "Mantener la estructura original (A., B., C., D. o numeración). "
            "Mantener saltos de línea y formato. "
            "EXCLUIR preparación de soluciones (van en 'soluciones'). "
            "EXCLUIR fórmulas de cálculo (van en 'calculos'). "
            "Si el texto está interrumpido por ruido del documento, unirlo pero SIN cambiar las palabras."
        )
    )
    sst: Optional[ProcedimientoSST] = Field(
        None,
        description="Sección de Test de Adecuabilidad del Sistema (SST) con tabla de orden de inyección si existe"
    )
    tiempo_retencion: Optional[List[TiempoRetencion]] = Field(
        None,
        description="Tabla de tiempos de retención relativos si aplica (para pruebas de impurezas)"
    )
    notas: Optional[List[str]] = Field(
        None,
        description="Notas del procedimiento que NO corresponden a SST ni Cálculos"
    )


#######################################################################################
# Modelo de Criterios de Aceptación
#######################################################################################

class TablaCriteriosAceptacion(BaseModel):
    """Fila de tabla de criterios de aceptación por etapas (para uniformidad de contenido)."""
    etapa: str = Field(..., description="Etapa (ej: 'S1', 'S2', 'L1', 'L2')")
    unidades_analizadas: Optional[str] = Field(None, description="Número de unidades analizadas")
    criterio_aceptacion: str = Field(..., description="Criterio de aceptación para esta etapa")


class CriterioAceptacion(BaseModel):
    """Criterio de aceptación de una prueba analítica."""
    texto: str = Field(
        ...,
        description=(
            "Texto del criterio de aceptación tal como aparece en el documento. "
            "Puede incluir rangos, valores máximos/mínimos, y unidades. "
            "Ejemplos: '90.0 – 110.0%; 900.0 – 1,100.0 mg/tab', '4-aminofenol; 0.15% Máximo', '10 – 30 kP'"
        )
    )
    tipo_criterio: Optional[Literal["Liberación", "Estabilidad", "Liberación y Estabilidad"]] = Field(
        None,
        description="Tipo de criterio: solo Liberación, solo Estabilidad, o ambos"
    )
    tabla_criterios: Optional[List[TablaCriteriosAceptacion]] = Field(
        None,
        description="Tabla de criterios por etapas si aplica (para uniformidad de contenido/disolución)"
    )
    notas: Optional[List[str]] = Field(
        None,
        description="Notas asociadas al criterio de aceptación"
    )


#######################################################################################
# Modelo de Tabla de Parámetros (para Uniformidad de Contenido)
#######################################################################################

class FilaParametro(BaseModel):
    """Fila de una tabla de parámetros de uniformidad."""
    variable: str = Field(..., description="Símbolo de la variable (ej: 'X̄', 'χ₁, χ₂, ..., χₙ', 'N', 'K', 'S', 'RSD')")
    definicion: str = Field(..., description="Definición de la variable")
    condiciones: Optional[str] = Field(None, description="Condiciones de aplicación")
    valor: Optional[str] = Field(None, description="Valor o fórmula")


class TablaParametros(BaseModel):
    """Tabla de parámetros de uniformidad de contenido."""
    titulo: Optional[str] = Field(None, description="Título de la tabla (ej: 'Tabla 1. Parámetros uniformidad de contenido')")
    filas: List[FilaParametro] = Field(..., description="Filas de la tabla de parámetros")


#######################################################################################
# Modelo principal de extracción: TestSolution
#######################################################################################

class TestSolution(BaseModel):
    """
    Modelo principal para una prueba/test analítico extraído del método.
    Diseñado para ser general y capturar diferentes tipos de pruebas:
    - HPLC (Valoración, Impurezas, Identificación)
    - Pruebas físicas (Dureza, Espesor, Peso Promedio)
    - Pruebas con fórmula (Uniformidad, Pérdida por Secado)
    """
    
    # Identificación de la sección
    section_id: str = Field(
        ...,
        description="Número de la sección (ej: '7.1', '7.2', '7.5', '7.6')"
    )
    section_title: str = Field(
        ...,
        description=(
            "Título completo de la sección tal como aparece. "
            "Ejemplos: 'DESCRIPCIÓN (INTERNA)', 'VALORACIÓN ACETAMINOFEN (Cubierta) (USP)', "
            "'IMPUREZAS INDIVIDUALES (4-Aminofenol) (Cubierta) (USP)'. "
            "Si no se identifica, usar 'Por definir'."
        )
    )
    test_name: str = Field(
        ...,
        description=(
            "Nombre descriptivo del test incluyendo el analito. "
            "Ejemplos: 'Valoración de Acetaminofén', 'Impurezas de 4-Aminofenol', 'Dureza del Núcleo'. "
            "Si no se identifica, usar 'Por definir'."
        )
    )
    test_type: Literal[
        "Descripción",
        "Identificación",
        "Valoración",
        "Impurezas",
        "Peso promedio",
        "Disolución",
        "Uniformidad de contenido",
        "Uniformidad de unidades de dosificación",
        "Control microbiológico",
        "Humedad",
        "Dureza",
        "Espesores",
        "Pérdida por Secado",
        "Otros análisis"
    ] = Field(
        ...,
        description=(
            "Tipo de prueba analítica. Elegir el más apropiado. "
            "Usar 'Otros análisis' si no encaja en ninguna categoría."
        )
    )
    
    # Componentes de la prueba
    condiciones_cromatograficas: Optional[CondicionesCromatograficas] = Field(
        None,
        description="Condiciones cromatográficas si es una prueba HPLC/GC"
    )
    soluciones: Optional[List[Solucion]] = Field(
        None,
        description="Lista de soluciones utilizadas en esta prueba"
    )
    procedimiento: Optional[Procedimiento] = Field(
        None,
        description="Procedimiento de la prueba (incluye SST si existe)"
    )
    calculos: Optional[Calculos] = Field(
        None,
        description="Sección de cálculos con fórmulas y definición de variables"
    )
    tabla_parametros: Optional[TablaParametros] = Field(
        None,
        description="Tabla de parámetros adicional si aplica (ej: para uniformidad de contenido)"
    )
    criterio_aceptacion: Optional[CriterioAceptacion] = Field(
        None,
        description="Criterio de aceptación de la prueba"
    )
    
    # Elementos adicionales
    equipos: Optional[List[str]] = Field(
        None,
        description="Equipos mencionados explícitamente en esta prueba (ej: 'Cromatógrafo Líquido', 'Durómetro', 'Vernier')"
    )
    reactivos: Optional[List[str]] = Field(
        None,
        description="Reactivos específicos de esta prueba (ej: 'Metanol HPLC', 'Ácido trifluoroacético')"
    )
    referencias: Optional[List[str]] = Field(
        None,
        description="Referencias a otras secciones del documento (ej: 'Ver ítem 7.5', 'USP', 'INTERNA')"
    )


#######################################################################################
# Contenedor principal
#######################################################################################

class TestSolutions(BaseModel):
    """Contenedor para lista de pruebas extraídas de un método analítico."""
    tests: Optional[List[TestSolution]] = Field(
        None,
        description=(
            "Lista de ensayos analíticos extraídos del método. "
            "NO incluir información de anexos, apéndices o secciones de autorización."
        )
    )


#######################################################################################
# Constantes para el prompt
#######################################################################################

# Patrones de ruido del documento a filtrar
DOCUMENT_NOISE_PATTERNS = [
    r"DOCUMENTO PROPIEDAD DE PROCAPS S\.A\..*?PARCIAL\.?",
    r"DOCUMENTO CONFIDENCIAL",
    r"DOCUMENTO ORIGINAL",
    r"F-INST-\d+-\d+-V\d+",
    r"F-INST-\d+-\d+",
    r"Copia no controlada",
    r"METODO DE ANÁLISIS DE.*?Página:\s*\d+\s*de\s*\d+",
    r"Método No[:\.]?\s*[\d-]+",
    r"Código[:\.]?\s*\d+",
    r"Versión[:\.]?\s*\d+",
    r"Vigencia[:\.]?\s*[\d/-]+",
    r"Página[:\.]?\s*\d+\s*de\s*\d+",
]