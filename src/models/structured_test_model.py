from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator
from typing import Literal
import re

#######################################################################################
# Modelo de datos
#######################################################################################

class CondicionCromatografica(BaseModel):
    nombre_condicion: str = Field(..., description = "Nombre de la condición cromatográfica, por ejemplo: Columna, Temperatura de la columna, Fase Móvil, entre otros")
    valor_condicion: str = Field(..., description = "Valor de la condición cromatográfica, por ejemplo: 'C18 (250 x 4.6); 5 micras', '60°C', 'Ver Tabla 1', entre otros")

class ProporcionesTiempo(BaseModel):
    tiempo: float = Field(..., description="Tiempo en minutos")
    proporcion_a: float = Field(..., description="Proporción de solución A")
    proporcion_b: float = Field(..., description="Proporción de solución B")

class CondicionesCromatograficas(BaseModel):
    condiciones_cromatograficas: List[CondicionCromatografica] = Field(..., description="Listado de condiciones cromatográficas")
    tabla_gradiente: Optional[List[ProporcionesTiempo]] = Field(None, description="Tabla de proporciones de soluciones A y B.")
    notas: Optional[List[str]] = Field(None, description="Listado de notas de la sección condiciones cromatográficas")

class Solucion(BaseModel):
    nombre_solucion: str = Field(
        ...,
        description=(
            "Encabezado literal tal como en el documento: 'Solución Stock Estándar', "
            "'Solución Estándar', 'Solución Stock Muestra', 'Solución Muestra', etc. "
            "No traducir, no normalizar, no inventar."
        )
    )
    preparacion_solucion: str = Field(
        ...,
        description=(
            "⚠️ COPIAR VERBATIM. Pegar el texto COMPLETO de la preparación exactamente como aparece, "
            "incluyendo saltos de línea, signos, mayúsculas/minúsculas, símbolos (µm, °C), paréntesis y notas. "
            "NO resumir, NO corregir ortografía, NO traducir, NO cambiar unidades. "
            "Límites de captura: desde la línea inmediatamente debajo del encabezado de la solución "
            "hasta ANTES del próximo encabezado de 'Solución ...', 'Procedimiento', 'Criterio de Aceptación' "
            "o siguiente subtítulo (p.ej., '7.x.y'). "
            "Ejemplo (fragmento): 'Transferir aproximadamente 25.0 mg... Pasar a vial por filtro jeringa PVDF 0.45 µm, "
            "descartando los primeros 2 mL del filtrado.'"
        )
    )
    notas: Optional[List[str]] = Field(None, description = "Listado de notas relacionadas con la preparación o materiales de la solución")

class TiempoRetencion(BaseModel):
    nombre: str = Field(..., description="Nombre del compuesto")
    tiempo_relativo_retencion: str = Field(..., description="Tiempo relativo de retención")
    factor_respuesta_relativa: str = Field(..., description="Factor de respuesta relativa")

class Procedimiento(BaseModel):
    texto: str = Field(..., description="Texto del procedimiento tal como aparece en el documento")
    notas: Optional[List[str]] = Field(None, description="Listado de notas relacionadas con el procedimiento")
    tiempo_retencion: Optional[List[TiempoRetencion]] = Field(None, description="Listado de tiempos de retención")

class TablaCriteriosAceptacion(BaseModel):
    etapa: str = Field(..., description="Etapa, S1, S2, entre otros")
    unidades_analizadas: str = Field(..., description="Número de unidades analizadas")
    criterio_aceptacion: str = Field(..., description = "Criterio de aceptación específico")

class CriterioAceptacion(BaseModel):
    texto: str = Field(..., description="Texto del criterio de aceptación tal como aparece en el documento")
    notas: Optional[List[str]] = Field(None, description="Listado de notas relacionadas con el criterio de aceptación")
    tabla_criterios: Optional[List[TablaCriteriosAceptacion]] = Field(None, description="Tabla de criterios de aceptación")

class OrdenInyeccion(BaseModel):
    solucion: Optional[str] = Field(None, description="Nombre de la solución")
    numero_inyecciones: Optional[int] = Field(None, description="Numero de inyecciones")
    test_adecuabilidad: Optional[str] = Field(None, description="Nombre y descripción del test de adecuabilidad. Aquí es importante que indiques cual es el parametro de calculo, esto es, si es RSD, si es desviacion estandar, promedio, entre otros")
    especificacion: Optional[str] = Field(None, description="Especificacion del parametro de calculo. Descripcion detallada.")


#######################################################################################
# Modelo de extracción de datos
#######################################################################################

