# Radar de Empleo (versión gratis)

Busca vacantes remotas todos los días, las filtra con las reglas de Luz y de Cristian, avisa al teléfono y ayuda a preparar el CV, la carta y las respuestas de cada postulación. No necesita ninguna membresía de IA ni que la PC esté encendida.

| Parte | Dónde funciona | Costo |
|---|---|---|
| Buscador diario (7:17 a. m. hora RD) | GitHub Actions, en la nube | Gratis |
| App web (teléfono y PC) | GitHub Pages | Gratis |
| Avisos al teléfono | App ntfy | Gratis |
| IA para CVs, cartas y evaluaciones | Copiar y pegar en ChatGPT, Gemini o Claude gratis · IA local con Ollama en la PC · Gemini con clave gratis (opcional) | Gratis |

> **Privacidad:** este repositorio es público (GitHub Pages gratis lo exige). Aquí **no** van CVs ni datos personales: se guardan solo en el navegador de cada dispositivo. Los nombres de los temas de avisos van en *Secrets*, que nadie más ve.

---

## 1. Crear la cuenta y el repositorio

1. Crea una cuenta gratis en <https://github.com/signup>.
2. Arriba a la derecha pulsa **+ → New repository**.
3. Nombre: `radar-empleo`. Marca **Public**. Pulsa **Create repository**.

## 2. Subir los archivos

1. En el repositorio nuevo pulsa **uploading an existing file** (o **Add file → Upload files**).
2. Abre la carpeta `radar-empleo` del zip y arrastra **todo su contenido** (las carpetas `.github`, `buscador`, `config`, `docs` y este `README.md`).
3. Pulsa **Commit changes**.
4. Revisa que exista el archivo `.github/workflows/buscar.yml`. Si no se subió (a veces el navegador ignora las carpetas que empiezan con punto):
   **Add file → Create new file**, escribe como nombre `.github/workflows/buscar.yml`, pega el contenido de ese archivo del zip y pulsa **Commit changes**.

## 3. Guardar los temas de avisos (Secrets)

1. En el repositorio: **Settings → Secrets and variables → Actions → New repository secret**.
2. Crea dos secretos con los nombres de tema que te dio Claude en el chat (no los publiques en ningún otro sitio: quien sepa el nombre puede leer los avisos):
   - Nombre `NTFY_LUZ` → valor: el tema de Luz.
   - Nombre `NTFY_CRISTIAN` → valor: el tema de Cristian.

## 4. Activar la página

1. **Settings → Pages**.
2. En *Build and deployment*: Source **Deploy from a branch**, Branch **main**, carpeta **/docs**. Pulsa **Save**.
3. En 1 o 2 minutos la app queda en `https://TU-USUARIO.github.io/radar-empleo/`.

## 5. Primera búsqueda

1. Pestaña **Actions**. Si GitHub pregunta, pulsa **I understand my workflows, go ahead and enable them**.
2. A la izquierda elige **Buscar vacantes → Run workflow → Run workflow**.
3. Espera 2 o 3 minutos hasta que salga el círculo verde. Abre la app: ya verás vacantes.

Desde ese momento corre solo todos los días a las 7:17 a. m. (GitHub a veces lo atrasa unos minutos).

## 6. Avisos en el teléfono (ntfy)

1. Instala **ntfy** desde Play Store (Android) o App Store (iPhone).
2. Pulsa **+**, escribe el tema (el mismo del secreto: Luz el suyo, Cristian el suyo) y deja el servidor `ntfy.sh`. Pulsa **Subscribe**.
3. Cada mañana con vacantes nuevas que cumplan tus filtros llega un aviso. Al tocarlo se abre la app.

## 7. Usar la app en el teléfono

1. Abre `https://TU-USUARIO.github.io/radar-empleo/` en Chrome.
2. Menú **⋮ → Agregar a la pantalla principal**. Queda como una app más.
3. **Ajustes → Importar respaldo** y elige el archivo `respaldo-radar-….json` que te dio Claude (mándatelo por WhatsApp o correo). Así quedan tus CVs, reglas y seguimiento.
4. Haz lo mismo en cada dispositivo. Los datos no se sincronizan solos: cuando cambies algo importante, **Exportar respaldo** e impórtalo en el otro dispositivo.

## 8. La IA

En **Ajustes → Inteligencia artificial** eliges cómo trabaja:

