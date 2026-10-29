---
tipo: framework
pilar: aprendizaje
creado: 2026-01-15
actualizado: 2026-01-15
tags: [llm-wiki, ia, sistema]
---

# Cómo Funciona Este Cerebro

> Notas en texto plano que una IA mantiene y conecta: tú decides y lees, ella escribe y ordena.

---

## La idea

Andrej Karpathy propuso el patrón **LLM Wiki**: en vez de pedirle a una IA que recuerde tu vida (no puede), le das una carpeta de notas Markdown con reglas claras y la IA se vuelve la bibliotecaria. Cada conversación deja la carpeta un poco mejor.

## Las 3 capas

| Capa | Archivo | Qué hace |
|---|---|---|
| Nodos | un `.md` por idea, dentro de cada pilar | El conocimiento |
| Schema | `CLAUDE.md` y `AGENTS.md` | Las reglas que sigue la IA |
| Navegación | `README.md` y `Bitacora.md` | El índice y el registro de cambios |

## Las 3 operaciones

1. **Ingesta:** le cuentas algo a la IA (una decisión, una idea, una conversación, un libro). Ella crea o actualiza el nodo, lo conecta y lo anota en la bitácora.
2. **Consulta:** le preguntas ("¿qué decidí sobre mi deuda?", "¿qué patrón se repite cuando abandono un hábito?"). Ella busca en los nodos y te responde citándolos.
3. **Lint:** mantenimiento. `python3 apps/lint/lint.py` encuentra enlaces rotos y notas sin conexiones; la IA revisa contradicciones y conexiones que faltan.

## Por qué funciona

- **Texto plano y Git:** es tuyo para siempre, se lee sin ninguna app y cada cambio queda en el historial.
- **Conexiones obligatorias:** cada nodo enlaza a otro, así la IA (y tú) navegan de una idea a sus causas y consecuencias.
- **Una sola fuente de verdad:** la IA busca aquí antes de opinar con conocimiento general, así sus respuestas son sobre TU vida.

## Conexiones

- [Quién Soy](../01-identidad/Quien%20Soy.md): la página raíz que todo lo demás amplía.

## Referenciado por

- [Quién Soy](../01-identidad/Quien%20Soy.md)
