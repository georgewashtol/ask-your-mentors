"""Bilingual lexicon (Spanish | English) for the search without AI.

One concept per line: `name: spanish words | english words`. A word of the question that belongs to a concept also
finds the other words of that concept, in both languages: "sell" finds "vender" and "ventas", "cobrar" finds
"price". An underscore joins a phrase (`high_ticket`). Words are written without accents (the search ignores them).

Keep each concept tight: a word that means several things (e.g. "solo") makes the search drift. To add your own
words, add a line or a word to a line; nothing else changes.
"""

CONCEPTS = """
money: dinero plata ingresos ganar ganancias riqueza rico ricos millonario millones facturar facturacion | money income earn earnings wealth rich wealthy millionaire millions cash revenue
price: precio precios cobrar cobro cobras cobrando tarifa tarifas cuesta costo coste honorarios caro barato | price prices pricing charge charging fee fees cost costs rate rates expensive cheap
sell: vender venta ventas vendedor vendiendo cierre | sell selling sale sales seller salesman closing
client: cliente clientes comprador compradores | client clients customer customers buyer buyers
business: negocio negocios empresa empresas emprender emprendedor emprendedores emprendimiento | business businesses company companies startup startups entrepreneur entrepreneurs entrepreneurship
coaching: coaching coach coaches mentoria mentorias asesoria consultoria consultor | coaching coach coaches mentorship mentoring consulting consultant
offer: oferta ofertas producto productos servicio servicios | offer offers product products service services
high_ticket: high_ticket alto_valor premium | high_ticket premium
marketing: marketing publicidad anuncios captacion embudo embudos | marketing advertising ads funnel funnels leads
content: contenido publicar publicacion videos | content posting publish videos
social: redes_sociales instagram tiktok youtube linkedin | social_media instagram tiktok youtube linkedin
audience: audiencia seguidores comunidad | audience followers community
brand: marca marca_personal | brand personal_brand branding
month: mes meses mensual mensuales | month months monthly
year: ano anos anual | year years yearly annual
week: semana semanas semanal | week weeks weekly
day: dia dias diario diaria | day days daily
morning: manana madrugar madrugada despertar levantarse | morning mornings wake early sunrise
night: noche noches | night nights evening
sleep: dormir sueno descanso descansar | sleep sleeping rest
discipline: disciplina disciplinado constancia consistencia | discipline disciplined consistency consistent
habit: habito habitos rutina rutinas costumbre costumbres | habit habits routine routines
motivation: motivacion motivado ganas | motivation motivated drive
procrastination: procrastinar procrastinacion postergar pereza aplazar | procrastination procrastinate lazy laziness
focus: foco enfoque concentracion concentrarse distraccion distracciones | focus concentration attention distraction distractions
productivity: productividad productivo eficiencia | productivity productive efficiency
deep_work: trabajo_profundo | deep_work
fear: miedo miedos temor | fear fears afraid scared
anxiety: ansiedad estres nervios preocupacion | anxiety stress stressed worry anxious
confidence: confianza autoestima inseguridad | confidence self_esteem confident insecurity insecure
failure: fracaso fracasar fallar | failure fail failing failed
mistake: error errores equivocarse | mistake mistakes error errors
success: exito exitoso triunfar | success successful
goal: meta metas objetivo objetivos proposito | goal goals objective objectives purpose
mindset: mentalidad creencias | mindset beliefs belief
happiness: felicidad feliz plenitud | happiness happy fulfillment
gratitude: gratitud agradecer agradecido | gratitude grateful thankful
faith: fe dios oracion orar | faith god prayer pray
family: familia hijos hijo hija padres | family kids children son daughter parents
relationship: pareja relacion relaciones novia novio esposa esposo matrimonio | partner relationship relationships girlfriend boyfriend wife husband marriage
love: amor enamorarse | love
friends: amigos amistad | friends friendship
health: salud saludable | health healthy
exercise: ejercicio entrenar entrenamiento gimnasio correr deporte | exercise training workout gym running sport
nutrition: comida comer alimentacion dieta nutricion | food eat eating diet nutrition
addiction: alcohol drogas vicio vicios adiccion | alcohol drugs vice addiction addicted
phone: celular telefono movil pantalla | phone smartphone screen
email: correo correos email | email emails inbox
meeting: reunion reuniones | meeting meetings
job: trabajo empleo jefe empleado puesto | job jobs work boss employee position
career: carrera profesion profesional | career profession professional
hire: contratar contratacion equipo empleados | hire hiring team employees staff
leadership: liderazgo lider liderar | leadership leader leaders lead
learn: aprender aprendizaje estudiar estudio | learn learning study studying
read: leer lectura libro libros | read reading book books
write: escribir escritura | write writing
skill: habilidad habilidades talento | skill skills talent
communication: comunicacion comunicar | communication communicate
speaking: hablar_en_publico oratoria presentacion | public_speaking speech presentation
negotiation: negociar negociacion | negotiate negotiation negotiating
persuasion: persuasion persuadir influencia convencer | persuasion persuade influence convince
image: imagen vestir ropa estilo apariencia | image dress clothes style appearance
invest: invertir inversion inversiones bolsa acciones | invest investing investment investments stocks
save: ahorrar ahorro ahorros | save saving savings
debt: deuda deudas credito prestamo | debt debts credit loan
scale: escalar crecer crecimiento | scale scaling grow growth
launch: lanzamiento lanzar | launch launching
niche: nicho nichos | niche niches
agency: agencia agencias | agency agencies
ai: ia inteligencia_artificial chatgpt claude | ai artificial_intelligence chatgpt claude
technology: tecnologia | technology tech
decision: decision decisiones decidir | decision decisions decide
ego: ego orgullo | ego pride
compare: comparar compararse compararte comparacion comparaciones envidia | compare comparing comparison envy jealous
loneliness: soledad | loneliness lonely
death: muerte morir | death die dying
energy: energia cansancio cansado agotado agotamiento | energy tired exhausted burnout
emotions: emociones emocion sentimientos | emotions emotion feelings
change: cambio cambiar | change changing
start: empezar comenzar arrancar | start starting begin beginning
quit: renunciar abandonar rendirse rendirme tirar_la_toalla | quit quitting give_up giving_up
patience: paciencia | patience patient
luck: suerte | luck lucky
competition: competencia competir competidores | competition compete competitors
english: ingles | english
remote: remoto | remote
interview: entrevista entrevistas | interview interviews
resume: curriculum hoja_de_vida | resume
salary: salario sueldo | salary wage wages
tax: impuestos impuesto | taxes tax
music: musica cancion canciones | music song songs
advice: consejo consejos | advice tip tips
system: sistema sistemas proceso procesos | system systems process processes
plan: plan planificar planear planificacion | plan planning
schedule: agenda calendario | calendar schedule time_blocking
ambition: ambicion ambicioso | ambition ambitious
greatness: grandeza | greatness
lose: perder perdida pierdo | lose losing lost loss
keep: mantener sostener | keep keeping maintain sustain
build: construir crear | build building create creating
stop: parar detener | stop stopping
improve: mejorar mejora | improve improving improvement
help: ayudar ayuda | help helping
wake: despertar levantarse | wake waking
"""

