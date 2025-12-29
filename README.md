## Flujo Side-by-Side (Proposed Column)

1. **Paso 0 – Extracción inicial**
   - Ejecutar `sbs_proposed_column_to_pdf_md(dir_document=...)`.
   - Resultado principal: `/proposed_method/method_metadata_TOC.json` (modelo `SideBySideModelCompleto`).
   - Resultado auxiliar: `/proposed_method/method_metadata_metrics.json` con métricas de:
     - Páginas totales procesadas.
     - Índices de páginas con baja confianza al separar columnas.
     - Metadata de división por página (divider_x, header_end, shapes).
     - Estadísticas de consolidación (chunks totales, chunks con anotaciones, errores de parseo).
   - Revisar los mensajes del tool para confirmar si hubo baja confianza y si el resumen de metadata luce coherente.

2. **Paso 1 – Limpieza de markdown**
   - Ejecutar `test_solution_clean_markdown(base_path="/proposed_method")` una sola vez.
   - Este paso usa exclusivamente `method_metadata_TOC.json`; no depende del archivo de métricas, pero el analista debe consultarlo si la limpieza devuelve contenido sospechoso.

3. **Paso 2 – Extracción estructurada**
   - Llamar en paralelo a `test_solution_structured_extraction(id=?, base_path="/proposed_method")` para cada id reportado por el paso anterior.
   - Si algún id falla, verificar en `method_metadata_metrics.json` si hubo errores de parsing en los chunks correspondientes.

4. **Paso 3 – Consolidación**
   - Ejecutar `consolidate_test_solution_structured(base_path="/proposed_method")`.
   - Confirmar que `/proposed_method/test_solution_structured_content.json` esté poblado.

### Validación manual recomendada

1. Revisar el PDF y asegurarse de que el marcador de baja confianza (si existe) coincide con páginas de layout atípico.
2. Abrir `/proposed_method/method_metadata_TOC.json` y confirmar que:
   - `tabla_de_contenidos` enumera cada sección “IDENTIFICACIÓN”, “Criterio de aceptación”, “Soluciones”, etc.
   - `markdown_completo` conserva notas como “Se elimina la prueba”.
3. Validar que los valores de `avg_divider_x` y `column_split_metadata` sean consistentes (no extremos). Si no, repetir el paso 0 ajustando `DEFAULT_HEADER_PERCENT`/`DEFAULT_MARGIN_PX`.
4. Ejecutar los pasos 1–3 y comparar el resultado final con el método actual para detectar divergencias tempranas.

