#!/usr/bin/env python3
"""Radar de Empleo (versión libre): busca vacantes remotas en bolsas con API pública
gratuita, aplica las reglas de cada perfil y guarda docs/data/vacantes.json.
También envía un aviso al teléfono con ntfy.

Solo usa la biblioteca estándar de Python: no hay que instalar nada.

Variables de entorno opcionales:
  NTFY_LUZ, NTFY_CRISTIAN   nombre secreto del tema de ntfy de cada perfil
  RADAR_FIXTURES            carpeta con respuestas guardadas (para pruebas sin internet)
  RADAR_SIN_AVISOS=1        no enviar avisos (pruebas)
"""
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(RAIZ, "config", "perfiles.json")
SALIDA = os.path.join(RAIZ, "docs", "data", "vacantes.json")
FIXTURES = os.environ.get("RADAR_FIXTURES")
AHORA = dt.datetime.now(dt.timezone.utc)
UA = "RadarEmpleoLibre/1.0 (busqueda personal de empleo; contacto via GitHub)"
DIAS_HISTORIAL = 21


# ---------------------------------------------------------------- utilidades
def norm(texto):
    """Minúsculas, sin acentos, espacios simples."""
    t = unicodedata.normalize("NFD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.lower()).strip()


def limpiar_html(texto):
    t = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", str(texto or ""), flags=re.I)
    t = re.sub(r"<li[^>]*>", "\n- ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    return t.strip()


def slug(texto):
    return re.sub(r"[^a-z0-9]+", "-", norm(texto)).strip("-")[:80] or "vacante"


def contiene(texto_norm, palabras):
    return [p for p in palabras if norm(p) and norm(p) in texto_norm]


def pedir(url, nombre_fixture=None, json_esperado=True, intentos=2):
    """Descarga una URL (o lee una respuesta guardada si RADAR_FIXTURES está definido)."""
    if FIXTURES:
        ruta = os.path.join(FIXTURES, nombre_fixture or "")
        if not nombre_fixture or not os.path.exists(ruta):
            raise FileNotFoundError("sin fixture " + str(nombre_fixture))
        with open(ruta, encoding="utf-8") as f:
            data = f.read()
        return json.loads(data) if json_esperado else data
    ultimo = None
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, application/rss+xml, */*"})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read().decode("utf-8", "replace")
            return json.loads(data) if json_esperado else data
        except Exception as e:  # noqa: BLE001
            ultimo = e
            time.sleep(3 * (i + 1))
    raise ultimo


def a_fecha(valor):
    """Convierte fechas de distintos formatos a datetime UTC."""
    if valor in (None, ""):
        return None
    try:
        if isinstance(valor, (int, float)) or re.fullmatch(r"\d{9,13}", str(valor)):
            n = float(valor)
            if n > 1e12:
                n /= 1000
            return dt.datetime.fromtimestamp(n, dt.timezone.utc)
        s = str(valor).strip()
        if re.match(r"\d{4}-\d{2}-\d{2}", s):
            s = s.replace("Z", "+00:00")
            d = dt.datetime.fromisoformat(s[:25]) if "T" in s else dt.datetime.fromisoformat(s[:10])
            return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
        d = email.utils.parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- pago
def _a_hora(valor, periodo):
    if valor is None:
        return None
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    periodo = norm(periodo)
    if periodo.startswith("hour") or periodo in ("h", "hr", "hora"):
        return v
    if periodo.startswith("month") or periodo in ("mo", "mes"):
        return v / 173.3
    if periodo.startswith("week"):
        return v / 40
    if periodo.startswith("day"):
        return v / 8
    # anual por defecto; si es un número pequeño probablemente es por hora
    if v < 200:
        return v
    if v < 15000:
        return v / 173.3
    return v / 2080


PAT_PAGO = re.compile(
    r"(?:\$|usd ?|us\$ ?)\s?(\d[\d,]*(?:\.\d+)?)\s?(k)?"
    r"(?:\s?(?:-|to|a)\s?(?:\$|usd ?|us\$ ?)?\s?(\d[\d,]*(?:\.\d+)?)\s?(k)?)?([^\n$]{0,40})")
CONTEXTO_PAGO = re.compile(r"salary|pay|compensation|rate|wage|per hour|hourly|/ ?hr|/ ?hour|a year|per year|annual|per month|monthly|/ ?mo|usd|sueldo|salario|pago")


def _num(s, k):
    n = float(s.replace(",", ""))
    return n * 1000 if k else n


def pago_desde_texto(texto, exigir_contexto=False):
    """Devuelve (min_hora, max_hora) desde un texto como '$15-20/hr', 'USD 45k - 60k a year' o '$2,000/month'."""
    t = str(texto or "").replace("–", "-").replace("—", "-")
    t = norm(t)
    if not t:
        return None, None
    for m in PAT_PAGO.finditer(t):
        antes = t[max(0, m.start() - 60):m.start()]
        cola = m.group(5) or ""
        if exigir_contexto and not CONTEXTO_PAGO.search(antes + " " + m.group(0)):
            continue
        if re.search(r"stipend|bonus|equipment|referral|reimburse", antes[-40:] + cola):
            continue
        nums = [_num(m.group(1), m.group(2))]
        if m.group(3):
            nums.append(_num(m.group(3), m.group(4) or m.group(2)))
        contexto = cola + " " + antes[-25:]
        if re.search(r"/ ?h(ou)?r|per hour|hourly|an hour|/ ?h\b|/hora|por hora", contexto):
            periodo = "hour"
        elif re.search(r"/ ?mo|per month|monthly|a month|/mes|mensual", contexto):
            periodo = "month"
        elif re.search(r"/ ?w(ee)?k|per week|weekly", contexto):
            periodo = "week"
        else:
            periodo = "year"
        horas = [h for h in (_a_hora(n, periodo) for n in nums) if h]
        if horas:
            return round(min(horas), 1), round(max(horas), 1)
    return None, None


# ---------------------------------------------------------------- fuentes
def varias(consultas, json_esperado=True):
    """Pide varias URLs de una misma fuente. Si una falla, sigue con las demás;
    solo marca la fuente con error si fallan todas."""
    ok, ultimo = [], None
    for nombre, url in consultas:
        try:
            ok.append(pedir(url, nombre, json_esperado=json_esperado))
        except FileNotFoundError:
            continue
        except Exception as e:  # noqa: BLE001
            ultimo = e
            print("Consulta con error:", url, e, file=sys.stderr)
    if not ok and ultimo:
        raise ultimo
    return ok


def fuente_remotive():
    """Remotive pide máximo 4 consultas al día y mencionar la fuente. Hacemos 4."""
    vistos = {}
    consultas = (("remotive-cs.json", "https://remotive.com/api/remote-jobs?category=customer-support"),
                 ("remotive-data.json", "https://remotive.com/api/remote-jobs?search=data%20entry"),
                 ("remotive-assistant.json", "https://remotive.com/api/remote-jobs?search=assistant"),
                 ("remotive-processing.json", "https://remotive.com/api/remote-jobs?search=processing"))
    for data in varias(consultas):
        for j in data.get("jobs", []):
            vistos[j.get("id")] = {
                "fuente": "Remotive",
                "url": j.get("url"),
                "puesto": j.get("title"),
                "empresa": j.get("company_name"),
                "ubicacion": j.get("candidate_required_location") or "",
                "pago_texto": j.get("salary") or "",
                "publicada": j.get("publication_date"),
                "tipo": j.get("job_type") or "",
                "categoria": j.get("category") or "",
                "descripcion": j.get("description") or "",
            }
    return list(vistos.values())


def fuente_himalayas(busquedas):
    vistos = {}
    for i, q in enumerate(busquedas):
        params = urllib.parse.urlencode({"q": q, "country": "DO", "sort": "recent"})
        try:
            data = pedir("https://himalayas.app/jobs/api/search?" + params, "himalayas-%d.json" % i)
        except FileNotFoundError:
            continue
        jobs = data.get("jobs") if isinstance(data, dict) else data
        for j in jobs or []:
            url = j.get("applicationLink") or j.get("guid") or j.get("url")
            clave = j.get("guid") or url or (j.get("title"), j.get("companyName"))
            ubic = j.get("locationRestrictions") or []
            if isinstance(ubic, list):
                ubic_txt = ", ".join(str(x.get("name") if isinstance(x, dict) else x) for x in ubic) or "Worldwide"
            else:
                ubic_txt = str(ubic)
            pmin, pmax = j.get("minSalary"), j.get("maxSalary")
            moneda = j.get("currency") or j.get("salaryCurrency") or ""
            periodo = j.get("salaryPeriod") or "annual"
            vistos[clave] = {
                "fuente": "Himalayas",
                "url": url,
                "puesto": j.get("title"),
                "empresa": j.get("companyName") or j.get("company"),
                "ubicacion": ubic_txt,
                "pago_min_hora": _a_hora(pmin, periodo) if norm(moneda) in ("usd", "") else None,
                "pago_max_hora": _a_hora(pmax, periodo) if norm(moneda) in ("usd", "") else None,
                "pago_texto": ("%s %s–%s (%s)" % (moneda, pmin, pmax, periodo)) if (pmin or pmax) else "",
                "publicada": j.get("pubDate"),
                "tipo": j.get("employmentType") or "",
                "categoria": ", ".join(j.get("categories") or []) if isinstance(j.get("categories"), list) else str(j.get("categories") or ""),
                "descripcion": j.get("description") or j.get("excerpt") or "",
            }
        time.sleep(0 if FIXTURES else 2)
    return list(vistos.values())


def fuente_jobicy():
    out = []
    consultas = (("jobicy-supporting.json", "https://jobicy.com/api/v2/remote-jobs?count=100&industry=supporting"),
                 ("jobicy-latam.json", "https://jobicy.com/api/v2/remote-jobs?count=100&geo=latam"),
                 ("jobicy-dataentry.json", "https://jobicy.com/api/v2/remote-jobs?count=100&tag=data%20entry"),
                 ("jobicy-backoffice.json", "https://jobicy.com/api/v2/remote-jobs?count=100&tag=back%20office"))
    for data in varias(consultas):
        for j in data.get("jobs", []):
            moneda = j.get("salaryCurrency") or ""
            periodo = j.get("salaryPeriod") or "annual"
            pmin, pmax = j.get("annualSalaryMin") or j.get("salaryMin"), j.get("annualSalaryMax") or j.get("salaryMax")
            out.append({
                "fuente": "Jobicy",
                "url": j.get("url"),
                "puesto": html.unescape(str(j.get("jobTitle") or "")),
                "empresa": j.get("companyName"),
                "ubicacion": j.get("jobGeo") or "",
                "pago_min_hora": _a_hora(pmin, periodo) if norm(moneda) in ("usd", "") else None,
                "pago_max_hora": _a_hora(pmax, periodo) if norm(moneda) in ("usd", "") else None,
                "pago_texto": ("%s %s–%s (%s)" % (moneda, pmin, pmax, periodo)) if (pmin or pmax) else "",
                "publicada": j.get("pubDate"),
                "tipo": ", ".join(j.get("jobType") or []) if isinstance(j.get("jobType"), list) else str(j.get("jobType") or ""),
                "categoria": ", ".join(j.get("jobIndustry") or []) if isinstance(j.get("jobIndustry"), list) else str(j.get("jobIndustry") or ""),
                "descripcion": j.get("jobDescription") or j.get("jobExcerpt") or "",
            })
    return out


def fuente_remoteok():
    data = pedir("https://remoteok.com/api", "remoteok.json")
    out = []
    for j in data if isinstance(data, list) else []:
        if not isinstance(j, dict) or not j.get("position"):
            continue
        out.append({
            "fuente": "Remote OK",
            "url": j.get("url") or j.get("apply_url"),
            "puesto": j.get("position"),
            "empresa": j.get("company"),
            "ubicacion": j.get("location") or "",
            "pago_min_hora": _a_hora(j.get("salary_min"), "annual"),
            "pago_max_hora": _a_hora(j.get("salary_max"), "annual"),
            "pago_texto": ("USD %s–%s al año" % (j.get("salary_min"), j.get("salary_max"))) if j.get("salary_min") else "",
            "publicada": j.get("date") or j.get("epoch"),
            "tipo": "",
            "categoria": ", ".join(j.get("tags") or []),
            "descripcion": j.get("description") or "",
        })
    return out


def fuente_wwr():
    out = []
    consultas = (("wwr-cs.xml", "https://weworkremotely.com/categories/remote-customer-support-jobs.rss"),
                 ("wwr-otros.xml", "https://weworkremotely.com/categories/all-other-remote-jobs.rss"))
    for xml in varias(consultas, json_esperado=False):
        raiz = ET.fromstring(xml)
        for it in raiz.iter("item"):
            titulo = it.findtext("title") or ""
            empresa, _, puesto = titulo.partition(":")
            if not puesto:
                empresa, puesto = "", titulo
            out.append({
                "fuente": "We Work Remotely",
                "url": it.findtext("link"),
                "puesto": puesto.strip(),
                "empresa": empresa.strip(),
                "ubicacion": it.findtext("region") or it.findtext("country") or "",
                "pago_texto": "",
                "publicada": it.findtext("pubDate"),
                "tipo": it.findtext("type") or "",
                "categoria": it.findtext("category") or "",
                "descripcion": it.findtext("description") or "",
            })
    return out


def fuente_sagan():
    """Sagan Recruitment: agencia que contrata en LATAM y el Caribe para empresas de EE. UU.
    Su web publica un RSS de WordPress con 10 vacantes por página; leemos las 3 más recientes."""
    out = []
    base = "https://saganrecruitment.com/feed/?post_type=job"
    consultas = (("sagan-1.xml", base), ("sagan-2.xml", base + "&paged=2"), ("sagan-3.xml", base + "&paged=3"))
    etiqueta = "{http://purl.org/rss/1.0/modules/content/}encoded"
    for xml in varias(consultas, json_esperado=False):
        raiz = ET.fromstring(xml)
        for it in raiz.iter("item"):
            cuerpo = it.findtext(etiqueta) or it.findtext("description") or ""
            texto = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(cuerpo))).strip()
            corte = r"(?=\s+(?:Compensation|Salary Range|Salary|Work Schedule|Recruiting region|NOTE|Contractor|Full-time|About|Position Overview)\b|$)"
            m = (re.search(r"Recruiting region:\s*(.+?)" + corte, texto)
                 or re.search(r"Location:\s*(.+?)" + corte, texto))
            ubic = m.group(1).strip(" .") if m else ""
            if not ubic or norm(ubic) in ("remote", "remoto"):
                ubic = "LATAM (Sagan)"
            m = re.search(r"(?:Compensation|Salary Range):\s*(.+?)" + corte, texto)
            pago = m.group(1).strip() if m else ""
            hasta = re.match(r"(?i)\s*up to\s+(?:usd|us\$|\$)?\s*([\d,.]+k?)", pago)
            if hasta:
                pago = "USD " + hasta.group(1) + " (up to)"
            elif pago and not re.match(r"(?i)\s*(usd|us\$|\$)", pago):
                pago = "USD " + pago
            if pago and not re.search(r"(?i)hour|hr\b|month|/ ?mo|year|annual|week", pago):
                pago += " per month"  # Sagan publica sueldos mensuales
            out.append({
                "fuente": "Sagan Recruitment",
                "url": it.findtext("link"),
                "puesto": (it.findtext("title") or "").strip(),
                "empresa": "Sagan Recruitment (cliente en EE. UU.)",
                "ubicacion": ubic,
                "pago_texto": pago[:120],
                "publicada": it.findtext("pubDate"),
                "tipo": "contractor",
                "categoria": "",
                "descripcion": cuerpo,
            })
    return out


def fuente_ashby(tablero, nombre, region_por_defecto):
    """Tablero público de Ashby (lo usan varias agencias). Devuelve las vacantes con pago."""
    url = "https://api.ashbyhq.com/posting-api/job-board/%s?includeCompensation=true" % urllib.parse.quote(tablero)
    data = pedir(url, "ashby-%s.json" % slug(tablero))
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        texto = j.get("descriptionPlain") or ""
        m = re.search(r"open to candidates (?:based |located )?in ([^.\n]{3,80})", texto, re.I)
        if m:
            ubic = m.group(1).strip()
        else:
            lugares = [j.get("location") or ""] + [x.get("location") or "" for x in j.get("secondaryLocations") or []]
            ubic = ", ".join(x.strip() for x in lugares if x.strip())
            ubic = (ubic + " — " if ubic else "") + region_por_defecto
        pmin = pmax = None
        comp = j.get("compensation") or {}
        for c in comp.get("summaryComponents") or []:
            if c.get("compensationType") == "Salary" and norm(c.get("currencyCode") or "usd") == "usd":
                periodo = {"1 HOUR": "hour", "1 WEEK": "week", "1 MONTH": "month", "1 YEAR": "year"}.get(c.get("interval") or "", "year")
                pmin, pmax = _a_hora(c.get("minValue"), periodo), _a_hora(c.get("maxValue"), periodo)
                break
        out.append({
            "fuente": nombre,
            "url": j.get("jobUrl") or j.get("applyUrl"),
            "puesto": j.get("title"),
            "empresa": nombre + " (cliente en EE. UU.)",
            "ubicacion": ubic,
            "pago_min_hora": pmin,
            "pago_max_hora": pmax,
            "pago_texto": comp.get("compensationTierSummary") or "",
            "publicada": j.get("publishedAt"),
            "tipo": j.get("employmentType") or "",
            "categoria": j.get("department") or "",
            "descripcion": j.get("descriptionHtml") or texto,
        })
    return out


def fuente_scalearmy():
    """Scale Army Careers: agencia que contrata en LATAM, África y Europa del Este (tablero de Ashby)."""
    return fuente_ashby("Scale Army Careers", "Scale Army", "LATAM, Africa, Eastern Europe (Scale Army)")


def fuente_workingnomads():
    data = pedir("https://www.workingnomads.com/api/exposed_jobs/", "workingnomads.json")
    out = []
    for j in data if isinstance(data, list) else []:
        cat = norm(j.get("category_name"))
        if not any(c in cat for c in ("customer", "support", "administration", "admin", "operations", "data",
                                      "finance", "accounting", "legal", "health", "medical", "commerce",
                                      "translation", "writing", "other")):
            continue
        out.append({
            "fuente": "Working Nomads",
            "url": j.get("url"),
            "puesto": j.get("title"),
            "empresa": j.get("company_name"),
            "ubicacion": j.get("location") or "",
            "pago_texto": "",
            "publicada": j.get("pub_date"),
            "tipo": "",
            "categoria": j.get("category_name") or "",
            "descripcion": j.get("description") or "",
        })
    return out


# ---------------------------------------------------------------- reglas
def regla(nombre, resultado, detalle):
    return {"regla": nombre, "resultado": resultado, "detalle": detalle}


IDIOMA_REQ = r"(fluent|fluency|native|proficien\w*|bilingual)[^.\n]{0,40}\b{l}\b|\b{l}\b[^.\n]{0,25}(required|speaker|speaking|fluency|native|mandatory|is a must)"

# ---------------------------------------------------------------- estudios y licencias
# Títulos profesionales y licencias que ni Luz ni Cristian tienen (médico, enfermería,
# abogado, contador público, doctorado, maestría...). Si el anuncio los pide, se excluye.
CREDENCIAL = re.compile(
    r"\bMD,? (?:or |/ ?)?DO\b|\bM\.D\.|\bMD degree|medical degree|medical school|medical licen[sc]e"
    r"|board[- ]certifi\w*|licensed (?:physician|doctor|nurse|pharmacist|therapist|psychologist|counselor|clinician"
    r"|attorney|lawyer|dentist|veterinarian|social worker|practitioner|radiolog\w*|sonographer|technologist)"
    r"|(?:active|current|valid|unrestricted|state|professional|clinical|nursing|rn|lpn|medical) licen[sc]e\b"
    r"|licen[sc]e to practi[cs]e|registered nurse|bar admission|admitted to (?:the bar|practice)"
    r"|juris doctor|\bJ\.?D\.? degree|\bph\.? ?d\b|doctoral degree|doctorate|master['’]?s (?:degree|in)\b|\bMBA\b"
    r"|medical residency|completed (?:a |your )?residency|certified public accountant"
    r"|\bCPA (?:required|licen[sc]e|certifi\w*|designation)|\b(?:licensed|active|qualified) CPA\b"
    r"|certified (?:professional |medical )?coder|\bCPC (?:certifi\w*|credential|required)|\bRHIT\b|\bRHIA\b",
    re.I)
# Título universitario (licenciatura, bachelor's, associate's...). El bachiller de secundaria no cuenta.
TITULO_UNIV = re.compile(
    r"\bbachelor['’]?s?\b|\b(?:BA/BS|BS/BA|B\.A\.|B\.S\.)|\b(?:undergraduate|university|college|4[- ]year|four[- ]year"
    r"|academic|associate['’]?s|technical|relevant|related) degree\b|\bdegree (?:in|from)\b|\ba degree\b"
    r"|t[ií]tulo universitario|licenciatura|licenciad[oa] en|grado universitario|carrera universitaria|egresad[oa]",
    re.I)
_NEGACION = re.compile(r"\b(?:no|not|without|don['’]?t need|do not need|doesn['’]?t require|does not require|sin)\b[^.\n]{0,25}$", re.I)
_NO_HACE_FALTA = re.compile(r"^[^.\n;]{0,40}\b(?:not required|not necessary|not needed|optional|no es necesari)", re.I)
_ALTERNATIVA_DESPUES = re.compile(r"^[^.\n;]{0,120}\b(?:or|o)\b[^.\n;]{0,40}\b(?:experience|background|track record|knowledge|skills"
                                  r"|expertise|alternative|experiencia)\b"
                                  r"|^[^.\n;]{0,60}\bor (?:an? )?equivalent\b(?! (?:\w+ )?(?:degree|qualification))"
                                  r"|^[^.\n;]{0,120}\b(?:equivalent|comparable|relevant|practical|professional) (?:work |professional |practical )?experience"
                                  r"|^[^.\n;]{0,120}\bin lieu of\b", re.I)
_ALTERNATIVA_ANTES = re.compile(r"(?:\b(?:or|o)|in lieu of)\s+(?:a|an|un|una)?\s*(?:relevant\s+|related\s+)?$", re.I)
_PREFERIDO = re.compile(r"preferred|preferably|a plus|is a plus|strong plus|nice[- ]to[- ]have|bonus|desirable|desired"
                        r"|advantage|ideally|an asset|valued|beneficial|deseable|valorable|preferible", re.I)
_OBLIGATORIO_ANTES = re.compile(r"\b(?:must|required|requires|require|requirements?|mandatory|minimum|essential|need to have"
                                r"|you need|obligatori[oa]|indispensable|requisitos?|requerid[oa])\b", re.I)
_OBLIGATORIO_DESPUES = re.compile(r"^[^.\n;]{0,60}\b(?:required|mandatory|is a must|is essential|obligatori[oa]|indispensable|requerid[oa])\b", re.I)
# encabezados de sección del anuncio
_SEC_PREF = re.compile(r"preferred|nice[- ]to[- ]have|bonus|\bplus\b|desirable|deseable|valorable|optional", re.I)
_SEC_OTRO = re.compile(r"responsibilit|what you(?:'|’)?ll do|what you will do|duties|about (?:the |this )?(?:role|us|company|job|position|team)"
                       r"|benefits|perks|what we offer|compensation|selection process|how to apply|why join|day[- ]to[- ]day"
                       r"|your role|the role|\babout\b(?! you)|who we are|our mission|funciones|responsabilidades|beneficios"
                       r"|ofrecemos|sobre nosotros|la empresa|payment", re.I)
# «licensed therapists», «board-certified physicians», «registered nurses» a menudo describen
# al equipo de la empresa; solo cuentan si se refieren al candidato
_DEL_EQUIPO = re.compile(r"licensed|board|registered nurse", re.I)
_CANDIDATO = re.compile(r"\b(?:you are|you're|are|be|must be|must hold|must have|hold|holds|have|has|having|possess\w*"
                        r"|as an?|is|being|currently)\s+(?:an?\s+|currently\s+|also\s+)?$", re.I)
_SEC_REQ = re.compile(r"requirement|qualification|what you(?:'|’)?ll bring|what you bring|must[- ]haves?|you have|who you are"
                      r"|looking for|ideal candidate|about you|skills|education|requisitos|perfil|competencias", re.I)


def _seccion(texto, pos):
    """Mira el encabezado más cercano antes de pos: 'requisito', 'preferido', 'otro' o 'desconocido'."""
    lineas = texto[:pos].split("\n")[:-1]
    for linea in reversed(lineas[-60:]):
        t = linea.strip()
        if len(t) > 70:
            if not t.endswith(":"):
                continue
            t = t[-45:]  # p. ej. «...9. Ad hoc tasks Qualifications:»
        t = t.strip("#*•:").strip()
        if not t or t.startswith("-"):
            continue
        if _SEC_PREF.search(t):
            return "preferido"
        if _SEC_OTRO.search(t):
            return "otro"
        if _SEC_REQ.search(t):
            return "requisito"
    return "desconocido"


def _requisitos(texto, patron):
    """Busca el patrón en el anuncio y decide si se lo piden al candidato.
    Devuelve (obligatorios, dudosos), cada uno con fragmentos del anuncio.
    No cuenta lo preferido, lo opcional, lo reemplazable por experiencia ni lo que
    aparece fuera de los requisitos (p. ej. «apoyarás a médicos certificados»)."""
    obligatorios, dudosos = [], []
    for m in patron.finditer(texto):
        if _DEL_EQUIPO.match(m.group(0)):
            ini_l = max(texto.rfind("\n", 0, m.start()), texto.rfind(". ", 0, m.start()))
            previo = re.sub(r"^[\s\-•*\d.)]*(?:[A-Za-z /&]{1,25}:)?\s*", "", texto[ini_l + 1:m.start()])
            if previo.strip() and not _CANDIDATO.search(previo):
                continue
        ini = max(texto.rfind("\n", 0, m.start()), texto.rfind(". ", 0, m.start()), texto.rfind(";", 0, m.start()))
        antes = texto[ini + 1:m.start()][-120:]
        despues = texto[m.end():m.end() + 200]
        corte = re.search(r"\n|\.\s|;", despues)
        despues_corto = despues[:corte.start()] if corte else despues
        if _NEGACION.search(antes) or _NO_HACE_FALTA.search(despues):
            continue
        if _ALTERNATIVA_DESPUES.search(despues_corto) or _ALTERNATIVA_ANTES.search(antes):
            continue
        if re.search(r"\b(?:or|o)\s*$", despues_corto) and corte and despues[corte.start()] == "\n":
            continue  # «...degree or» y la siguiente viñeta da otra opción (p. ej. años de experiencia)
        frag = re.sub(r"\s+", " ", antes[-50:] + m.group(0) + despues_corto[:80]).strip(" -•:")
        if _OBLIGATORIO_DESPUES.search(despues_corto) or _OBLIGATORIO_ANTES.search(antes):
            obligatorios.append(frag)
            continue
        if _PREFERIDO.search(despues_corto) or _PREFERIDO.search(antes):
            continue
        sec = _seccion(texto, m.start())
        if sec == "requisito":
            obligatorios.append(frag)
        elif sec == "desconocido":
            dudosos.append(frag)
    return obligatorios, dudosos


def evaluar(v, perfil, comunes):
    titulo = " " + norm(v["puesto"]) + " "
    texto = norm(" ".join([v["puesto"], v.get("categoria", ""), v.get("tipo", ""), v["descripcion_txt"]]))
    ubic = norm(v.get("ubicacion"))
    filtro, duras, dudas = [], [], []

    # tipo de puesto
    no_t = contiene(titulo, perfil["titulo_no"])
    si_t = contiene(titulo, perfil["titulo_si"])
    if no_t:
        filtro.append(regla("Tipo de puesto", "no cumple", "El título dice: " + ", ".join(no_t[:3])))
        duras.append("tipo de puesto (" + no_t[0].strip() + ")")
    elif si_t:
        filtro.append(regla("Tipo de puesto", "cumple", "El título coincide con: " + ", ".join(si_t[:3])))
    else:
        filtro.append(regla("Tipo de puesto", "no cumple", "El título no parece de los puestos que buscas"))
        duras.append("tipo de puesto")

    # voz
    voz = contiene(texto, perfil["voz_no"])
    if voz and contiene(texto, comunes.get("sin_voz_marcas", [])):
        # el anuncio aclara que no hay llamadas: solo cuentan las señales fuertes
        voz = [x for x in voz if x in comunes.get("voz_fuerte", [])]
    if voz:
        filtro.append(regla("Sin llamadas", "no cumple", "Menciona: " + ", ".join(voz[:3])))
        duras.append("incluye llamadas")
    else:
        canales = contiene(texto, perfil.get("canales_si", []))
        if canales:
            filtro.append(regla("Sin llamadas", "cumple", "Canales escritos: " + ", ".join(canales[:3]) + "; no menciona teléfono"))
        elif perfil.get("canales_obligatorios"):
            filtro.append(regla("Sin llamadas", "no cumple", "No dice si es por chat, email o tickets"))
            duras.append("no nombra los canales")
        else:
            filtro.append(regla("Sin llamadas", "no se sabe", "No menciona teléfono ni canales"))
            dudas.append("canal no indicado")

    # país
    pais_no = contiene(" " + ubic + " " + texto + " ", comunes["pais_no"])
    # frases como "US-based" solo cuentan en la ubicación: en la descripción suelen
    # referirse a los clientes ("supporting US-based clients"), no al candidato
    pais_no += contiene(" " + ubic + " ", comunes.get("pais_no_ubicacion", []))
    pais_si = contiene(ubic, comunes["pais_si"]) or (["worldwide"] if not ubic else [])
    if pais_no:
        filtro.append(regla("Acepta RD", "no cumple", "Dice: " + pais_no[0]))
        duras.append("país (" + pais_no[0] + ")")
    elif "dominican" in ubic or "caribbean" in ubic:
        filtro.append(regla("Acepta RD", "cumple", "Ubicación: " + v.get("ubicacion", "")))
    elif pais_si:
        if contiene(ubic, comunes["pais_dudoso"]):
            filtro.append(regla("Acepta RD", "no se sabe", "Dice " + v.get("ubicacion", "") + "; confirma que incluya a RD"))
            dudas.append("confirmar que acepten RD")
        else:
            filtro.append(regla("Acepta RD", "cumple", "Ubicación: " + (v.get("ubicacion") or "sin restricción")))
    else:
        filtro.append(regla("Acepta RD", "no cumple", "Limitada a: " + v.get("ubicacion", "")))
        duras.append("país (" + v.get("ubicacion", "") + ")")

    # pago
    pmin, pmax = v.get("pago_min_hora"), v.get("pago_max_hora")
    minimo = perfil.get("pago_min_hora") or 0
    if pmax:
        if minimo and pmax < minimo and v.get("pago_origen") == "descripcion":
            filtro.append(regla("Pago", "no se sabe", "El texto parece decir unos US$%.1f/h; confírmalo" % pmax))
            dudas.append("pago posiblemente bajo")
        elif minimo and pmax < minimo:
            filtro.append(regla("Pago", "no cumple", "Hasta US$%.1f/h; tu mínimo es US$%s/h" % (pmax, minimo)))
            duras.append("pago bajo")
        else:
            filtro.append(regla("Pago", "cumple", "Unos US$%.1f–%.1f/h" % (pmin or pmax, pmax)))
    else:
        filtro.append(regla("Pago", "no se sabe", "Pago no publicado"))
        if minimo:
            dudas.append("pago no indicado")
    tope = comunes.get("pago_experto_hora")
    if tope and (pmin or pmax or 0) >= tope:
        # un puesto de back office o soporte no paga eso: suele ser para médicos,
        # abogados o expertos con título que entrenan IA
        filtro.append(regla("Pago de experto", "no se sabe",
                            "Desde US$%.0f/h: ese pago suele ser para profesionales con título; revisa los requisitos" % (pmin or pmax)))
        dudas.append("pago de nivel experto (revisa si pide título)")

    # estudios y licencias
    texto_orig = v["descripcion_txt"]
    cred_ob, cred_duda = _requisitos(texto_orig, CREDENCIAL)
    if perfil.get("sin_titulo_universitario"):
        univ_ob, univ_duda = _requisitos(texto_orig, TITULO_UNIV)
    else:
        univ_ob, univ_duda = [], []
    if cred_ob:
        filtro.append(regla("Estudios", "no cumple", "Pide título profesional o licencia: «%s»" % cred_ob[0][:140]))
        duras.append("pide título profesional o licencia")
    elif cred_duda:
        filtro.append(regla("Estudios", "no se sabe", "Menciona un título profesional o licencia: «%s»" % cred_duda[0][:140]))
        dudas.append("confirmar si pide título profesional o licencia")
    elif univ_ob:
        filtro.append(regla("Estudios", "no cumple", "Pide título universitario: «%s»" % univ_ob[0][:140]))
        duras.append("pide título universitario")
    elif univ_duda:
        filtro.append(regla("Estudios", "no se sabe", "Menciona título universitario sin decir si es obligatorio: «%s»" % univ_duda[0][:140]))
        dudas.append("confirmar si el título universitario es obligatorio")
    elif perfil.get("sin_titulo_universitario"):
        filtro.append(regla("Estudios", "cumple", "No pide título universitario ni licencias"))

    # idiomas
    malos = [l for l in perfil.get("idiomas_no", []) if re.search(IDIOMA_REQ.replace("{l}", re.escape(l)), texto)]
    # «Kinyarwanda Language Specialist», «Tamil Linguist»: el idioma en el título ya basta
    malos += [l for l in perfil.get("idiomas_no", []) + comunes.get("idiomas_no_titulo", [])
              if l not in malos and re.search(r"\b" + re.escape(norm(l)) + r"\b", titulo)]
    if malos:
        filtro.append(regla("Idiomas", "no cumple", "Pide " + ", ".join(malos[:2])))
        duras.append("pide " + malos[0])

    # señales de estafa y empresas excluidas
    estafa = contiene(texto, comunes["pago_ilegal"])
    if estafa:
        filtro.append(regla("Sin pagos ni estafas", "no cumple", "Menciona: " + estafa[0]))
        duras.append("posible estafa")
    emp = contiene(norm(v.get("empresa")), perfil.get("excluir_empresas", []))
    if emp:
        duras.append("empresa excluida")
        filtro.append(regla("Empresa", "no cumple", "Empresa excluida en tus reglas"))

    if duras:
        estado, motivo = "excluida", "No cumple: " + "; ".join(duras[:3])
    elif dudas:
        estado, motivo = "revisar", "Cumple lo que se puede ver; falta: " + "; ".join(dudas[:3])
    else:
        estado, motivo = "cumple", "Cumple tus filtros; falta abrir el anuncio original y verificar"
    prioridad = 1 if estado == "cumple" and pmax and pmax >= 15 else 2 if estado == "cumple" else 3 if estado == "revisar" else 4
    return {"estado": estado, "motivo": motivo, "filtro": filtro, "prioridad": prioridad}


# ---------------------------------------------------------------- avisos
def avisar(tema, titulo, mensaje, clic):
    if not tema or os.environ.get("RADAR_SIN_AVISOS") or FIXTURES:
        return False
    cuerpo = json.dumps({"topic": tema, "title": titulo, "message": mensaje, "click": clic, "tags": ["briefcase"]}).encode("utf-8")
    req = urllib.request.Request("https://ntfy.sh/", data=cuerpo, headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        return True
    except Exception as e:  # noqa: BLE001
        print("No se pudo enviar el aviso:", e, file=sys.stderr)
        return False


def url_pages():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        dueno, nombre = repo.split("/", 1)
        return "https://%s.github.io/%s/" % (dueno.lower(), nombre)
    return ""


# ---------------------------------------------------------------- principal
def main():
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    comunes, perfiles = cfg["comunes"], cfg["perfiles"]
    # intercala las búsquedas de cada perfil para que todos tengan turno
    busquedas = []
    listas = [p.get("busquedas", []) for p in perfiles.values()]
    for i in range(max([len(x) for x in listas] + [0])):
        for lista_p in listas:
            if i < len(lista_p) and lista_p[i] not in busquedas:
                busquedas.append(lista_p[i])
    busquedas = busquedas[:comunes.get("max_busquedas", 26)]

    fuentes = {
        "Remotive": fuente_remotive,
        "Himalayas": lambda: fuente_himalayas(busquedas),
        "Jobicy": fuente_jobicy,
        "Remote OK": fuente_remoteok,
        "We Work Remotely": fuente_wwr,
        "Working Nomads": fuente_workingnomads,
        "Sagan Recruitment": fuente_sagan,
        "Scale Army": fuente_scalearmy,
    }
    crudas, informe = [], {}
    for nombre, fn in fuentes.items():
        try:
            lista = fn()
            informe[nombre] = {"ok": True, "vacantes": len(lista)}
            crudas.extend(lista)
        except Exception as e:  # noqa: BLE001
            informe[nombre] = {"ok": False, "error": str(e)[:200]}
            print("Fuente con error:", nombre, e, file=sys.stderr)

    anterior = {}
    if os.path.exists(SALIDA):
        try:
            with open(SALIDA, encoding="utf-8") as f:
                for v in json.load(f).get("vacantes", []):
                    anterior[v["id"]] = v
        except Exception:  # noqa: BLE001
            anterior = {}

    dias_max = max([comunes.get("dias_maximos", 10)] + [p.get("dias_maximos", 10) for p in perfiles.values()])
    nuevas = {pid: [] for pid in perfiles}
    resultado = {}
    for v in crudas:
        if not v.get("puesto") or not v.get("url"):
            continue
        fecha = a_fecha(v.get("publicada"))
        if fecha and (AHORA - fecha).days > dias_max:
            continue
        v["descripcion_txt"] = limpiar_html(v.get("descripcion"))
        v["pago_origen"] = "estructurado" if (v.get("pago_min_hora") or v.get("pago_max_hora")) else None
        if not v["pago_origen"]:
            v["pago_min_hora"], v["pago_max_hora"] = pago_desde_texto(v.get("pago_texto") or "")
            v["pago_origen"] = "texto" if v["pago_max_hora"] else None
            if v["pago_max_hora"] is None:
                v["pago_min_hora"], v["pago_max_hora"] = pago_desde_texto(v["descripcion_txt"][:4000], exigir_contexto=True)
                v["pago_origen"] = "descripcion" if v["pago_max_hora"] else None
        if (v.get("pago_max_hora") or 0) > 300:  # dato de pago imposible (error de la bolsa)
            v["pago_min_hora"], v["pago_max_hora"], v["pago_origen"] = None, None, None
        vid = slug((v.get("empresa") or "") + " " + v["puesto"])
        if vid in resultado:  # misma vacante en dos bolsas
            continue
        evals = {}
        for pid, p in perfiles.items():
            dias_p = p.get("dias_maximos", dias_max)
            if fecha and (AHORA - fecha).days > dias_p:
                continue
            evals[pid] = evaluar(v, p, comunes)
        if not evals:
            continue
        previo = anterior.get(vid, {})
        primera = previo.get("vista_primera_vez") or AHORA.isoformat()
        registro = {
            "id": vid,
            "fuente": v["fuente"],
            "url": v["url"],
            "puesto": v["puesto"].strip(),
            "empresa": (v.get("empresa") or "").strip(),
            "ubicacion": v.get("ubicacion") or "",
            "pago_texto": v.get("pago_texto") or "",
            "pago_min_hora": round(v["pago_min_hora"], 1) if v.get("pago_min_hora") else None,
            "pago_max_hora": round(v["pago_max_hora"], 1) if v.get("pago_max_hora") else None,
            "pago_origen": v.get("pago_origen"),
            "tipo": v.get("tipo") or "",
            "publicada": fecha.isoformat() if fecha else None,
            "vista_primera_vez": primera,
            "vista_ultima_vez": AHORA.isoformat(),
            "descripcion": v["descripcion_txt"][:5000],
            "perfiles": evals,
        }
        resultado[vid] = registro
        for pid, e in evals.items():
            if e["estado"] == "cumple" and vid not in anterior:
                nuevas[pid].append(registro)

    # conservar las vistas en los últimos días aunque ya no salgan hoy
    for vid, v in anterior.items():
        if vid in resultado:
            continue
        ultima = a_fecha(v.get("vista_ultima_vez"))
        if ultima and (AHORA - ultima).days <= DIAS_HISTORIAL:
            v["ya_no_aparece"] = True
            # se vuelven a evaluar con las reglas de hoy, por si cambiaron
            # (solo para hacerlas más estrictas: el texto guardado está recortado y
            # podría haber perdido lo que la excluyó)
            base = dict(v, categoria="", descripcion_txt=v.get("descripcion") or "")
            orden = {"cumple": 0, "revisar": 1, "excluida": 2}
            for pid, viejo in list((v.get("perfiles") or {}).items()):
                if pid in perfiles:
                    try:
                        nuevo = evaluar(base, perfiles[pid], comunes)
                        if orden.get(nuevo["estado"], 0) > orden.get(viejo.get("estado"), 0):
                            v["perfiles"][pid] = nuevo
                    except Exception as e:  # noqa: BLE001
                        print("No se pudo reevaluar", vid, e, file=sys.stderr)
            resultado[vid] = v

    lista = sorted(resultado.values(), key=lambda x: (min((e["prioridad"] for e in x["perfiles"].values()), default=9), -(x.get("pago_max_hora") or 0), x.get("publicada") or ""), reverse=False)
    salida = {
        "actualizado": AHORA.isoformat(),
        "fuentes": informe,
        "aviso": "Datos de Remotive, Himalayas, Jobicy, Remote OK, We Work Remotely y Working Nomads. Cada vacante enlaza a su fuente.",
        "vacantes": lista,
    }
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)

    pagina = url_pages()
    for pid, p in perfiles.items():
        conteo = {"cumple": 0, "revisar": 0}
        for v in lista:
            e = v["perfiles"].get(pid)
            if e and e["estado"] in conteo and not v.get("ya_no_aparece"):
                conteo[e["estado"]] += 1
        nuevas_p = sorted(nuevas[pid], key=lambda x: -(x.get("pago_max_hora") or 0))
        print("%s: %d nuevas que cumplen; %d cumplen en total; %d por revisar" % (p["nombre"], len(nuevas_p), conteo["cumple"], conteo["revisar"]))
        tema = os.environ.get("NTFY_" + pid.upper())
        if nuevas_p:
            lineas = ["• %s — %s%s" % (v["puesto"], v["empresa"] or v["fuente"], (" · US$%s/h" % v["pago_max_hora"]) if v.get("pago_max_hora") else "") for v in nuevas_p[:6]]
            msg = "\n".join(lineas) + ("\n…y %d más" % (len(nuevas_p) - 6) if len(nuevas_p) > 6 else "") + "\nRecuerda verificar cada una en el sitio original."
            avisar(tema, "Radar: %d vacante%s nueva%s para %s" % (len(nuevas_p), "s" if len(nuevas_p) != 1 else "", "s" if len(nuevas_p) != 1 else "", p["nombre"]), msg, pagina)
        else:
            avisar(tema, "Radar: sin vacantes nuevas para %s" % p["nombre"], "Hoy no apareció nada nuevo que cumpla tus filtros. Por revisar: %d." % conteo["revisar"], pagina)
    fallas = [n for n, i in informe.items() if not i["ok"]]
    if fallas:
        print("Fuentes con error:", ", ".join(fallas), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
