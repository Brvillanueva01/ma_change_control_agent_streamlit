from __future__ import annotations
from enum import Enum
from typing import List, Optional
import re

from pydantic import BaseModel, Field, field_validator


# =========================
# TIPOS DE MÉTODO
# =========================

class TipoMetodo(str, Enum):
    METODO_ANALISIS_PRODUCTO_TERMINADO = "MÉTODO DE ANÁLISIS DE PRODUCTO TERMINADO"
    METODO_ANALISIS_MATERIA_PRIMA = "MÉTODO DE ANÁLISIS DE MATERIA PRIMA"
    METODO_ANALISIS_PROCESO = "MÉTODO DE ANÁLISIS DE PROCESO"

# =========================
# 2. ALCANCE DEL MÉTODO
# =========================

class ProductosAlcance(BaseModel):
    nombre_producto: str = Field(
        ...,
        description=(
            "Nombre exacto del producto tal como aparece en la tabla de ALCANCE o en el encabezado. "
            "Incluye la potencia si está pegada al nombre. "
            "Ej.: 'PROGESTERONA 100 mg'. No incluir códigos ni siglas."
        ),
    )
    codigo_producto: str = Field(
        ...,
        description=(
            "Código del producto asociado al alcance tal como aparece en la tabla de ALCANCE "
            "o encabezado. Ej.: '400002641'."
        ),
    )


class AlcanceMetodo(BaseModel):
    texto_alcance: str = Field(
        ...,
        description=(
            "Párrafo o texto principal que describe cuándo aplica el método, bajo el título '2. ALCANCE' "
            "o equivalente. Capturar el texto continuo hasta la tabla/listado de productos."
        ),
    )
    lista_productos_alcance: List[ProductosAlcance] = Field(
        ...,
        description=(
            "Lista de productos del alcance tal como aparecen en la tabla/listado bajo 'ALCANCE'. "
            "Cada entrada corresponde a una fila (nombre y código)."
        ),
    )

# =========================
# 6. EQUIPOS
# =========================

class Equipo(BaseModel):
    nombre: str = Field(
        ...,
        description=(
            "Nombre genérico del equipo en la tabla/listado de 'EQUIPOS'. "
            "Ej.: 'Balanza analítica', 'Cromatógrafo líquido'."
        ),
    )
    marca: str = Field(
        ...,
        description=(
            "Marca y/o modelo del equipo tal como aparece en la tabla/listado. "
            "Ej.: 'Mettler Toledo XP205', 'Agilent 1100'."
        ),
    )

# =========================
# 8. ANEXOS
# =========================

class Anexo(BaseModel):
    numero: int = Field(
        ...,
        description="Número del anexo en la tabla/listado de ANEXOS. Ej.: 1, 2, 3.",
    )
    descripcion: str = Field(
        ...,
        description="Descripción literal del anexo. Ej.: 'Espectro UV de Valoración de Progesterona'.",
    )


# =========================
# 9. AUTORIZACIONES
# =========================

class Autorizacion(BaseModel):
    tipo_autorizacion: str = Field(
        ...,
        description=(
            "Etiqueta de firma, por ejemplo: 'ELABORADO POR', 'REVISADO POR', 'APROBADO POR', "
            "tal como aparece en la sección de firmas."
        ),
    )
    nombre: str = Field(
        ...,
        description="Nombre completo junto al tipo de autorización. Ej.: 'Luisa Beleño'.",
    )
    cargo: str = Field(
        ...,
        description=(
            "Cargo asociado al firmante, tal como aparece en el documento. "
            "Ej.: 'Analista', 'Coordinador de Estandarizaciones y Métodos'."
        ),
    )


# =========================
# 10. DOCUMENTOS SOPORTE
# =========================

class DocumentoSoporte(BaseModel):
    numero: int = Field(
        ...,
        description=(
            "Número secuencial del documento soporte en la tabla de DOCUMENTOS SOPORTE. Ej.: 1, 2, 3."
        ),
    )
    fuente: str = Field(
        ...,
        description=(
            "Código/identificador del documento soporte tal como aparece. "
            "Ej.: 'F-INST-0310-4', 'USP'."
        ),
    )
    descripcion: str = Field(
        ...,
        description=(
            "Descripción textual del documento de soporte. "
            "Ej.: 'Plantilla de Reporte Analítico para Laboratorio'."
        ),
    )


# =========================
# 11. HISTÓRICO DE CAMBIOS
# =========================

