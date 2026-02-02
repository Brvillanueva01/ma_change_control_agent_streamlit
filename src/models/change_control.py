from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

class ActividadEvaluacion(BaseModel):
    id: Optional[str] = Field(default=None, description="ID de la actividad de evaluación.")
    actividad: Optional[str] = Field(default=None, description="Actividad de evaluación.")
    responsable: Optional[str] = Field(default=None, description="Responsable de la actividad de evaluación.")
    fecha_programada: Optional[str] = Field(default=None, description="Fecha programada de la actividad de evaluación.")
    soportes_requeridos: Optional[List[str]] = Field(default=None, description="Soportes requeridos para la actividad de evaluación.")

class ActividadImplementacion(ActividadEvaluacion):
    """Actividad de implementación"""

class ActividadPostCambio(ActividadEvaluacion):
    """Actividad de post-cambio"""

class ComentarioEquipoMultidisciplinario(BaseModel):
    """Comentario del equipo multidisciplinario"""
    usuario: Optional[str] = Field(default=None, description="Usuario que realiza el comentario.")
    fecha: Optional[str] = Field(default=None, description="Fecha del comentario.")
    comentario: Optional[str] = Field(default=None, description="Comentario del equipo multidisciplinario.")

class MiembroEquipoMultidisciplinario(BaseModel):
    nombre: Optional[str] = Field(default=None, description="Nombre del miembro del equipo multidisciplinario.")
    cargo: Optional[str] = Field(default=None, description="Cargo del miembro del equipo multidisciplinario.")
    fecha_revision: Optional[str] = Field(default=None, description="Fecha de la revisión del miembro del equipo multidisciplinario.")

class AprobacionCambiosMayores(BaseModel):
    """Aprobación para cambios mayores"""
    cargo: Optional[str] = Field(default=None, description="Cargo del usuario que realiza la aprobación.")
    nombre: Optional[str] = Field(default=None, description="Nombre del usuario que realiza la aprobación.")
    fecha: Optional[str] = Field(default=None, description="Fecha de la aprobación.")

class ProductoAfectadoCambio(BaseModel):
    codigo: Optional[str] = Field(default=None, description="Código del producto afectado por el cambio.")
    descripcion: Optional[str] = Field(default=None, description="Descripción del producto afectado por el cambio.")
    no_orden: Optional[str] = Field(default=None, description="Número de orden del producto afectado por el cambio. Puede estar vacío")
    no_lote: Optional[str] = Field(default=None, description="Número de lote del producto afectado por el cambio. Puede estar vacío")

class DescripcionCambio(BaseModel):
    """Descripción del cambio"""
    prueba: Optional[str] = Field(default=None, description="Prueba a la que se aplica el cambio.")
    texto: Optional[str] = Field(default=None, description="Descripción del cambio que le será realizado a la prueba.")


# ============================================================================
# Modelos para extracción estructurada de cambios (ControlCambioOutput)
# ============================================================================

class TipoCambio(str, Enum):
    """Tipo de cambio aplicado a una prueba analítica."""
    ACTUALIZACION = "ACTUALIZACIÓN"
    ELIMINACION = "ELIMINACIÓN"
    SIN_CAMBIO = "SIN_CAMBIO"


class CambioPruebaAnalitica(BaseModel):
    """Representa un cambio específico en una prueba analítica existente."""
    prueba: str = Field(description="Nombre exacto de la prueba analítica")
    tipo_cambio: TipoCambio = Field(description="Tipo de cambio: ACTUALIZACIÓN, ELIMINACIÓN o SIN_CAMBIO")
    criterio_actual: Optional[str] = Field(default=None, description="Valor/límite actual con unidades")
    criterio_propuesto: Optional[str] = Field(default=None, description="Valor/límite propuesto con unidades")
    metodologia_actual: Optional[str] = Field(default=None, description="Metodología actual (Titulación, HPLC, IR, etc.)")
    metodologia_propuesta: Optional[str] = Field(default=None, description="Metodología propuesta")
    referencia: Optional[str] = Field(default=None, description="Referencia farmacopeica (USP, COFA, Interna, etc.)")
    source_reference_file: Optional[str] = Field(
        default=None, 
        description="Nombre del archivo/método de referencia de donde proviene la prueba propuesta (ej: '01-3850', '01-4279', 'MA 400006238'). Extraer del texto cuando menciona 'tomar de referencia', 'contemplado en el método', etc."
    )


class PruebaNueva(BaseModel):
    """Representa una prueba analítica nueva que se incorpora."""
    prueba: str = Field(description="Nombre de la prueba nueva")
    criterio: str = Field(description="Criterio de aceptación")
    metodologia: str = Field(description="Metodología analítica")
    referencia: Optional[str] = Field(default=None, description="Referencia farmacopeica")
    source_reference_file: Optional[str] = Field(
        default=None, 
        description="Nombre del archivo/método de referencia de donde proviene la prueba (ej: '01-3850', '01-4279', 'MA 400006238'). Extraer del texto cuando menciona 'tomar de referencia', 'contemplado en el método', 'transcribir de', etc."
    )
#Breiner estuvo aqui 

