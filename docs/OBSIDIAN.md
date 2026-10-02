# Enlaces Obsidian en Telegram

La integración reside en el gateway de este proyecto. No se modificó Hermes Desktop, su renderer, ni MCP.

`app/obsidian.py` expone `extract_obsidian_telegram_actions(text)` sin llamadas de red. Devuelve texto y botones con etiqueta fija **Abrir en Obsidian** y destino idéntico al URI validado. `Gateway.deliver` en `app/bot.py` conecta esta salida con el envío y la edición existentes, incluidos mensajes largos y respuestas con archivos.

Política cerrada: esquema literal `obsidian`, autoridad `open`, sin path, fragmento, usuario ni puerto; exactamente `vault` y `file`, no repetidos y no vacíos. Se rechazan valores con espacios sin codificar, Unicode sin codificar, percent-encoding mal formado, controles, HTML y abreviaciones con `...` o `…`. El validador RFC 3986 rechaza `+` literal. En la extracción Telegram hay una capa explícita de compatibilidad para productores de query tipo formulario: convierte exclusivamente `+` a `%20`, revalida todo el URI y registra `form_encoded_spaces` sin contenido privado. Un signo más real debe ser `%2B` y se conserva. `%20`, barras, Unicode codificado y caracteres reservados permanecen exactamente como llegaron. La decodificación sólo valida y nunca reconstruye el destino.

Se detectan enlaces Markdown y URIs planos. No se convierten bloques cercados de código (backticks o tildes, incluidos bloques sin cerrar), código inline ni etiquetas de enlaces Markdown. Los destinos únicos generan un solo botón. El título del modelo no controla ni la etiqueta fija ni el destino. El texto restante sigue por el escape HTML habitual.

Cuando se acepta el botón, se retiran las ocurrencias convertidas de la respuesta. Cuando Telegram lo rechaza, se restaura la respuesta original usando el envío HTML/texto habitual. Se registra un motivo categorizado sin rutas privadas ni contenido del modelo. Los archivos salientes mantienen su ruta de entrega existente. En el modo directo no hay servidores, redirecciones ni URLs intermedias. El modo HTTPS autorizado posteriormente se describe abajo.

## Verificación del modo directo y limitación

El 2 de octubre de 2026 se probó la Bot API real contra el OWNER. Telegram rechazó **ambas** opciones: botón inline y entidad `text_link`, con `unsupported url protocol`. El fallback textual sí se entregó. El informe está en `docs/obsidian-validation.json`.

La [documentación oficial de InlineKeyboardButton](https://core.telegram.org/bots/api#inlinekeyboardbutton) especifica HTTP o `tg://` como destinos. Por tanto, el criterio de botón tocable que abra directamente Obsidian **no se cumple en esta Bot API**. La integración implementa el intento seguro y el fallback solicitado, sin simular éxito ni sustituir el destino.

## Archivos de esta entrega

- `app/obsidian.py`: extracción y validación puras.
- `app/bot.py`: teclado inline y restauración textual ante rechazo.
- `tests/test_obsidian.py`: validación, seguridad y pruebas de integración del envío/edición con Telegram simulado.
- `scripts/verify_obsidian.py`: prueba real de botón, fallback y entidad, usando el token configurado sin imprimirlo.
- `docs/obsidian-validation.json`: resultados de la prueba real.
- `docs/OBSIDIAN.md` y `README.md`: comportamiento y límites.

Comandos ejecutados desde `/Users/neura/repos/hermes-telegram-bot`:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.verify_obsidian
.venv/bin/python -m scripts.service restart
.venv/bin/python -m scripts.service status
```

Resultado: 84 pruebas pasaron. La prueba real verifica el fallback, pero registra la incompatibilidad del protocolo como rechazo, no como éxito del enlace tocable. El teléfono no se puede comprobar abriendo un botón que el servidor no admite.

## Puente HTTPS en GitHub Pages

El repositorio público es https://github.com/neura-neura/hermes-telegram-bot. GitHub Pages publica sólo los archivos de `bridge/` mediante `.github/workflows/pages.yml` en https://neura-neura.github.io/hermes-telegram-bot/. No se publica un backend.

`OBSIDIAN_BRIDGE_URL=https://neura-neura.github.io/hermes-telegram-bot/` activa botones HTTPS. El fragmento contiene el URI original codificado como un único componente. La página decodifica ese transporte una vez, valida y asigna exactamente el URI original al enlace y a la navegación automática. La codificación interna `%20`, Unicode y barras del URI no cambia. Sin configurar el puente se mantiene el intento directo anterior.

La página usa exclusivamente recursos propios; no tiene fetch, analítica, almacenamiento ni contenido del modelo insertado como HTML. El fragmento no forma parte de la petición HTTP al servidor, pero el enlace completo sigue estando en el mensaje de Telegram y en el navegador. GitHub Pages puede registrar la IP de visita. CSP y política de referrer limitan recursos y filtración a otras páginas.

Safari/iOS, Telegram u otros navegadores pueden exigir confirmación o un segundo toque sobre el botón de la página. Cada dispositivo necesita Obsidian y la nota/vault sincronizados con el nombre correcto. El puente no sincroniza archivos. La apertura en teléfonos requiere verificación del usuario; una aceptación del botón por Telegram no prueba que Obsidian se haya abierto allí.

Verificación adicional:

```bash
.venv/bin/python -m pytest -q
node --test tests/bridge.test.cjs
```

Resultado tras integrar el puente: 92 pruebas Python y 5 pruebas JavaScript. El deploy se verifica mediante GitHub Actions y una petición HTTPS a la página publicada.

Publicación comprobada: GitHub Actions completó el deploy, los tres recursos públicos respondieron por HTTPS y coinciden byte a byte con los archivos locales. El navegador ejecutó el script y rechazó correctamente una página sin URI. La Bot API aceptó el botón HTTPS y conservó su fragmento sin cambios; el OWNER recibió una prueba con vault ficticio porque su conversación activa no contenía un URI válido para reutilizar. Informe local: `docs/obsidian-bridge-validation.json` (excluido del repositorio público).

Comando de prueba real del puente:

```bash
.venv/bin/python -m scripts.verify_obsidian_bridge
```

## Compatibilidad con respuestas reales de Hermes

Una respuesta real usó `+` como espacio en el parámetro `file` y por eso no generó botón con la política RFC estricta. El adaptador ahora admite ese formato de formulario mediante la conversión mínima `+` → `%20`. No decodifica ni reconstruye barras, Unicode o signos más percent-encoded. El puente recibe únicamente el URI canónico validado. Los URI ya válidos no cambian, los parámetros desconocidos siguen rechazándose, y no se procesan bloques de código.

Verificación posterior: 101 pruebas Python y 5 JavaScript. Se recuperó la respuesta real del chat activo y se entregó su botón corregido sin repetir la tarea de Hermes ni modificar la nota. Evidencia local excluida de Git: `docs/obsidian-form-encoding-validation.json`.