class HistoricoCambio(BaseModel):
    codigo_cambio: str = Field(
        ...,
        description=(
            "Código del método en la tabla de HISTÓRICO DE CAMBIOS. Ancla: columna 'CÓDIGO'. "
            "Ej.: '01-3608'."
        ),
    )
    version_cambio: str = Field(
        ...,
        description=(
            "Versión asociada a ese cambio en la columna 'VERSIÓN'. Ej.: '01', '00'."
        ),
    )
    fecha_modificacion: str = Field(
        ...,
        description=(
            "Fecha exactamente como aparece en la tabla de cambios. No normalizar el formato. "
            "Ej.: '16-08-30', '15-01-14'."
        ),
    )
    descripcion_cambio: str = Field(
        ...,
        description=(
            "Descripción completa del cambio, incluyendo referencias internas si las hay. "
            "Ej.: 'En la prueba de valoración se incluye método alterno por Espectrofotometría UV. CC-000000295'."
        ),
    )

# ==========================================
# METODO ANALITICO PARA DOCUMENT ANNOTATION
# ==========================================

class MetodoAnaliticoDA(BaseModel):
    apis: Optional[List[str]] = Field(
        None,
        description="Listado de ingredientes activos (APIs) del producto, si se indican en el método.",
    )
    tipo_metodo: Optional[TipoMetodo] = Field(
        None,
        description=(
            "Tipo de método según el encabezado o portada. Seleccionar una de las opciones definidas "
            "('MÉTODO DE ANÁLISIS DE PRODUCTO TERMINADO', 'MÉTODO DE ANÁLISIS DE MATERIA PRIMA', "
            "'MÉTODO DE ANÁLISIS DE PROCESO'), tal como aparece en el documento."
        ),
    )
    nombre_producto: Optional[str] = Field(
        None,
        description=(
            "Nombre comercial/técnico del producto en el encabezado. Mantener potencia si está en la misma línea. "
            "Ej.: 'PROGESTERONA 100 mg'."
        ),
    )
    numero_metodo: Optional[str] = Field(
        None,
        description=(
            "Identificador del método indicado como 'Método No', 'CÓDIGO', 'MÉTODO', etc. "
            "Ej.: '01-3608'. Devolverlo tal como aparece."
        ),
    )
    version_metodo: Optional[str] = Field(
        None,
        description=(
            "Versión del método indicada en el encabezado o portada. Ej.: '01'. Solo el valor literal."
        ),
    )
    codigo_producto: Optional[str] = Field(
        None,
        description=(
            "Código del producto en el encabezado o tabla de alcance (columna 'Código'/'Código Nuevo'). "
            "Ej.: '400002641'."
        ),
    )
    tabla_de_contenidos: Optional[List[str]] = Field(
        None,
        description=(
            "Extracción EXHAUSTIVA y LITERAL de la estructura jerárquica del documento. "
            "Instrucciones críticas: "
            "1. CITA TEXTUAL: El texto extraído debe ser idéntico al del documento (mismas mayúsculas, tildes, errores tipográficos y numeración). "
            "   **No traduzcas; conserva el idioma original (si el documento está en inglés, los encabezados deben permanecer en inglés).** "
            "2. PROFUNDIDAD: Detecta y extrae todos los niveles jerárquicos visibles (Nivel 1 hasta Nivel 4 o más profundo). "
            "3. COMPLETITUD: No omitas secciones 'pequeñas' o técnicas. Si es un encabezado visual, debe estar en la lista. "
            "4. FORMATO: Cada string debe incluir el prefijo numérico y el título (ej: '5.5.3.2 Solución Hidróxido de Potasio'). "
            "NO resumas, NO corrijas ortografía, NO agrupes ítems."
        ),
      #Breiner estuvo aqui 
    )
    objetivo: Optional[str] = Field(
        None,
        description=(
            "Párrafo completo bajo el encabezado '1. OBJETIVO' o equivalente, hasta el siguiente encabezado numerado."
        ),
    )
    alcance_metodo: Optional[AlcanceMetodo] = Field(
        None,
        description="Sección '2. ALCANCE' con texto general y tabla/listado de productos.",
    )
    definiciones: Optional[List[str]] = Field(
        None,
        description=(
            "Lista de siglas/definiciones bajo '3. DEFINICIONES' o similares. "
            "Una entrada por línea/viñeta."
        ),
    )
    recomendaciones_seguridad: Optional[List[str]] = Field(
        None,
        description=(
            "Viñetas completas bajo 'RECOMENDACIONES CLAVES, PRECAUCIONES Y ADVERTENCIAS' "
            "o sección equivalente. Una entrada por viñeta."
        ),
    )
    materiales: Optional[List[str]] = Field(
        None,
        description=(
            "Lista de materiales y reactivos globales del método ('MATERIALES Y REACTIVOS'). "
            "Una entrada por línea/viñeta."
        ),
    )
    equipos: Optional[List[Equipo]] = Field(
        None,
        description=(
            "Tabla/listado de 'EQUIPOS' con nombre y marca/modelo para cada equipo."
        ),
    )
    anexos: Optional[List[Anexo]] = Field(
        None,
        description="Tabla/listado de ANEXOS con número y descripción.",
    )
    autorizaciones: Optional[List[Autorizacion]] = Field(
        None,
        description=(
            "Bloque de texto con las firmas de ELABORADO/REVISADO/APROBADO, incluyendo nombres y cargos, "
            "tal como aparece en la sección de autorizaciones."
        ),
    )
    documentos_soporte: Optional[List[DocumentoSoporte]] = Field(
        None,
        description=(
            "Texto o tabla de DOCUMENTOS SOPORTE con número, fuente y descripción, tal cual se muestra en el método."
        ),
    )
    historico_cambios: Optional[List[HistoricoCambio]] = Field(
        None,
        description=(
            "Texto o tabla de HISTÓRICO DE CAMBIOS con código, versión, fecha y descripción completa del cambio."
        ),
    )