class ProductoAfectado(BaseModel):
    """Producto afectado por el control de cambios."""
    codigo: str = Field(description="Código del producto")
    nombre: str = Field(description="Nombre del producto")


class MateriaPrima(BaseModel):
    """Información de la materia prima afectada."""
    codigo: str = Field(description="Código de la materia prima")
    nombre: str = Field(description="Nombre de la materia prima")


class ControlCambioOutput(BaseModel):
    """Modelo de salida estructurada para extracción de control de cambios."""
    filename: str = Field(description="Nombre del archivo a almacenar (ej: CC-001_resumen_cambios.md)")
    summary: str = Field(max_length=500, description="Resumen conciso en 1-2 oraciones del propósito de los cambios")
    materia_prima: Optional[MateriaPrima] = Field(default=None, description="Materia prima afectada por el cambio")
    productos_afectados: List[ProductoAfectado] = Field(default_factory=list, description="Lista de productos afectados")
    cambios_pruebas_analiticas: List[CambioPruebaAnalitica] = Field(
        default_factory=list,
        description="Lista de cambios en pruebas analíticas existentes"
    )
    pruebas_nuevas: List[PruebaNueva] = Field(
        default_factory=list,
        description="Lista de pruebas nuevas a incorporar"
    )
    prerrequisitos: List[str] = Field(default_factory=list, description="Prerrequisitos para implementar el cambio")
    notas_operativas: List[str] = Field(default_factory=list, description="Notas operativas adicionales")

class ChangeControlModel(BaseModel):
    # Encabezado
    codigo_solicitud: Optional[str] = Field(default=None, description="Código de la solicitud de cambio, normalmente se encuentra en el encabezado del documento al lado de PLAN DE CONTROL DE CAMBIOS.")
    fecha_solicitud: Optional[str] = Field(default=None, description="Fecha de la solicitud.")
    
    # Título del cambio
    nombre: Optional[str] = Field(default=None, description="Nombre de la persona que presenta el cambio.")
    cargo: Optional[str] = Field(default=None, description="Cargo de la persona que presenta el cambio. Puede ser Analistas, Jefes, Coordinadores, etc.")
    titulo: Optional[str] = Field(default=None, description="Título del cambio. Puede ser el nombre de un producto o declarar el nombre del método analítico.")
    fecha_aprobacion: Optional[str] = Field(default=None, description="Fecha de aprobación del cambio.")

    # Inicio e identificación del cambio
    descripcion_cambio: List[DescripcionCambio] = Field(..., description="Listado de descripciones de los diferentes cambios en las pruebas del método analítico. Usualmente es un texto extenso explicativo del cambio que abarca varias hojas. Inicia desde strings como 'SECCION I: INICIO E IDENTIFICACION DEL CAMBIO', y finaliza cerca de strings como 'JUSTIFICACION'.")
    cliente: Optional[str] = Field(default=None, description="Nombre del cliente. Se encuentra cerca del string 'CLIENTE'.")
    centro: Optional[str] = Field(default=None, description="Nombre del centro. Se encuentra cerca del string 'CENTRO'.")

    # Codigos de productos afectados por el cambio
    codigos_productos: Optional[List[ProductoAfectadoCambio]] = Field(default=None, description="Lista de codigos de productos afectados por el cambio.")
    
    # Equipo multidisciplinario
    equipo_multidisciplinario: Optional[List[MiembroEquipoMultidisciplinario]] = Field(default=None, description="Equipo multidisciplinario. Se encuentra cerca del string 'EQUIPO MULTIDISCIPLINARIO'.")

    # Sección 2 Propuesta de evaluación
    actividades_evaluacion: Optional[List[ActividadEvaluacion]] = Field(default=None, description="Actividades de evaluación incluyendo su responsable, id, FECHA PROGRAMADA Y SOPORTES REQUERIDOS. Se encuentra cerca del string 'FASE DE EVALUACION'.")

    actividades_implementacion: Optional[List[ActividadImplementacion]] = Field(default=None, description="Actividades de implementación incluyendo su responsable, id, FECHA PROGRAMADA Y SOPORTES REQUERIDOS. Se encuentra cerca del string 'FASE DE IMPLEMENTACION'.")

    actividades_post_cambio: Optional[List[ActividadPostCambio]] = Field(default=None, description="Actividades de post-cambio incluyendo su responsable, id, FECHA PROGRAMADA Y SOPORTES REQUERIDOS. Se encuentra cerca del string 'FASE DE POST-CAMBIOS'.")

    # Sección 3 Comentarios del equipo multidisciplinario
    comentarios_equipo_multidisciplinario: Optional[List[ComentarioEquipoMultidisciplinario]] = Field(default=None, description="Comentarios del equipo multidisciplinario. Se encuentra cerca del string 'COMENTARIOS DEL EQUIPO MULTIDISCIPLINARIO'.")

    # Aprobación para cambios mayores
    aprobacion_cambos_mayores: Optional[List[AprobacionCambiosMayores]] = Field(default=None, description="Aprobación para cambios mayores. Se encuentra cerca del string 'APROBACION PARA CAMBIOS MAYORES'.")