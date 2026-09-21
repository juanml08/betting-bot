# Reglas del proyecto - Betting Bot

## Objetivo

Este archivo define las reglas obligatorias que cualquier agente de IA (ChatGPT, Claude, Copilot, Codex u otro) debe seguir al trabajar en este proyecto.

Estas reglas tienen prioridad sobre cualquier suposición del agente.

El objetivo es mantener una arquitectura consistente, cambios pequeños y un historial claro de por qué se tomó cada decisión.

---

# Regla 1 — Respetar la arquitectura

Nunca cambies la arquitectura del proyecto por iniciativa propia.

No:

- mover responsabilidades entre capas sin autorización;
- cambiar el flujo del sistema;
- fusionar módulos porque "parece más simple";
- introducir patrones complejos sin necesidad.

Si detectas una mejora arquitectónica:

1. no la implementes;
2. explícala;
3. espera aprobación.

---

# Regla 2 — El prompt es la fuente de verdad

El prompt del proyecto define el producto.

No agregues funcionalidades que no fueron solicitadas.

No elimines funcionalidades existentes sin autorización.

Si alguna parte del prompt es ambigua:

- pregunta antes de asumir.

---

# Regla 3 — Cambios pequeños

Cada intervención debe resolver una sola tarea claramente definida.

Evita:

- refactorizaciones masivas;
- cambios en múltiples módulos cuando no son necesarios;
- modificar archivos no relacionados.

Si necesitas tocar varios archivos, explica por qué.

---

# Regla 4 — Explicar siempre el razonamiento

Después de terminar cualquier tarea debes explicar:

- qué hiciste;
- por qué lo hiciste así;
- cómo encaja dentro de la arquitectura;
- qué problema resuelve.

No basta con decir "implementado".

Debe entenderse la regla de negocio detrás del código.

---

# Regla 5 — Siempre entregar un resumen

Al finalizar cada tarea entrega un resumen con este formato.

## Resumen

### Archivos creados

- archivo
- archivo

### Archivos modificados

- archivo
- archivo

### Qué cambió

Descripción breve.

### Por qué

Explicación de la decisión tomada.

### Cómo probarlo

Pasos para verificar.

### Tests ejecutados

Comando utilizado, cantidad de tests ejecutados/exitosos/fallidos y resultado final (ver Regla 11). Si algún test no pudo ejecutarse, indicar cuál y por qué.

### Siguiente paso recomendado

La siguiente tarea lógica sin implementarla.

---

# Regla 6 — No asumir datos

Nunca inventes:

- APIs;
- endpoints;
- respuestas;
- estadísticas;
- modelos;
- tablas;
- nombres de archivos.

Si algo no existe todavía, créalo explícitamente.

---

# Regla 7 — Mantener responsabilidades separadas

Cada módulo debe tener una única responsabilidad.

Ejemplos:

- Data Providers obtienen datos.
- Feature Engine calcula estadísticas.
- Prediction genera probabilidades.
- Value Engine compara probabilidades contra cuotas.
- Risk Manager calcula stake.
- Persistence guarda información.

No mezclar responsabilidades.

---

# Regla 8 — Pensar primero en datos históricos

Antes de pensar en apuestas reales:

1. obtener datos;
2. almacenarlos;
3. analizarlos;
4. hacer backtesting;
5. validar resultados.

El sistema debe poder demostrar si una estrategia funciona.

---

# Regla 9 — No vender certezas

El sistema trabaja con:

- probabilidades;
- incertidumbre;
- riesgo;
- valor esperado.

Nunca diseñar componentes que presenten una apuesta como "segura".

---

# Regla 10 — Compatibilidad futura

Todo componente nuevo debe poder reemplazarse en el futuro sin romper el resto del sistema.

Ejemplos:

- cambiar proveedor de datos;
- cambiar modelo predictivo;
- agregar nuevos deportes;
- agregar nuevos mercados.

Evitar acoplamientos innecesarios.

---

# Regla 11 — Tests obligatorios

Toda funcionalidad que contenga lógica de negocio debe tener tests automatizados.

El agente debe:

1. Identificar qué comportamiento debe probarse antes de implementar.
2. Crear o modificar los tests necesarios.
3. Ejecutar los tests después de realizar los cambios.
4. Verificar que todos los tests relacionados con la modificación pasen.
5. Cuando sea razonablemente posible, ejecutar también la suite completa del proyecto.
6. Informar claramente el resultado de los tests.

No se debe considerar una tarea terminada únicamente porque el código fue escrito.

La tarea se considera terminada cuando:

* el código está implementado;
* los tests correspondientes existen;
* los tests pasan;
* las demás validaciones necesarias pasan.

Si un test falla:

* no ocultar el fallo;
* no eliminar el test para conseguir que pase;
* no modificar una prueba únicamente para adaptarla incorrectamente al código;
* investigar la causa;
* corregirla si pertenece a la tarea actual;
* si requiere una decisión o cambio fuera del alcance, detenerse y explicarlo.

El resumen final debe incluir una sección:

### Tests ejecutados

Indicar:

* comando utilizado;
* cantidad de tests ejecutados;
* cantidad de tests exitosos;
* cantidad de tests fallidos;
* resultado final.

Ejemplo:

```
Tests ejecutados:
pytest

42 passed
0 failed

Resultado: OK
```

Si existen tests que no pudieron ejecutarse, debe indicarse claramente cuáles y por qué.

## Tests antes y después

Cuando una modificación afecte comportamiento existente:

1. ejecutar los tests existentes relevantes antes de modificar el código cuando sea posible;
2. implementar el cambio;
3. crear/modificar los tests;
4. ejecutar nuevamente los tests;
5. verificar que no se hayan introducido regresiones.

## No confiar únicamente en tests

Los tests automatizados no reemplazan otras validaciones.

Cuando corresponda también deben verificarse:

* linting;
* formateo;
* type checking;
* migraciones;
* endpoints;
* integración frontend/backend;
* comandos de aplicación;
* cualquier otra validación necesaria para la tarea.

El agente debe indicar cuáles ejecutó y cuáles no.

---

# Regla 12 — No adelantar fases

Respeta el orden del proyecto.

No implementes funcionalidades de fases futuras porque "aprovechamos".

Cada fase debe quedar estable antes de avanzar.

---

# Regla 13 — Documentar decisiones importantes

Cuando una decisión afecte la arquitectura o el dominio del proyecto:

- explica el motivo;
- explica las alternativas;
- deja claro el impacto futuro.

Esto facilita retomar el proyecto meses después.

---

# Filosofía del proyecto

Este proyecto busca construir un sistema serio de análisis de apuestas basado en datos.

Las decisiones deben priorizar:

- claridad;
- mantenibilidad;
- evidencia estadística;
- validación mediante backtesting;
- arquitectura escalable.

Si existe una solución más llamativa pero menos verificable, se prefiere la solución verificable.
