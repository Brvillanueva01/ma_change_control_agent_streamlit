from __future__ import annotations
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, model_validator
import re

class SideBySideModel(BaseModel):
    apis: Optional[List[str]] = Field(
        None,
        description=(
            "Listado literal de los ingredientes activos (APIs) tal como aparecen en los encabezados o notas "
            "del método propuesto (p.ej. 'NAPROXENO SÓDICO 10-0514 Versión 02'). "
            "Preservar mayúsculas, potencias, sales y sinónimos, así como los separadores originales. "
            "Si se listan múltiples APIs, mantener el orden textual exacto."
        ),
    )
    nombre_producto: Optional[str] = Field(
        None,
        description=(
            "Nombre comercial/técnico del producto tal como aparece en el bloque principal de encabezado de la columna propuesta. "
            "Incluir códigos de cambio, versión o notas si comparten la misma línea (p.ej. 'SC-25-777 MODIFICACIÓN PROPUESTA'). "
            "Ignorar repeticiones en pies de página y mantener exactamente el formato, mayúsculas y potencias."
        ),
    )
    tabla_de_contenidos: Optional[List[str]] = Field(
        None,
        description=(
            "Lista ORDENADA de los títulos principales (Nivel 1) de la columna propuesta. "
            "Solo incluir encabezados que aparecen como bloques separados (p.ej. 'IDENTIFICACIÓN A (IR) (USP)'), "
            "sin repetir descripciones, criterios de aceptación, procedimientos ni notas internas. "
            "Instrucciones: "
            "1. CITA TEXTUAL: copiar cada encabezado exactamente como en el PDF (mantener mayúsculas, tildes, siglas USP/<232>, etc.). "
            "   **No traduzcas; conserva el idioma original del documento (inglés o español según aplique).** "
            "2. NIVEL: registrar únicamente los encabezados de prueba o sección (DESCRIPCIÓN, PUNTO DE FUSIÓN, LÍMITE DE NAPROXENO LIBRE...). "
            "3. EXCLUSIONES: NO incluir subtítulos como 'Soluciones', 'Procedimiento', 'Criterio de aceptación', notas u observaciones. "
            "4. ORDEN: respetar el orden de aparición desde la parte superior hasta la inferior del documento. "
            "5. FORMATO: devolver un elemento de lista por encabezado, sin prefijos adicionales ni numeraciones artificiales."
        ),
    )

class SideBySideModelCompleto(BaseModel):
    apis: Optional[List[str]] = Field(
        None,
        description=(
            "Listado literal de los ingredientes activos (APIs) tal como aparecen en los encabezados o notas "
            "del método propuesto (p.ej. 'NAPROXENO SÓDICO 10-0514 Versión 02'). "
            "Preservar mayúsculas, potencias, sales y sinónimos, así como los separadores originales. "
            "Si se listan múltiples APIs, mantener el orden textual exacto."
        ),
    )
    nombre_producto: Optional[str] = Field(
        None,
        description=(
            "Nombre comercial/técnico del producto tal como aparece en el bloque principal de encabezado de la columna propuesta. "
            "Incluir códigos de cambio, versión o notas si comparten la misma línea (p.ej. 'SC-25-777 MODIFICACIÓN PROPUESTA'). "
            "Ignorar repeticiones en pies de página y mantener exactamente el formato, mayúsculas y potencias."
        ),
    )
    tabla_de_contenidos: Optional[List[str]] = Field(
        None,
        description=(
            "Misma lista ORDENADA de títulos principales (Nivel 1) descrita en `SideBySideModel`. "
            "Debe contener únicamente las pruebas de la columna propuesta (DESCRIPCIÓN, PUNTO DE FUSIÓN, IDENTIFICACIÓN A/B, etc.), "
            "copiadas literalmente con sus paréntesis USP/BP/EP cuando apliquen. "
            "No traduzcas; mantén el idioma original presente en el PDF."
            "Excluir subtítulos internos como 'Soluciones', 'Procedimiento', 'Criterio de aceptación', notas o cálculos."
        ),
        #Breiner estuvo aqui 
    )
    markdown_completo: str = Field(
        ...,
        description=(
            "Markdown completo de la columna del método propuesto, preservando el orden y el formato del PDF (listas, tablas, notas en negrilla). "
            "Debe incluir encabezados, subtítulos, procedimientos, criterios de aceptación, notas regulatorias y cualquier comentario 'Se elimina la prueba'. "
            "Mantener el idioma original y no alterar la ortografía; únicamente convertir a markdown respetando saltos y jerarquías."
        ),
    )
