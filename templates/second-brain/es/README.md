# 🌱 Cerebro Personal

> Tu *second brain* (segundo cerebro) mantenido por IA: notas en texto plano que Claude Code o Codex escriben, conectan y consultan por ti.

<!-- EMPIEZA AQUÍ: esta sección explica la plantilla. El prompt de arranque la reemplaza por tu propio encabezado. -->

## Qué es

Una plantilla para tener **toda tu vida en una carpeta**: quién eres, tu salud, tus relaciones, tu trabajo, tus finanzas, tus proyectos y lo que aprendes. Son archivos Markdown con Git, sin apps ni suscripciones. Tú hablas; la IA escribe, ordena y conecta.

Sigue el patrón **LLM Wiki** de Andrej Karpathy:

- **Nodos:** una nota por idea, dentro de 8 pilares ordenados por prioridad de vida.
- **Schema:** `CLAUDE.md` y `AGENTS.md`, las reglas que convierten a la IA en una bibliotecaria disciplinada.
- **Navegación:** este `README.md` (índice de todo) y `Bitacora.md` (el registro de cada cambio).
- **Tres operaciones:** ingesta (guardar), consulta (preguntar) y lint (mantener), con `apps/lint/lint.py` para la parte mecánica.

## Qué trae

```
Segundo Cerebro/
├── README.md        Puerta de entrada e índice maestro (una línea por nota)
├── Bitacora.md      Registro de cada cambio, solo se agrega al final
├── CLAUDE.md        El schema: cómo se escribe y conecta cada nota
├── AGENTS.md        Tu perfil y las reglas de la IA (lo leen Claude y Codex)
├── PROMPTS.md       8 prompts listos: arranque, ingesta, consulta, diario, lint...
├── 01-identidad/ … 08-aprendizaje/   Los 8 pilares, cada uno con su index.md
└── apps/lint/       Script que encuentra enlaces rotos y calcula los backlinks
```

Cada nota es un `.md` con un frontmatter corto (tipo, pilar, fechas, tags), una frase que resume la idea, el contenido y una sección `## Conexiones` con enlaces a otras notas. Esas conexiones son el grafo: la IA las sigue para responder con contexto.

¿Para qué sirve en la práctica? Para que la IA te responda con **tu** contexto: *"con lo que sabes de mis finanzas, ¿me conviene este crédito?"*, *"¿qué patrón se repite cuando abandono un hábito?"*, *"prepárame para hablar con mi jefe mañana"*. Y para que nada importante se pierda en un chat.

## Empieza en 3 pasos

**1. Ya la tienes.** Ask Your Mentors creó esta carpeta en tu computador. Si quieres respaldo, pídele a tu IA que la suba a un repositorio **privado** de GitHub; si no, déjala solo local.

**2. Deja que la IA te entreviste.** Abre Claude Code (recomendado) o Codex dentro de la carpeta y pega el **prompt de arranque** de [PROMPTS.md](PROMPTS.md). Te hace una pregunta a la vez, pilar por pilar, y va escribiendo tus primeras notas. Puedes pausar y retomar.

**3. Úsalo todos los días.** Cuando pase algo que valga la pena, *"Ingesta: ..."*. Cuando necesites claridad, *"Consulta: ..."*. Una vez por semana, el lint. Todos los prompts están en [PROMPTS.md](PROMPTS.md).

## Cómo leerlo

- **En GitHub:** los enlaces entre notas funcionan directo.
- **En Obsidian:** abre la carpeta y verás el grafo de conexiones.
- **En cualquier editor:** son archivos de texto.

## Privacidad

Aquí va a quedar tu vida entera. Mantén el repositorio **privado** o solo en tu computador. Nunca guardes contraseñas, claves ni números de cuenta completos. Ten en cuenta que lo que la IA lee se envía a su proveedor (Anthropic, OpenAI) según sus términos. Si prefieres que nada salga de tu equipo, usa un modelo local.

## Requisitos

- Git.
- Python 3.9 o superior (solo para el lint; sin librerías).
- Una IA que trabaje sobre archivos: [Claude Code](https://claude.com/claude-code) (recomendado) o [Codex](https://github.com/openai/codex).

## Créditos

- **Andrej Karpathy**, [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) (abril 2026): el patrón base. Una IA que mantiene una wiki en Markdown en vez de buscar en documentos sueltos; el schema en `CLAUDE.md`/`AGENTS.md`; las operaciones ingesta, consulta y lint; el índice con una línea por página y la bitácora con prefijo `## [fecha] tipo | título`.
- **Tiago Forte**, [Building a Second Brain](https://www.buildingasecondbrain.com/): el concepto de *second brain* (segundo cerebro) como sistema personal de conocimiento.
- **[AGENTS.md](https://agents.md/)** y la [documentación de memoria de Claude Code](https://code.claude.com/docs/en/memory): un solo archivo de reglas compartido entre Claude y Codex, importado con `@AGENTS.md`.
- **Harvard Study of Adult Development**: la razón de que los pilares vayan por prioridad de vida y de que las relaciones estén antes que el trabajo.

Plantilla creada por Jorge Toledo ([github.com/georgewashtol](https://github.com/georgewashtol)) a partir de su propio cerebro personal, que usa a diario.

## Licencia

MIT. Úsala, cámbiala y compártela.

<!-- FIN DE LA SECCIÓN DE LA PLANTILLA -->

---

## Índice maestro

Prioridad de vida: `01-03` el yo interior · `04` el yo con otros · `05-07` el yo produciendo · `08` el yo mejorando.

### 🪞 [Identidad](01-identidad/index.md)

_Quién soy: valores, principios, historia y reglas propias._

- [Quién Soy](01-identidad/Quien%20Soy.md): La página raíz: quién eres, qué valoras y hacia dónde vas. La llena el prompt de arranque. `identidad`

### 🌿 [Salud](02-salud/index.md)

_Cuerpo y mente: sueño, comida, ejercicio y emociones._

### 📓 [Diario](03-diario/index.md)

_Reflexiones y entradas con fecha._


### 🤝 [Personas](04-personas/index.md)

_Las relaciones importantes._


### 💼 [Trabajo](05-trabajo/index.md)

_Empleo, oficio, habilidades y empresa actual._

### 💰 [Finanzas](06-finanzas/index.md)

_Ingresos, gastos, deudas, patrimonio y metas._

### 🚀 [Proyectos](07-proyectos/index.md)

_Emprendimientos, marca personal e ideas en ejecución._

### 📚 [Aprendizaje](08-aprendizaje/index.md)

_Cursos, libros, certificaciones e investigación._

- [Cómo Funciona Este Cerebro](08-aprendizaje/Como%20Funciona%20Este%20Cerebro.md): El patrón LLM Wiki explicado: nodos, schema, navegación y las tres operaciones. `framework`
