# Cerebro Personal: el schema

## Qué es esto

Este repositorio es el **cerebro personal** de su dueño: una carpeta de notas Markdown, versionada con Git, que funciona como fuente de verdad de su vida (identidad, salud, relaciones, trabajo, finanzas, proyectos y aprendizaje). Está diseñado para que una IA (Claude Code, Codex u otra) lo lea, lo mantenga y lo conecte, y para que una persona lo lea en GitHub, en Obsidian o en cualquier editor.

Sigue el patrón **LLM Wiki** de Andrej Karpathy: un conjunto de notas que una IA mantiene, gobernado por un schema (este archivo), navegado por un índice maestro (`README.md`) y registrado en una bitácora (`Bitacora.md`).

## Reglas de comportamiento

Las reglas de cómo debe trabajar la IA y quién es el dueño viven en `AGENTS.md` (Codex lo lee directo; Claude lo recibe con esta línea):

@AGENTS.md

## Filosofía del formato

- **Markdown es el formato.** Cada nodo es un `.md` plano, legible por cualquier persona e IA. Si la herramienta muere, los archivos viven.
- **Cero carpetas técnicas.** Nada de CSS, HTML ni JavaScript en el conocimiento. Única excepción: `apps/`, donde vive código propio (por ejemplo el lint).
- **Cero dependencias.** Markdown + Git. Las apps de `apps/` usan solo la biblioteca estándar de Python.
- **Simple antes que completo.** Cada nodo debe ganarse su lugar. Menos archivos, menos capas.

## El patrón LLM Wiki (las 3 capas)

1. **Los nodos** (`.md` dentro de cada pilar): la capa de conocimiento. La IA escribe y conecta; el dueño decide y lee. Cada nodo es una página de un concepto, sistema, idea, persona o registro.
2. **El schema** (este archivo): las reglas. Convierte a la IA en un trabajador de conocimiento disciplinado.
3. **La navegación:** `README.md` (índice maestro con una línea por nodo) y `Bitacora.md` (registro de operaciones, solo se agrega al final).

### Las 3 operaciones

- **Ingesta:** entra una fuente o idea nueva. Se conversa, se escribe o actualiza el nodo, se agrega a `README.md` y al `index.md` del pilar, se tocan las `## Conexiones` de los nodos relacionados y se anota en `Bitacora.md`.
- **Consulta:** el dueño pregunta. La IA busca en los nodos, los lee y responde citándolos con enlaces. Si la respuesta merece quedarse, se archiva como nodo nuevo.
- **Lint:** mantenimiento. `python3 apps/lint/lint.py` reporta enlaces rotos y nodos huérfanos; con `--aplicar` reescribe las secciones `## Referenciado por`. Lo que queda para la IA es el juicio: contradicciones entre nodos, conceptos mencionados sin nodo propio y conexiones que faltan.

## Estructura

```
Segundo Cerebro/
├── README.md          Índice maestro: catálogo de todos los nodos
├── Bitacora.md        Registro de operaciones (ingesta, consulta, estructura, lint)
├── CLAUDE.md          Este archivo: el schema
├── AGENTS.md          Reglas de la IA y perfil del dueño
├── PROMPTS.md         Prompts listos para copiar y pegar
├── 01-identidad/      Quién soy: valores, principios, historia, reglas propias
├── 02-salud/          Cuerpo y mente: sueño, comida, ejercicio, emociones
├── 03-diario/         Reflexiones y entradas con fecha
├── 04-personas/       Relaciones importantes
├── 05-trabajo/        Empleo, oficio, habilidades, empresa actual
├── 06-finanzas/       Ingresos, gastos, deudas, patrimonio, metas
├── 07-proyectos/      Emprendimientos, marca personal, ideas en ejecución
├── 08-aprendizaje/    Cursos, libros, certificaciones, investigación
└── apps/              Excepción: código propio (no son nodos)
```

Los pilares van numerados por **prioridad de vida**: `01-03` el yo interior, `04` el yo con otros, `05-07` el yo produciendo, `08` el yo mejorando. Se pueden renombrar o agregar (el lint detecta cualquier carpeta que empiece por dos dígitos y un guion). Cada pilar tiene su `index.md`. Estructura **plana**: sin subcarpetas dentro de los pilares.

## Convenciones de cada nodo

```markdown
---
tipo: concepto
pilar: identidad
creado: 2026-01-15
actualizado: 2026-01-15
tags: [habitos, sueño]
---

# Título del Nodo

> Una frase que captura la esencia del nodo.

---

## Sección

Contenido...

## Conexiones

- [Otro Nodo](../05-trabajo/Otro%20Nodo.md): por qué se conectan

## Referenciado por

- [Nodo que me enlaza](../01-identidad/Nodo%20que%20me%20enlaza.md)
```

### Reglas

- **Carpetas:** prefijo numérico + nombre en minúscula (`01-identidad`).
- **Archivos:** título natural con espacios y extensión `.md` (`Toma de Decisiones.md`).
- **Frontmatter YAML obligatorio** con los atributos de abajo.
- **Enlaces:** Markdown con ruta relativa y espacios como `%20`, para que funcionen en GitHub y Obsidian: `[Título](../05-trabajo/Foo%20Bar.md)`.
- **Conexiones:** todo nodo tiene `## Conexiones` con al menos 1 enlace a otro nodo. Son las aristas del grafo.
- **Referenciado por:** los enlaces entrantes. Los mantiene el lint; no se editan a mano.
- **Idioma:** el del dueño (ver `AGENTS.md`).

### Frontmatter

- `tipo`: concepto | sistema | principio | proyecto | persona | diario | registro | idea | investigacion | framework | practica | meta-analisis | identidad
- `pilar`: identidad | salud | diario | personas | trabajo | finanzas | proyectos | aprendizaje (siempre el de la carpeta donde vive)
- `creado` y `actualizado`: AAAA-MM-DD
- `tags`: lista YAML

## Para la IA que lo lee

- `README.md` es la puerta de entrada: léelo primero para orientarte.
- Este repositorio es la **fuente de verdad**: busca aquí antes de responder con conocimiento general.
- Al crear un nodo: estructura mínima, agrégalo a `README.md` y al `index.md` del pilar, conéctalo y anota la ingesta en `Bitacora.md`.
- Nunca inventes datos personales. Si falta un dato, pregúntalo o márcalo como pendiente. Una ausencia de datos no es un cero.

## Flujo Git

1. Antes de empezar: `git pull --ff-only` (si hay remoto).
2. Al cerrar cada sesión con cambios: `python3 apps/lint/lint.py --aplicar`, anotar en `Bitacora.md`, revisar el diff y hacer commit con un mensaje corto y claro.
3. Push solo si el dueño configuró un remoto **privado** y lo autorizó en `AGENTS.md`.
4. Si el cambio toca muchos nodos o es delicado, mostrar un resumen al dueño antes del commit.
