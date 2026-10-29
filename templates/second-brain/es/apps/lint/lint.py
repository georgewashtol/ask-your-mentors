#!/usr/bin/env python3
"""Lint del cerebro: la tercera operacion del patron LLM Wiki, hecha software.

`## Conexiones` son las aristas salientes y se escriben al crear el nodo.
`## Referenciado por` son las entrantes y solo se pueden calcular mirando el repo
entero: eso hace este script. Sin ellas, quien lee un nodo (persona o IA) puede
seguir hacia adelante pero no hacia atras.

    python3 apps/lint/lint.py              # solo reporta enlaces rotos, huerfanos y backlinks desactualizados
    python3 apps/lint/lint.py --aplicar    # reescribe las secciones 'Referenciado por'

Solo toca esa seccion. Nunca el frontmatter, nunca el cuerpo, nunca Conexiones.
Los pilares son las carpetas de primer nivel que empiezan por dos digitos y un
guion (01-identidad, 09-lo-que-quieras...): se pueden renombrar o agregar.
"""
from __future__ import annotations

import os
import re
import sys
import urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(BASE))
RAIZ = ["README.md", "Bitacora.md", "CLAUDE.md", "AGENTS.md", "PROMPTS.md"]
ENLACE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
SECCION = "## Referenciado por"

# El encabezado DE VERDAD: una linea que es exactamente el titulo, no cualquier
# aparicion del texto. Un nodo que hable del schema (por ejemplo el que
# documenta este lint) menciona `## Referenciado por` entre comillas en medio
# de un parrafo, y partir por ahi le cortaria el cuerpo entero: sus enlaces
# salientes desaparecerian del grafo sin que nada avisara.
ENCABEZADO = re.compile(r"^## Referenciado por\s*$", re.M)


def partir(texto: str) -> tuple[str, str]:
    """(cuerpo, seccion de backlinks). La segunda es '' si no existe."""
    m = ENCABEZADO.search(texto)
    if not m:
        return texto, ""
    return texto[:m.start()], texto[m.start():]

# Archivos que NO deben recibir backlinks: los indices de pilar (son navegacion,
# no conocimiento) y los registros generados solos, que se acumulan y ensuciarian
# la seccion de cualquier nodo que citen.
def es_generado(rel: str) -> bool:
    n = os.path.basename(rel)
    return n.startswith(("Semana 20", "Mes 20"))


def pilares() -> list:
    return sorted(d for d in os.listdir(REPO)
                  if re.match(r"^\d\d-", d) and os.path.isdir(os.path.join(REPO, d)))


def es_nodo(rel: str) -> bool:
    return (rel.split("/")[0] in pilares() and rel.endswith(".md")
            and not rel.endswith("index.md"))


def cargar() -> dict:
    out = {}
    for p in pilares():
        d = os.path.join(REPO, p)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".md"):
                rel = f"{p}/{f}"
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    out[rel] = fh.read()
    for f in RAIZ:
        ruta = os.path.join(REPO, f)
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as fh:
                out[f] = fh.read()
    return out


def analizar(nodos: dict) -> tuple[list, dict]:
    """Devuelve (enlaces rotos, {destino: set(origenes)})."""
    rotos = []
    entrantes = {k: set() for k in nodos}
    for origen, texto in nodos.items():
        base = os.path.dirname(origen)
        # CLAUDE.md trae enlaces de EJEMPLO en la plantilla del schema; no son
        # enlaces rotos, son documentacion de como se escribe uno.
        if origen == "CLAUDE.md":
            continue
        # Los enlaces de `## Referenciado por` NO son aristas salientes: son las
        # entrantes ya calculadas. Contarlos crearia un lazo: A cita a B, el
        # lint escribe A en los backlinks de B, y en la siguiente corrida eso se
        # lee como que B cita a A. En dos o tres pasadas el grafo termina
        # completamente bidireccional y sin informacion. Por eso el lint solo
        # mira lo que hay ANTES de esa seccion.
        texto = partir(texto)[0]
        for etiqueta, destino in ENLACE.findall(texto):
            if destino.startswith(("http", "#", "mailto:")):
                continue
            limpio = urllib.parse.unquote(destino.split("#")[0])
            absoluto = os.path.normpath(os.path.join(REPO, base, limpio))
            rel = os.path.relpath(absoluto, REPO)
            if not os.path.exists(absoluto):
                rotos.append((origen, etiqueta, destino))
            elif rel in entrantes:
                entrantes[rel].add(origen)
    return rotos, entrantes