# ==========================================
# METODO ANALITICO INCLUYENDO MARKDOWN
# ==========================================

# ==========================================
# MODELOS PARA PRUEBAS (usado por apply_method_patch, consolidate_new_method)
# ==========================================

class Subespecificacion(BaseModel):
    nombre_subespecificacion: str = Field(..., description="Nombre de la subespecificación")
    criterio_aceptacion_subespecificacion: str = Field(..., description="Criterio de aceptación de la subespecificación")

class Especificacion(BaseModel):
    prueba: str = Field(..., description="Prueba del método analítico a la que se refiere la especificación.")
    texto_especificacion: str = Field(..., description="Texto de la especificacion incluyendo criterio de aceptación")
    subespecificacion: Optional[List[Subespecificacion]] = Field(None, description="Subespecificaciones del método analítico")

class Solucion(BaseModel):
    nombre_solucion: str = Field(..., description="Nombre de la solución")
    preparacion_solucion: str = Field(..., description="Texto descriptivo de la preparación de la solución")

class CondicionCromatografica(BaseModel):
    nombre: str = Field(..., description="Nombre de la condición cromatográfica")
    descripcion: str = Field(..., description="Descripción de la condición cromatográfica")

class Prueba(BaseModel):
    id_prueba: Optional[str] = Field(
        default=None,
        description="Identificador único (UUID o hash) de la prueba dentro del método.",
    )
    prueba: str = Field(..., description="Prueba del método analítico a la que se refiere el procedimiento.")
    procedimientos: str = Field(..., description="Descripción detallada de los procedimientos de la prueba analítica.")
    equipos: Optional[List[str]] = Field(None, description="Listado de Equipos declarados en la prueba")
    condiciones_cromatograficas: Optional[List[CondicionCromatografica]] = Field(None, description="Condiciones cromatográficas de la prueba analítica (Si Aplica)")
    reactivos: Optional[List[str]] = Field(None, description="Listado de los reactivos")
    soluciones: Optional[List[Solucion]] = Field(None, description="Listado de las soluciones")
    especificaciones: List[Especificacion] = Field(..., description="Especificaciones del método analítico")


class MetodoAnaliticoNuevo(BaseModel):
    """Modelo para el método analítico final consolidado."""
    tipo_metodo: Optional[str] = Field(None)
    nombre_producto: Optional[str] = Field(None)
    numero_metodo: Optional[str] = Field(None)
    version_metodo: Optional[str] = Field(None)
    codigo_producto: Optional[str] = Field(None)
    objetivo: Optional[str] = Field(None)
    alcance_metodo: Optional[AlcanceMetodo] = Field(None)
    definiciones: Optional[List[str]] = Field(None)
    recomendaciones_seguridad: Optional[List[str]] = Field(None)
    materiales: Optional[List[str]] = Field(None)
    equipos: Optional[List[Equipo]] = Field(None)
    anexos: Optional[List[Anexo]] = Field(None)
    autorizaciones: Optional[List[Autorizacion]] = Field(None)
    documentos_soporte: Optional[List[DocumentoSoporte]] = Field(None)
    historico_cambios: Optional[List[HistoricoCambio]] = Field(None)
    pruebas: List[Prueba] = Field(description="La lista de pruebas procesadas en el nuevo formato.")


# ==========================================
# METODO ANALITICO INCLUYENDO MARKDOWN
# ==========================================

