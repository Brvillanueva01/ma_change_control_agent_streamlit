from pydantic import BaseModel, Field
from typing import List

class ActividadEvaluacion(BaseModel):
    id: str = Field(..., description="ID de la actividad de evaluación.")
    actividad: str = Field(..., description="Actividad de evaluación.")
    responsable: str = Field(..., description="Responsable de la actividad de evaluación.")
    fecha_programada: str = Field(..., description="Fecha programada de la actividad de evaluación.")
    soportes_requeridos: List[str] = Field(..., description="Soportes requeridos para la actividad de evaluación.")

class ActividadImplementacion(ActividadEvaluacion):
    """Actividad de implementación"""

class ActividadPostCambio(ActividadEvaluacion):
    """Actividad de post-cambio"""

class ComentarioEquipoMultidisciplinario(BaseModel):
    """Comentario del equipo multidisciplinario"""
    usuario: str = Field(..., description="Usuario que realiza el comentario.")
    fecha: str = Field(..., description="Fecha del comentario.")
    comentario: str = Field(..., description="Comentario del equipo multidisciplinario.")

class MiembroEquipoMultidisciplinario(BaseModel):
    nombre: str = Field(..., description="Nombre del miembro del equipo multidisciplinario.")
    cargo: str = Field(..., description="Cargo del miembro del equipo multidisciplinario.")
    fecha_revision: str = Field(..., description="Fecha de la revisión del miembro del equipo multidisciplinario.")

class AprobacionCambiosMayores(BaseModel):
    """Aprobación para cambios mayores"""
    cargo: str = Field(..., description="Cargo del usuario que realiza la aprobación.")
    nombre: str = Field(..., description="Nombre del usuario que realiza la aprobación.")
    fecha: str = Field(..., description="Fecha de la aprobación.")

class ProductoAfectadoCambio(BaseModel):
    codigo: str = Field(..., description="Código del producto afectado por el cambio.")
    descripcion: str = Field(..., description="Descripción del producto afectado por el cambio.")
    no_orden: str = Field(..., description="Número de orden del producto afectado por el cambio. Puede estar vacío")
    no_lote: str = Field(..., description="Número de lote del producto afectado por el cambio. Puede estar vacío")

class ChangeControlModel(BaseModel):
    # Encabezado
    codigo_solicitud: str = Field(..., description="Código de la solicitud de cambio, normalmente se encuentra en el encabezado del documento al lado de PLAN DE CONTROL DE CAMBIOS.")
    fecha_solicitud: str = Field(..., description="Fecha de la solicitud.")
    
    # Título del cambio
    nombre: str = Field(..., description="Nombre de la persona que presenta el cambio.")
    cargo: str = Field(..., description="Cargo de la persona que presenta el cambio. Puede ser Analistas, Jefes, Coordinadores, etc.")
    titulo: str = Field(..., description="Título del cambio. Puede ser el nombre de un producto o declarar el nombre del método analítico.")
    fecha_aprobacion: str = Field(..., description="Fecha de aprobación del cambio.")

    # Inicio e identificación del cambio
    descripcion_cambio: str = Field(..., description="Descripción del cambio. Usualmente es un texto extenso explicativo del cambio que abarca varias hojas. Inicia desde strings como 'SECCION I: INICIO E IDENTIFICACION DEL CAMBIO', y finaliza cerca de strings como 'JUSTIFICACION'.")
    cliente: str = Field(..., description="Nombre del cliente. Se encuentra cerca del string 'CLIENTE'.")
    centro: str = Field(..., description="Nombre del centro. Se encuentra cerca del string 'CENTRO'.")

    # Codigos de productos afectados por el cambio
    codigos_productos: List[ProductoAfectadoCambio] = Field(..., description="Lista de codigos de productos afectados por el cambio.")
    
    # Equipo multidisciplinario
    equipo_multidisciplinario: List[MiembroEquipoMultidisciplinario] = Field(..., description="Equipo multidisciplinario. Se encuentra cerca del string 'EQUIPO MULTIDISCIPLINARIO'.")

    # Sección 2 Propuesta de evaluación
    actividades_evaluacion: List[ActividadEvaluacion] = Field(..., description="Actividades de evaluación incluyendo su responsable, id, FECHA PROGRAMADA Y SOPORTES REQUERIDOS. Se encuentra cerca del string 'FASE DE EVALUACION'.")

    actividades_implementacion: List[ActividadImplementacion] = Field(..., description="Actividades de implementación incluyendo su responsable, id, FECHA PROGRAMADA Y SOPORTES REQUERIDOS. Se encuentra cerca del string 'FASE DE IMPLEMENTACION'.")

    actividades_post_cambio: List[ActividadPostCambio] = Field(..., description="Actividades de post-cambio incluyendo su responsable, id, FECHA PROGRAMADA Y SOPORTES REQUERIDOS. Se encuentra cerca del string 'FASE DE POST-CAMBIOS'.")

    # Sección 3 Comentarios del equipo multidisciplinario
    comentarios_equipo_multidisciplinario: List[ComentarioEquipoMultidisciplinario] = Field(..., description="Comentarios del equipo multidisciplinario. Se encuentra cerca del string 'COMENTARIOS DEL EQUIPO MULTIDISCIPLINARIO'.")

    # Aprobación para cambios mayores
    aprobacion_cambos_mayores: List[AprobacionCambiosMayores] = Field(..., description="Aprobación para cambios mayores. Se encuentra cerca del string 'APROBACION PARA CAMBIOS MAYORES'.")