def titulo_de(rel: str, nodos: dict) -> str:
    """El titulo real del nodo: su `# H1`, no el nombre del archivo.

    Importa mas de lo que parece. El archivo se llama `Quien Soy.md` pero el
    nodo se titula "Quién Soy", con tilde. Derivar la etiqueta del nombre de
    archivo borraria eso en cada corrida del lint:
    seria una herramienta de mantenimiento que degrada lo que mantiene.
    """
    for linea in nodos.get(rel, "").splitlines():
        if linea.startswith("# "):
            return linea[2:].strip()
    return os.path.basename(rel)[:-3]


def enlace_a(origen: str, destino: str, nodos: dict, sufijo: str = "") -> str:
    """Enlace markdown relativo, con los espacios codificados para GitHub."""
    rel = os.path.relpath(os.path.join(REPO, origen),
                          os.path.join(REPO, os.path.dirname(destino)))
    return f"- [{titulo_de(origen, nodos)}]({urllib.parse.quote(rel)}){sufijo}"


def sufijos_actuales(texto: str) -> dict:
    """Las explicaciones ': por que' que alguien escribio a mano, por archivo.

    La seccion la mantiene el lint, pero si alguien se tomo el trabajo de anotar
    por que dos nodos se conectan, esa frase no se tira: se vuelve a colgar del
    enlace correspondiente.
    """
    cuerpo, seccion = partir(texto)
    if not seccion:
        return {}
    out = {}
    for linea in seccion.splitlines():
        m = re.match(r"- \[[^\]]+\]\(([^)]+)\)(\s*(?::|\s-|\s\u2014)\s+.+)$", linea.strip())
        if m:
            out[os.path.basename(urllib.parse.unquote(m.group(1)))] = m.group(2).rstrip()
    return out


def bloque(destino: str, origenes: set, nodos: dict) -> str:
    viejos = sufijos_actuales(nodos.get(destino, ""))
    lineas = sorted(
        enlace_a(o, destino, nodos, viejos.get(os.path.basename(o), ""))
        for o in origenes)
    return SECCION + "\n\n" + "\n".join(lineas) + "\n"


def reescribir(texto: str, nuevo: str) -> str:
    """Reemplaza (o agrega al final) la seccion de backlinks. Nada mas."""
    cuerpo, seccion = partir(texto)
    return cuerpo.rstrip() + "\n\n" + nuevo


def main() -> None:
    aplicar = "--aplicar" in sys.argv
    nodos = cargar()
    rotos, entrantes = analizar(nodos)

    print(f"Lint del cerebro: {len(nodos)} archivos revisados\n")

    print(f"Enlaces rotos: {len(rotos)}")
    for o, e, d in rotos:
        print(f"  {o}: [{e}] -> {d}")

    huerfanos = [n for n, e in entrantes.items()
                 if es_nodo(n) and not es_generado(n) and not e]
    print(f"\nNodos sin un solo enlace entrante: {len(huerfanos)}")
    for h in huerfanos:
        print(f"  {h}")

    cambios = []
    for destino, origenes in entrantes.items():
        if not es_nodo(destino) or es_generado(destino):
            continue
        reales = {o for o in origenes if es_nodo(o) and not es_generado(o)}
        if not reales:
            continue
        nuevo = bloque(destino, reales, nodos)
        actual = nodos[destino]
        propuesto = reescribir(actual, nuevo)
        if propuesto != actual:
            cambios.append((destino, len(reales), propuesto))

    print(f"\n'Referenciado por' desactualizado en {len(cambios)} nodos")
    if not aplicar:
        for d, n, _ in sorted(cambios, key=lambda x: -x[1])[:10]:
            print(f"  {d} ({n} entrantes)")
        if cambios:
            print("\nCorre con --aplicar para reescribir solo esa seccion.")
        return

    for destino, _, propuesto in cambios:
        with open(os.path.join(REPO, destino), "w", encoding="utf-8") as fh:
            fh.write(propuesto)
    print(f"reescritos: {len(cambios)}")


if __name__ == "__main__":
    main()
