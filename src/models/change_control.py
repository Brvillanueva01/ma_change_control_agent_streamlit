from pydantic import BaseModel, Field
from typing import List, Optional

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