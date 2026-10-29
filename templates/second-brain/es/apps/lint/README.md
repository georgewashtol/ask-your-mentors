# Lint del cerebro

La tercera operación del patrón LLM Wiki, hecha software. Solo biblioteca estándar de Python.

```bash
python3 apps/lint/lint.py              # reporta
python3 apps/lint/lint.py --aplicar    # reescribe las secciones 'Referenciado por'
python3 apps/lint/pruebas.py           # pruebas sobre un repo de mentira
```

| Chequeo | Qué significa |
| --- | --- |
| Enlaces rotos | un `[texto](ruta.md)` que apunta a un archivo que no existe |
| Nodos huérfanos | nodos sin un solo enlace entrante: existen pero nadie llega a ellos |
| `Referenciado por` | los backlinks, la capa de aristas entrantes del grafo |

Garantías (cada una tiene su prueba):

1. Solo toca `## Referenciado por`: nunca el frontmatter, el cuerpo ni `## Conexiones`.
2. La etiqueta del enlace sale del `# Título` del nodo, no del nombre del archivo (respeta tildes y emojis).
3. Los backlinks no cuentan como enlaces salientes, así que converge: la segunda corrida no cambia nada.
4. Conserva las explicaciones escritas a mano después de un backlink (`- [A](A.md): por qué`).
5. Los pilares se detectan solos: cualquier carpeta que empiece por dos dígitos y un guion.