class TestSolution(BaseModel):
    section_id: str = Field(..., description="Número de la sección donde se encuentra el análisis específico (Por ejemplo, 7.1, 7.2, 6.1, 6.4, 8.3, 8.9)")
    section_title: str = Field(..., description="Título descriptivo de la sección donde se encuentra el test. No incluir textos que pertenezcan a anexos, apéndices u otras secciones de apoyo. Si no identificas el section_title directamente, no alucines.. Simplemente pon 'Por definir'.. Con el section_id se podrá agrupar todo")
    test_name: str = Field(..., description="Nombre completo del test según el documento incluyendo el nombre del o los analitos (Ingredientes activos, impurezas, entre otros). Por ejemplo: 'Disolución de Acetaminofen', 'Valoración de Hidrocodona'. Si no identificas el nombre del test directamente, no alucines.. Simplemente pon 'Por definir'.. Con el section_id se podrá agrupar todo")
    test_type: Literal[
        # Tipos existentes en tu lista original
        "Descripción",
        "Identificación",
        "Valoración",
        "Impurezas",
        "Peso promedio",
        "Disolución",
        "Uniformidad de contenido",
        "Control microbiológico",
        "Humedad en cascarilla",
        "Humedad en contenido",        
        # Nuevos tipos extraídos de los SYSTEM_PROMPTS
        "Dureza",                                  # SYSTEM_PROMPT_DUREZA
        "Espesores",                               # SYSTEM_PROMPT_ESPESOR
        "Uniformidad de unidades de dosificación", # SYSTEM_PROMPT_UNIFORMIDAD_UNIDADES_DOSICACION
        "Pérdida por Secado",                      # SYSTEM_PROMPT_PERDIDA_POR_SECADO
        "Check list de autorización",              # SYSTEM_PROMPT_CHECKLIST
        "Hoja de trabajo instrumental HPLC",       # SYSTEM_PROMPT_INSTRUMENTAL
        "Solución",                                # SYSTEM_PROMPT_SOLUCION
        "Otros análisis"                           # SYSTEM_PROMPT_OTROS_ANALISIS
    ] = Field(..., description="Tipo del test analítico a configurar.")
    condiciones_cromatograficas: Optional[CondicionCromatografica] = Field(None, description="Listado de condiciones cromatográficas")
    soluciones: Optional[List[Solucion]] = Field(
        ...,
        description=(
            "Cada 'Solución ...' usada en ESTA prueba, con su preparación copiada VERBATIM (ver 'preparacion_solucion')."
        )
    )
    procedimiento: Procedimiento = Field(
        ...,
        description=(
            "⚠️ COPIAR VERBATIM de los Procedimientos de la PRUEBA que se encuentran en la subsección 'Procedimientos'. Es una descripción detallada y exhaustiva del procedimiento de la prueba."
            "EXCLUIR todo bloque que comience por Solución ... (Stock Estándar/Estándar/Stock Muestra/Muestra) y EXCLUIR Condiciones Cromatográficas."
            "Mantén fórmulas de cálculo y la sección Dónde: ... si está pegada al procedimiento."
            "No incluyas numeraciones de subapartados (p. ej. '7.2.1', '7.5.1.2') salvo que estén dentro del propio bloque de Procedimiento."
        )
    )
    criterio_aceptacion: Optional[CriterioAceptacion] = Field(
        ...,
        description=(
            "Texto literal bajo 'Criterio de Aceptación' de ESTA prueba (rangos, unidades, referencias). Copiar completo."
        )
    )
    equipos: Optional[List[str]] = Field(
        None,
        description=(
            "Equipos citados explícitamente en ESTA prueba, tal como aparecen. Ej.: "
            "['Espectrofotómetro UV', 'Cromatógrafo líquido', 'Aparato de desintegración']."
        )
    )
    reactivos: Optional[List[str]] = Field(
        None,
        description=(
            "Reactivos mencionados dentro de ESTA prueba (además de los globales), copiados literal. Ej.: "
            "['Metanol HPLC', 'Acetonitrilo HPLC']."
        )
    )
    procedimiento_sst: Optional[List[OrdenInyeccion]] = Field(None, description="Secuencia de inyecciones a realizar en el Test de adecuabilidad del sistema")


class TestSolutions(BaseModel):
    tests: Optional[List[TestSolution]] = Field(
        None,
        description=(
            "Lista de ensayos analíticos o soluciones descritos en el cuerpo principal del método. "
            "No extraer información ubicada en secciones de anexos, apéndices o referencias."
        )
    )