class MetodoAnaliticoCompleto(BaseModel):
    apis: Optional[List[str]] = Field(
        None,
        description="Listado de ingredientes activos (APIs) del producto, si se indican en el método.",
    )
    tipo_metodo: Optional[TipoMetodo] = Field(
        None,
        description=(
            "Tipo de método según el encabezado o portada. Seleccionar una de las opciones definidas "
            "('MÉTODO DE ANÁLISIS DE PRODUCTO TERMINADO', 'MÉTODO DE ANÁLISIS DE MATERIA PRIMA', "
            "'MÉTODO DE ANÁLISIS DE PROCESO'), tal como aparece en el documento."
        ),
    )
    nombre_producto: Optional[str] = Field(
        None,
        description=(
            "Nombre comercial/técnico del producto en el encabezado. Mantener potencia si está en la misma línea. "
            "Ej.: 'PROGESTERONA 100 mg'."
        ),
    )
    numero_metodo: Optional[str] = Field(
        None,
        description=(
            "Identificador del método indicado como 'Método No', 'CÓDIGO', 'MÉTODO', etc. "
            "Ej.: '01-3608'. Devolverlo tal como aparece."
        ),
    )
    version_metodo: Optional[str] = Field(
        None,
        description=(
            "Versión del método indicada en el encabezado o portada. Ej.: '01'. Solo el valor literal."
        ),
    )
    codigo_producto: Optional[str] = Field(
        None,
        description=(
            "Código del producto en el encabezado o tabla de alcance (columna 'Código'/'Código Nuevo'). "
            "Ej.: '400002641'."
        ),
    )
    tabla_de_contenidos: Optional[List[str]] = Field(
        None,
        description=(
            "Listado completo de entradas de la tabla de contenidos, copiado literalmente del documento "
            "(con numeración jerárquica y texto exacto). Incluye absolutamente todos los subcapítulos disponibles, "
            "hasta el último nivel de detalle (ej.: '5.5.3.2 Solución Hidróxido de potasio', "
            "'5.5.3.3 Solución stock placebo', '5.5.3.3.1 Procedimiento'). No omitas ni agrupes subniveles."
        ),
    )
    objetivo: Optional[str] = Field(
        None,
        description=(
            "Párrafo completo bajo el encabezado '1. OBJETIVO' o equivalente, hasta el siguiente encabezado numerado."
        ),
    )
    alcance_metodo: Optional[AlcanceMetodo] = Field(
        None,
        description="Sección '2. ALCANCE' con texto general y tabla/listado de productos.",
    )
    definiciones: Optional[List[str]] = Field(
        None,
        description=(
            "Lista de siglas/definiciones bajo '3. DEFINICIONES' o similares. "
            "Una entrada por línea/viñeta."
        ),
    )
    recomendaciones_seguridad: Optional[List[str]] = Field(
        None,
        description=(
            "Viñetas completas bajo 'RECOMENDACIONES CLAVES, PRECAUCIONES Y ADVERTENCIAS' "
            "o sección equivalente. Una entrada por viñeta."
        ),
    )
    materiales: Optional[List[str]] = Field(
        None,
        description=(
            "Lista de materiales y reactivos globales del método ('MATERIALES Y REACTIVOS'). "
            "Una entrada por línea/viñeta."
        ),
    )
    equipos: Optional[List[Equipo]] = Field(
        None,
        description=(
            "Tabla/listado de 'EQUIPOS' con nombre y marca/modelo para cada equipo."
        ),
    )
    anexos: Optional[List[Anexo]] = Field(
        None,
        description="Tabla/listado de ANEXOS con número y descripción.",
    )
    autorizaciones: Optional[List[Autorizacion]] = Field(
        None,
        description=(
            "Bloque de texto con las firmas de ELABORADO/REVISADO/APROBADO, incluyendo nombres y cargos, "
            "tal como aparece en la sección de autorizaciones."
        ),
    )
    documentos_soporte: Optional[List[DocumentoSoporte]] = Field(
        None,
        description=(
            "Texto o tabla de DOCUMENTOS SOPORTE con número, fuente y descripción, tal cual se muestra en el método."
        ),
    )
    historico_cambios: Optional[List[HistoricoCambio]] = Field(
        None,
        description=(
            "Texto o tabla de HISTÓRICO DE CAMBIOS con código, versión, fecha y descripción completa del cambio."
        ),
    )
    markdown_completo: str = Field(
        ...,
        description=(
            "Markdown completo del método, incluyendo todos los elementos anteriores. "
            "No modificar el formato original, solo convertirlo a markdown."
        ),
    )
