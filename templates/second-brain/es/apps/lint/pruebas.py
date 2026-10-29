#!/usr/bin/env python3
"""Pruebas del lint. Sin dependencias: `python3 pruebas.py`.

El lint es la herramienta con **mayor radio de daño** del repo: reescribe una
seccion en muchos nodos de una sola corrida, y sus tres bugs conocidos no daban
error: borraban informacion en silencio. Un fallo aca no se nota hasta que
alguien busca un backlink que ya no esta.

Cada caso de abajo corresponde a algo que de verdad se rompio. Se prueban sobre
un repo de mentira en un directorio temporal: el cerebro real nunca se toca.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import lint  # noqa: E402

FALLOS = []


def revisar(nombre: str, ok: bool, detalle: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FALLA'} {nombre}" + (f": {detalle}" if not ok and detalle else ""))
    if not ok:
        FALLOS.append(nombre)


def repo(archivos: dict):
    """Crea un repo de mentira y apunta el lint ahi. Devuelve la ruta."""
    d = tempfile.mkdtemp(prefix="lint-prueba-")
    for rel, contenido in archivos.items():
        ruta = os.path.join(d, rel)
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(contenido)
    lint.REPO = d
    return d


def leer(d: str, rel: str) -> str:
    with open(os.path.join(d, rel), encoding="utf-8") as fh:
        return fh.read()


def correr(d: str):
    """Aplica el lint una vez. Devuelve cuantos archivos reescribio."""
    nodos = lint.cargar()
    _, entrantes = lint.analizar(nodos)
    n = 0
    for destino, origenes in entrantes.items():
        if not lint.es_nodo(destino) or lint.es_generado(destino):
            continue
        reales = {o for o in origenes if lint.es_nodo(o) and not lint.es_generado(o)}
        if not reales:
            continue
        nuevo = lint.bloque(destino, reales, nodos)
        propuesto = lint.reescribir(nodos[destino], nuevo)
        if propuesto != nodos[destino]:
            with open(os.path.join(d, destino), "w", encoding="utf-8") as fh:
                fh.write(propuesto)
            n += 1
    return n


NODO = "---\ntipo: concepto\npilar: salud\ncreado: 2026-01-01\ntags: [x]\n---\n\n# {titulo}\n\n{cuerpo}\n"


# ---------------------------------------------------------------- casos

def caso_backlink_basico():
    d = repo({
        "02-salud/A.md": NODO.format(titulo="Nodo A", cuerpo="## Conexiones\n\n- [Nodo B](B.md): porque si"),
        "02-salud/B.md": NODO.format(titulo="Nodo B", cuerpo="Contenido."),
    })
    correr(d)
    b = leer(d, "02-salud/B.md")
    revisar("backlink basico: B queda referenciado por A",
            "## Referenciado por" in b and "- [Nodo A](A.md)" in b, b[-120:])
    revisar("backlink basico: no se toca el frontmatter", "tipo: concepto" in b)
    shutil.rmtree(d)


def caso_titulo_del_h1():
    """Bug 1: la etiqueta salia del nombre de archivo y borraba emoji y tildes."""
    d = repo({
        "03-diario/Gorra.md": NODO.format(titulo="La Teoría de la Gorra 🧢",
                                          cuerpo="## Conexiones\n\n- [Sueno](../02-salud/Sueno.md)"),
        "02-salud/Sueno.md": NODO.format(titulo="Arquitectura del Sueño", cuerpo="Contenido."),
    })
    correr(d)
    s = leer(d, "02-salud/Sueno.md")
    revisar("etiqueta: usa el H1 con emoji, no el nombre del archivo",
            "La Teoría de la Gorra 🧢" in s, s[-140:])
    shutil.rmtree(d)


def caso_converge():
    """Bug 2: los backlinks se contaban como salientes y el grafo se hacia bidireccional."""
    d = repo({
        "02-salud/A.md": NODO.format(titulo="A", cuerpo="## Conexiones\n\n- [B](B.md)"),
        "02-salud/B.md": NODO.format(titulo="B", cuerpo="Contenido."),
        "02-salud/C.md": NODO.format(titulo="C", cuerpo="## Conexiones\n\n- [B](B.md)"),
    })
    primera = correr(d)
    segunda = correr(d)
    tercera = correr(d)
    revisar("converge: la segunda pasada no cambia nada",
            primera > 0 and segunda == 0 and tercera == 0,
            f"{primera}/{segunda}/{tercera}")
    a = leer(d, "02-salud/A.md")
    revisar("converge: A no termina referenciado por B (el grafo no se vuelve bidireccional)",
            "## Referenciado por" not in a, a[-100:])
    shutil.rmtree(d)


def caso_mencion_en_prosa():
    """Bug 3: un nodo que MENCIONA '## Referenciado por' quedaba cortado.

    Es el caso que rompio la herramienta con su propia documentacion: el cuerpo
    se cortaba en el primer parrafo y sus enlaces salientes desaparecian del
    grafo sin un solo error.
    """
    cuerpo = ("Este nodo habla de la seccion `## Referenciado por` del schema.\n\n"
              "## Conexiones\n\n- [Destino](Destino.md)")
    d = repo({
        "02-salud/Meta.md": NODO.format(titulo="Meta", cuerpo=cuerpo),
        "02-salud/Destino.md": NODO.format(titulo="Destino", cuerpo="Contenido."),
    })
    correr(d)
    dest = leer(d, "02-salud/Destino.md")
    revisar("mencion en prosa: los enlaces del nodo NO desaparecen",
            "- [Meta](Meta.md)" in dest, dest[-140:])
    meta = leer(d, "02-salud/Meta.md")
    revisar("mencion en prosa: el cuerpo del nodo queda intacto",
            "habla de la seccion" in meta and "## Conexiones" in meta)
    shutil.rmtree(d)


def caso_sufijo_a_mano():
    """Las explicaciones escritas a mano en la seccion no se tiran."""
    b = NODO.format(titulo="B", cuerpo="Contenido.") + \
        "\n## Referenciado por\n\n- [A](A.md): la razon escrita a mano\n"
    d = repo({
        "02-salud/A.md": NODO.format(titulo="A", cuerpo="## Conexiones\n\n- [B](B.md)"),
        "02-salud/B.md": b,
        "02-salud/C.md": NODO.format(titulo="C", cuerpo="## Conexiones\n\n- [B](B.md)"),
    })
    correr(d)
    t = leer(d, "02-salud/B.md")
    revisar("sufijo: se conserva la explicacion escrita a mano",
            ": la razon escrita a mano" in t, t[-160:])
    revisar("sufijo: y ademas entra el backlink nuevo", "- [C](C.md)" in t)
    shutil.rmtree(d)


def caso_enlace_roto():
    d = repo({
        "02-salud/A.md": NODO.format(titulo="A", cuerpo="## Conexiones\n\n- [Fantasma](No%20Existe.md)"),
    })
    rotos, _ = lint.analizar(lint.cargar())
    revisar("enlace roto: se detecta", len(rotos) == 1 and "No%20Existe.md" in rotos[0][2],
            str(rotos))
    shutil.rmtree(d)


def caso_generados_no_ensucian():
    """Los reportes semanales se acumulan; no deben entrar como backlinks."""
    d = repo({
        "03-diario/Semana 2026-W32.md": NODO.format(
            titulo="Semana 2026-W32", cuerpo="## Conexiones\n\n- [B](../02-salud/B.md)"),
        "02-salud/B.md": NODO.format(titulo="B", cuerpo="Contenido."),
    })
    correr(d)
    t = leer(d, "02-salud/B.md")
    revisar("generados: un reporte semanal no aparece como backlink",
            "Semana 2026-W32" not in t, t[-120:])
    shutil.rmtree(d)


def caso_no_toca_conexiones():
    """La garantia central: solo se toca 'Referenciado por'."""
    cuerpo = "## Conexiones\n\n- [B](B.md): motivo importante que no se puede perder"
    d = repo({
        "02-salud/A.md": NODO.format(titulo="A", cuerpo=cuerpo),
        "02-salud/B.md": NODO.format(titulo="B", cuerpo="## Conexiones\n\n- [A](A.md)"),
    })
    correr(d)
    a = leer(d, "02-salud/A.md")
    revisar("seguridad: la seccion Conexiones queda intacta",
            "motivo importante que no se puede perder" in a)
    revisar("seguridad: el frontmatter queda intacto",
            a.startswith("---\ntipo: concepto"))
    shutil.rmtree(d)


def caso_pilar_propio():
    """Los pilares se detectan solos: una carpeta nueva 09-musica cuenta."""
    d = repo({
        "09-musica/A.md": NODO.format(titulo="A", cuerpo="## Conexiones\n\n- [B](../02-salud/B.md)"),
        "02-salud/B.md": NODO.format(titulo="B", cuerpo="Contenido."),
    })
    correr(d)
    t = leer(d, "02-salud/B.md")
    revisar("pilar propio: 09-musica entra al grafo", "- [A](../09-musica/A.md)" in t, t[-120:])
    shutil.rmtree(d)


def main():
    real = lint.REPO
    print("Lint del cerebro (apps/lint/lint.py)\n")
    try:
        for fn in (caso_backlink_basico, caso_titulo_del_h1, caso_converge,
                   caso_mencion_en_prosa, caso_sufijo_a_mano, caso_enlace_roto,
                   caso_generados_no_ensucian, caso_no_toca_conexiones, caso_pilar_propio):
            fn()
    finally:
        lint.REPO = real
    print()
    if FALLOS:
        print(f"{len(FALLOS)} fallas: {', '.join(FALLOS)}")
        sys.exit(1)
    print("todo en orden")


if __name__ == "__main__":
    main()
