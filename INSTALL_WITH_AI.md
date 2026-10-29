# Install with your AI / Instálala con tu IA

Step by step to install Ask Your Mentors without programming. Open **Claude Code** (or another coding AI) in the folder where you keep your projects and paste the prompt in your language. The AI explains each step and asks before installing anything.

El paso a paso para instalar Ask Your Mentors sin saber programar. Abre **Claude Code** (u otra IA de programación) en la carpeta donde guardas tus proyectos y pega el prompt en tu idioma. La IA explica cada paso y pregunta antes de instalar cualquier cosa.

## English

```text
I don't know how to program, so explain each step in simple words and ask me before installing anything or before any command that needs my password.

1. Clone https://github.com/georgewashtol/ask-your-mentors into this folder. If git is missing, install it or download the ZIP from GitHub.
2. Read its AGENTS.md: it is the manual for you.
3. Run "python3 app.py --check" ("python app.py --check" on Windows). Install everything it marks as MISSING with the exact command it shows for my system, and offer me the optional ones (podcast transcription) telling me how much space they take.
4. Run the check again until nothing says MISSING. If I chose Claude Code and it is not logged in, tell me to run "claude auth login" and wait for me.
5. Start the app with "python3 app.py", give me the link (http://localhost:7720) and tell me my first step: typing the name of someone I learn from.

If something fails, read the error, fix it and tell me in one sentence what happened.
```

## Español

```text
No sé programar, así que explícame cada paso con palabras simples y pregúntame antes de instalar cualquier cosa o de correr un comando que pida mi contraseña.

1. Clona https://github.com/georgewashtol/ask-your-mentors en esta carpeta. Si no tengo git, instálalo o descarga el ZIP desde GitHub.
2. Lee su AGENTS.md: es el manual para ti.
3. Corre "python3 app.py --check" ("python app.py --check" en Windows). Instala todo lo que marque FALTA con el comando exacto que muestra para mi sistema, y ofréceme los opcionales (transcribir podcasts) diciéndome cuánto espacio ocupan.
4. Vuelve a correr la revisión hasta que nada diga FALTA. Si elegí Claude Code y no tiene sesión, dime que corra "claude auth login" y espérame.
5. Arranca la app con "python3 app.py", ponla en español (selector EN | ES abajo a la izquierda), dame el enlace (http://localhost:7720) y dime mi primer paso: escribir el nombre de alguien de quien aprendo.

Si algo falla, lee el error, arréglalo y cuéntame en una frase qué pasó.
```

## What happens / Qué pasa

1. The AI clones the repo and reads `AGENTS.md` (its manual). / La IA clona el repo y lee `AGENTS.md` (su manual).
2. `python3 app.py --check` lists what your computer has and what is missing, with the exact install command for your system. / `python3 app.py --check` muestra qué tiene tu computador y qué falta, con el comando exacto para tu sistema.
3. It installs what says MISSING / FALTA (asking first) and offers the optional pieces. / Instala lo que dice MISSING / FALTA (preguntando antes) y ofrece lo opcional.
4. It starts the app and gives you the link: http://localhost:7720. / Arranca la app y te da el enlace: http://localhost:7720.

Requirements, hardware and privacy: see the [README](README.md). / Requisitos, hardware y privacidad: mira el [README](README.md).
