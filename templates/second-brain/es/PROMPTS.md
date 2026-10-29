# Prompts listos para copiar y pegar

Ábrelos en **Claude Code** (recomendado) o **Codex**, con la terminal parada en la carpeta de tu cerebro. Cada prompt es un párrafo: cópialo entero.

---

## 1. Arranque: la IA te entrevista y llena tu cerebro

Úsalo una sola vez, al principio. Toma entre 30 y 90 minutos; puedes pausarlo y retomarlo cuando quieras con el prompt 2.

```text
Lee CLAUDE.md, AGENTS.md y README.md de esta carpeta: es mi cerebro personal y tú vas a ser quien lo mantiene. Quiero que me entrevistes para llenarlo. Reglas de la entrevista: hazme UNA pregunta a la vez y espera mi respuesta; empieza por mi perfil (nombre, cómo quiero que me llames, dónde vivo, a qué me dedico, mi meta del año, el tono que prefiero y lo que nunca debes hacer) y llena con eso la sección Perfil del dueño de AGENTS.md; luego recorre los pilares en orden (identidad, salud, personas, trabajo, finanzas, proyectos, aprendizaje), entre 4 y 8 preguntas por pilar, profundizando cuando algo sea importante; no inventes nada ni rellenes lo que no te dije, márcalo como pendiente; con mis respuestas llena 01-identidad/Quien Soy.md y crea los nodos que hagan falta siguiendo el schema (frontmatter, Conexiones, índice del pilar, README.md); al terminar cada pilar muéstrame un resumen de lo que escribiste y pregúntame si lo corrijo antes de seguir; cuando terminemos reemplaza la sección de la plantilla del README.md (entre los comentarios EMPIEZA AQUÍ y FIN) por un encabezado corto con mi nombre y una frase que me describa, corre python3 apps/lint/lint.py --aplicar, anota todo en Bitacora.md y haz commit. Empieza.
```

## 2. Retomar la entrevista

```text
Lee CLAUDE.md, AGENTS.md, README.md y la última entrada de Bitacora.md. Retoma la entrevista de arranque donde la dejamos: dime qué pilares faltan y sigue con el siguiente, una pregunta a la vez.
```

## 3. Ingesta del día a día

Para cualquier cosa que quieras guardar: una decisión, una conversación, una idea, un libro, un audio transcrito.

```text
Ingesta: [pega o cuenta aquí lo que pasó]. Busca si ya existe un nodo donde encaje y actualízalo; si no, crea uno nuevo siguiendo el schema. Conéctalo con los nodos relacionados, actualiza los índices y la bitácora, y muéstrame qué cambiaste antes del commit.
```

## 4. Consultar tu cerebro

```text
Consulta: [tu pregunta]. Responde solo con lo que está en mis nodos, citándolos con enlaces; si algo no está, dímelo en vez de rellenar con conocimiento general. Si la respuesta vale la pena guardarla, propónme un nodo nuevo.
```

Ejemplos de preguntas: *¿qué patrón se repite cada vez que abandono un hábito?*, *¿qué le prometí a mi hermana el mes pasado?*, *con lo que sabes de mis finanzas, ¿me conviene este crédito?*, *prepárame para la reunión de mañana con mi jefe usando lo que hay de él*.

## 5. Diario guiado (5 minutos)

```text
Diario de hoy: hazme tres preguntas cortas, una a la vez (qué pasó, qué decidí, qué noté de mí). Con mis respuestas crea la entrada en 03-diario con la fecha de hoy, conéctala con los nodos que toque y si aparece un patrón que ya vimos antes, dímelo.
```

## 6. Mantenimiento semanal (lint)

```text
Lint semanal: corre python3 apps/lint/lint.py y arregla los enlaces rotos. Luego revisa con criterio: contradicciones entre nodos, nodos huérfanos que deberían conectarse, conceptos que menciono mucho y no tienen nodo propio, y datos viejos que ya cambiaron. Muéstrame la lista antes de tocar nada; después aplica lo que apruebe, corre el lint con --aplicar, anota en la bitácora y haz commit.
```

## 7. Revisión mensual

```text
Revisión del mes: lee la bitácora de los últimos 30 días y los nodos que cambiaron. Dame en una página: qué avancé por pilar, qué se estancó, qué patrones se repitieron y una sola cosa para enfocarme el próximo mes. Guárdalo como nodo en 03-diario con el nombre "Revisión AAAA-MM".
```

## 8. Importar lo que ya tienes

```text
Importación: en la carpeta [ruta] tengo notas viejas exportadas de [Notion / Obsidian / Apple Notas / Google Keep / un chat exportado]. Léelas, agrúpalas por pilar y proponme qué se vuelve nodo nuevo, qué se fusiona con nodos existentes y qué se descarta. No escribas nada hasta que apruebe el plan; después hazlo por tandas de un pilar a la vez.
```

---

## Consejos

- **Habla, no escribas.** Dicta las respuestas o graba un audio y transcríbelo: saldrán más completas.
- **Una sesión, un tema.** Si la conversación se alarga y la IA deja de llamarte por tu apodo canario, abre una sesión nueva: el cerebro guarda el contexto, no el chat.
- **Con Codex:** su sandbox por defecto no deja escribir en `.git`, así que el commit lo haces tú (`git add -A && git commit -m "..."`) o le das permiso de escritura completo para esa sesión.
- **Privado siempre.** Si lo subes a GitHub, que sea un repositorio privado.