- **Copiar y pegar** (por defecto, sirve en el teléfono): la app prepara las instrucciones, tú las pegas en ChatGPT, Gemini o Claude gratis y pegas la respuesta de vuelta. Para evaluaciones con capturas, adjunta la captura directamente en esa IA.
- **IA local con Ollama** (solo en la PC de Cristian, sin internet ni límites):
  1. Descarga e instala Ollama desde <https://ollama.com/download/windows>.
  2. Abre **PowerShell** y escribe:
     ```
     ollama pull qwen3.5
     setx OLLAMA_ORIGINS "https://TU-USUARIO.github.io"
     ```
  3. Cierra Ollama (icono junto al reloj → **Quit**) y ábrelo de nuevo.
  4. En la app: **Ajustes → IA local con Ollama → Probar conexión**. Si Chrome pregunta si permites acceso a la red local, acepta.
  5. Con la RTX 4060 de 8 GB el modelo `qwen3.5` responde en segundos y también lee capturas de pantalla.
- **Gemini con clave gratis** (opcional): crea la clave en <https://aistudio.google.com/apikey> y pégala en Ajustes. La cuota gratis es pequeña y Google puede usar lo que envías para mejorar sus productos.

## 9. Cambiar las reglas del buscador

Edita `config/perfiles.json` en GitHub (botón del lápiz) o desde **Ajustes → Editar reglas del buscador**:

- `pago_min_hora`: pago mínimo en US$ por hora (Luz: 8; Cristian: 0 = sin mínimo).
- `busquedas`: palabras que se buscan en las bolsas de empleo.
- `titulo_si` / `titulo_no`: palabras que el título debe tener o no tener.
- `excluir_empresas`, `idiomas_no`, `dias`: empresas descartadas, idiomas que no se aceptan y antigüedad máxima.
- `sin_titulo_universitario`: con `true`, se excluyen las vacantes que piden título universitario obligatorio (si es "preferido" o acepta experiencia equivalente, no se excluye; si no queda claro, va a revisar). Las que piden título profesional o licencia (médico, enfermería, abogado, CPA, doctorado, maestría) se excluyen siempre.
- `idiomas_no_titulo` (en `comunes`): idiomas que, si aparecen en el título (p. ej. "Kinyarwanda Language Specialist"), excluyen la vacante para los dos perfiles.
- `pago_experto_hora` (en `comunes`): desde ese pago por hora la vacante va a revisar, porque suele ser para profesionales con título.

Las reglas de la IA (para analizar vacantes y escribir) están en la app, en **Ajustes → Perfil y reglas**.

## Qué hace y qué no hace

- Revisa 7 fuentes públicas y gratis: Remotive, Himalayas, Jobicy, Remote OK, We Work Remotely, Working Nomads y el RSS de la agencia Sagan Recruitment (LATAM y el Caribe). Las vacantes de la agencia InsideOutVAS llegan por Himalayas. **No** revisa LinkedIn ni Indeed (no tienen API gratis). Esas se agregan a mano con **Agregar vacante**.
- "Cumple tus filtros" significa que el texto del anuncio pasó las reglas, **no** que esté verificada. Antes de postular, abre el anuncio original y el formulario.
- Nunca postula por ti ni paga nada. Tú decides y envías cada postulación.
- Si el repositorio pasa 60 días sin cambios, GitHub pausa la búsqueda diaria. Como cada búsqueda guarda resultados, eso no debería pasar; si pasa, entra a **Actions** y pulsa **Enable workflow**.

## Problemas comunes

| Problema | Solución |
|---|---|
| La búsqueda falla con "Permission denied" al guardar | **Settings → Actions → General → Workflow permissions → Read and write permissions → Save** y vuelve a correrla. |
| No llegan avisos | Revisa que el secreto y el tema en la app ntfy sean exactamente iguales. Solo avisa cuando hay vacantes **nuevas** que cumplen. |
| "No se pudo conectar con Ollama" | Ollama debe estar abierto en esa PC, `OLLAMA_ORIGINS` debe tener tu dirección exacta de GitHub Pages y hay que reiniciar Ollama después de `setx`. |
| Perdí mis datos del teléfono | Importa tu último respaldo. Borrar los datos del navegador borra los de la app. |

Vacantes cortesía de [Remotive](https://remotive.com), [Himalayas](https://himalayas.app), [Jobicy](https://jobicy.com), [Remote OK](https://remoteok.com), [We Work Remotely](https://weworkremotely.com), [Working Nomads](https://www.workingnomads.com) y [Sagan Recruitment](https://saganrecruitment.com). Cada vacante enlaza a su anuncio original.