# Phrases of the question that say WHAT KIND of answer is wanted. Each one adds a concept to the search (if any)
# and rewards the paragraphs whose wording answers that kind of question (a figure, a reason, steps...).
# (name, pattern over the question without accents, concept added or "", pattern that rewards a paragraph)
INTENTS = [
    ("price", r"\b(how much|what price|cuanto (cobr|cuest|val|pid|pon|deber|deb|me cobr)|que precio|a cuanto|pricing|precio|cobrar|charge)",
     "price", r"(\d[\d.,]*\s?(€|\$|euros?|dolares|dollars?|usd|k\b|mil\b))|([€$]\s?\d)|\b(euros|dolares|dollars)\b"),
    ("howto", r"^(how (do|can|should|would|to)|como (hago|hacer|puedo|logro|empiezo|empezar|consigo|se hace|construyo|lo hago|deberia))|\bhow to\b|\bpasos?\b|\bsteps?\b",
     "", r"\b(primero|segundo|tercero|paso|lo que hago|lo que yo hago|lo que hice|first|second|third|step|what i do|what i did|the way i)\b"),
    ("why", r"\b(why|por que)\b", "", r"\b(porque|la razon|el motivo|por eso|because|the reason|that's why|thats why)\b"),
    ("time", r"\b(how long|cuanto tiempo|cuantos (anos|meses|dias)|how many (years|months|days))\b", "",
     r"\b\d+\s?(anos|meses|semanas|dias|years|months|weeks|days|horas|hours)\b"),
    ("advice", r"\b(should i|what should|do you recommend|deberia|que hago|me recomiendas|recomiendas|recomendarias|consejo|advice)\b", "",
     r"\b(te recomiendo|recomiendo|mi consejo|yo haria|lo que haria|tienes que|deberias|hay que|i recommend|my advice|i would|you should|you need to|you have to)\b"),
    ("define", r"^(what is|what's|whats|que es|que significa)\b", "",
     r"\b(es basicamente|significa|se trata de|consiste en|means|is basically|is simply|is about)\b"),
]
