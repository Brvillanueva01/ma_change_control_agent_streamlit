from pydantic import BaseModel, Field
from typing import List
from src.models.extraction_models import Prueba

class SideBySideModel(BaseModel):
    control_cambio: str = Field(..., description="Código de Control de Cambio. Inicia con SC y se encuentra en el encabezado del documento.")
    nombre_anexo: str = Field(..., description="Nombre del anexo. Se encuentra en el encabezado del documento.")
    codigo_producto: int = Field(..., description="Código del producto o materia prima. Puede iniciar por 10 o 40 o 30. Se encuentra en el encabezado del documento.")

    metodo_actual: List[Prueba] = Field(..., description="Listado de pruebas del método actual que incluye toda la información reportada en el documento. Todas las pruebas del metodo actual se encuentran en la tabla en el lado izquierdo del documento.")
    metodo_modificacion_propuesta: List[Prueba] = Field(..., description="Listado de pruebas del método modificación propuesta que incluye toda la información reportada en el documento. Todas las pruebas del metodo modificación propuesta se encuentran en la tabla en el lado derecho del documento.")
