# Hermes Telegram Bot

Gateway instalado en `/Users/neura/repos/hermes-telegram-bot`, bot normal [@hermeshermesagent_bot](https://t.me/hermeshermesagent_bot), OWNER configurado mediante `OWNER_USER_ID`. Usa long polling; no requiere cuenta MTProto, SMS ni sesiones humanas. Little K y sus servicios existentes permanecen separados.

Python 3.12.10 ARM64 de `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3`, seleccionado por compatibilidad de las ruedas Whisper/CTranslate2/PyAV. Todo Python corre en `.venv/`. Librería Telegram: python-telegram-bot 22.8 async. Dependencias exactas en `requirements.txt`, incluido PyAV 16.1 compatible con faster-whisper 1.2.1.

## Arquitectura

Telegram → handlers async → routing/media/storage mínimo → HermesClient → API real de Hermes Web UI `http://127.0.0.1:8787`. Inventario tools desde gateway nativo `http://127.0.0.1:8642[/p/perfil]/v1/toolsets`. Los Bot Chats canónicos de Desktop usan la API nativa `/api/sessions/{id}/chat/stream`, incluyendo el historial existente. Hermes conserva chats, mensajes, herramientas, modelos, perfiles y archivos.

La contraseña de Web UI se reutiliza leyendo `/Users/neura/repos/hermes-webui/.env`; las claves de la API nativa se leen desde `.hermes` por perfil. No se copian ni se muestran. Login y cookies de perfiles firmadas se obtienen por las APIs reales, con cookies separadas por petición. No se cambia el perfil global de Web UI.

`/bots` y «quiero hablar con Little K» abren el chat del bot conservando tu perfil actual. El propietario del Bot Chat y el perfil de interfaz son datos distintos, como en Desktop. `/profiles` cambia el perfil explícitamente. El roster se deriva de los perfiles reales y sus nombres de `profile.yaml`. No se clona la personalidad de Little K.

## Uso

`/start` o `/home`: Chats, Bots, Perfiles, Nuevo chat, Modelos, Tools, Ajustes, Actualizar y Estado. Menús editan el mensaje existente; listas paginadas, callbacks cortos y vinculados al usuario/chat/topic, caducidad de 24h.

Envía texto sin `/ask`. Fotos y PNG como documento llegan realmente a Hermes; captions pertenecen a la misma solicitud. Álbumes se agrupan con debounce de 1.2s. Documentos, PDF, código, TXT, Markdown, CSV, JSON, XML, Office y ZIP se suben originales; su interpretación depende de Hermes y sus tools. PDF/código/CSV se verificaron; no se garantiza interpretación de todos los formatos. Para archivos enviados por separado: `/attach`, archivos y `/send compáralos`. No se adivina asociación entre mensajes independientes.

Replies usan mappings para volver al chat correcto sin reenviar el attachment original. El contexto separa chat, topic y usuario. Para grupos, configura IDs autorizados: responde sólo a comando, mención o reply al bot. Privacy Mode puede quedarse activado; BotFather `/setprivacy` sólo es necesario si decides recibir mensajes no mencionados en grupos, comportamiento que este gateway no procesa por defecto.

Voz/audio OGG/Opus, MP3, M4A, WAV y formatos decodificables por ffmpeg: normalización mono 16kHz, Whisper local, router y Hermes. Transcripción gratuita `faster-whisper`, modelo **medium**, CPU int8, cuatro hilos; idioma automático. Modelo small confundió una nota real española con portugués, por eso se seleccionó medium tras probarla. Se verificaron español, inglés y chino, silencio y reunión sintética larga. No hay diarización. Configurables `TRANSCRIPTION_ENGINE`, `TRANSCRIPTION_MODEL`, `TRANSCRIPTION_LANGUAGE`, `MAX_AUDIO_SECONDS`. `hermes-local` reutiliza STT de Hermes sólo si anuncia un proveedor local.

Hermes genera outputs: enlaces locales Markdown o `MEDIA:` se resuelven por la API de archivos de Hermes y se entregan bytes reales como foto, audio o documento. No se descargan URLs arbitrarias. En chats Web UI los permisos de archivos los aplica Hermes. En Bot Chats nativos los archivos entran al inbox local del perfil; las salidas se restringen a workspace e inbox Telegram, con bloqueo de archivos privados. Mensajes largos se dividen; Markdown parcial se convierte a HTML escapado y falla a texto plano, preservando links. Streaming con throttling, typing cada 4s; tools y solicitudes de aprobación provienen de eventos reales.

## Comandos registrados (29)

`/start /home /help /status /new /chats /chat /bots /bot /profiles /profile /models /model /providers /tools /current /back /search /rename /archive /delete /regen /branch /settings /refresh /cancel /attach /send /export`

Para salir del bot y abrir un chat normal en tu perfil: «sal del bot», «abre un chat normal» o «deja de hablar con el bot y abre una conversación en mi perfil actual». También `/new` → 💬 Normal. Esto conserva la conversación del bot.

Ejemplos: `/search Telegram`, `/rename Proyecto`, «muéstrame mis chats», «quiero hablar con Little K», «abre Little K y pregúntale qué está haciendo», «regresa al anterior». Intenciones deterministas; no se llama un LLM para menús. Nombres ambiguos abren selector. El intérprete natural no entiende cualquier paráfrasis; texto ordinario va a Hermes.

## Permisos y privacidad

`.env` tiene modo 600, está ignorado; `.env.example` contiene placeholders. OWNER tiene acceso completo. `ALLOWED_USER_IDS` y `ALLOWED_CHAT_IDS` separan identidad y chat: grupos requieren ambos usuario y chat autorizados; OWNER también requiere grupo autorizado. Administración sólo OWNER. No se usan usernames para autorización. No hay logs de conversaciones, transcripciones ni tokens por defecto; errores se registran por clase.

SQLite: `data/state.sqlite3`, WAL, state de UI y mappings mínimos. Updates se marcan antes de ejecutar para no repetir herramientas tras una caída; una operación ambigua requiere revisar el chat Hermes antes de reenviar. No se promete exactamente una vez a través de dos servicios. Archivos temporales en `data/tmp` se borran al concluir; uploads permanentes pertenecen a Hermes. Modelo local en `data/models`. Los pending de `/attach` se conservan sólo en memoria; reiniciar los descarta. Álbum en curso puede requerir reenvío tras una caída. Grupos/topics no se probaron en un grupo real.

## Servicio macOS

LaunchAgent `com.neura.hermes-telegram-bot`, plist `/Users/neura/Library/LaunchAgents/com.neura.hermes-telegram-bot.plist`. Ejecuta explícitamente `/Users/neura/repos/hermes-telegram-bot/.venv/bin/python -m app`. RunAtLoad, KeepAlive, intervalo de reinicio 10s, bloqueo de proceso para impedir dos pollers. Arranca al iniciar sesión del usuario; no es un LaunchDaemon previo al login. Cuando Hermes no está disponible, el gateway sigue disponible y las conexiones tienen retries. No se repiten turnos de resultado ambiguo.

Desde el proyecto:

```bash
.venv/bin/python -m scripts.service status
.venv/bin/python -m scripts.service start
.venv/bin/python -m scripts.service stop
.venv/bin/python -m scripts.service restart
.venv/bin/python -m scripts.doctor
.venv/bin/python -m pytest -q
tail -f logs/gateway.log
```

Logs rotatorios `logs/gateway.log` (5 MB × 5), `launchd.out.log`, `launchd.err.log`. Doctor prueba identidad real, comandos, backend, chats, perfiles/bots, modelos/tools, DB, storage, STT, ffmpeg y launchd. Muestra evidencias E2E previas separadas de probes actuales.

## Instalación reproducible / actualización

La instalación en esta Mac ya está realizada. Para reconstruir el entorno, detener servicio, crear venv con el Python indicado e instalar `requirements.txt` dentro del venv. Configurar `.env` desde placeholders y hacer `chmod 600 .env`; definir `HERMES_WEBUI_ENV` si cambias ruta. ffmpeg ya existe en `/opt/homebrew/bin/ffmpeg`. Modelo se descarga una vez (requiere red); transcripción después es local.

```bash
.venv/bin/python -m scripts.service stop
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.service start
.venv/bin/python -m scripts.doctor
```

Desinstalar servicio: `.venv/bin/python -m scripts.service uninstall`. Conserva proyecto, `.env`, DB y conversaciones Hermes. Borrar el proyecto después sólo si ya no lo necesitas.

## Validación

[Mapa de capacidades](docs/CAPABILITIES.md), [pruebas controladas reales](docs/validation.json), [audio e idiomas](docs/audio-validation.json), [voz original del OWNER](docs/real-voice-validation.json), [PDF original del OWNER](docs/real-pdf-validation.json), [audio largo](docs/long-audio-validation.json), [selección de bot conservando perfil](docs/bot-selection-validation.json).

Pruebas controladas realizan generaciones reales Hermes y entregas Bot API, pero no simulan que mensajes fueron enviados por la cuenta OWNER. Recepción genuina de `/start`, foto, PDF y voz se verificó con mensajes del usuario. El usuario verificó botones Chats/Bots/Perfiles/Inicio y «hola». Primeros fallos se corrigieron y los documentos originales se reprocesaron sin pedir reenvío. Las pruebas de eliminación usaron sólo recursos desechables de validación.

Límites oficiales: [Telegram Bot API](https://core.telegram.org/bots/api), [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## Bot Chats nativos

La selección de Little K se verificó contra su chat canónico existente y conservó el perfil `default`. La salida a conversación normal también se comprobó con la API real. `/regen` no está expuesto por la API nativa; `/tools` muestra inventario y el bot hereda las herramientas de su perfil. `/export` entrega la ventana de historial disponible (hasta 200 mensajes) en Bot Chats nativos. Si el bot vivo deja una tarea en cola, Telegram lo informa y pide revisar Hermes antes de reenviar.

## Autenticación de todos los bots

La API multiplexada exige `API_SERVER_KEY` propia por perfil, aunque la app Desktop pueda usar los bots sin esa clave. Se configuraron las claves faltantes en los seis perfiles, conservando las de default y Little K y todos los ajustes existentes. `scripts.doctor` comprueba la autenticación de cada perfil. Para habilitar perfiles nuevos: `.venv/bin/python -m scripts.configure_native_profiles`; preserva las claves existentes, genera claves independientes con permisos 600 y verifica los chats canónicos por API.

## Obsidian

Las respuestas con URIs Obsidian se validan sin reescribir el destino. Con `OBSIDIAN_BRIDGE_URL=https://neura-neura.github.io/hermes-telegram-bot/`, Telegram muestra **Abrir en Obsidian** con destino HTTPS; la página estática valida el fragmento e intenta abrir el URI original en ese dispositivo. Puede requerir confirmación o un toque adicional del navegador. No hay servidor local ni backend del puente. Sin el puente, la Bot API rechaza el protocolo directo y se entrega texto como fallback. Política y pruebas en [docs/OBSIDIAN.md](docs/OBSIDIAN.md).
