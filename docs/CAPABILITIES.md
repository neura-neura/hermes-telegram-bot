# Capacidades comprobadas de la instalación

Discovery: 2 de octubre de 2026. Hermes Web UI local `127.0.0.1:8787`, gateway nativo `127.0.0.1:8642`. Fuente: código instalado en `/Users/neura/repos/hermes-webui` y `/Users/neura/.hermes/hermes-agent`; no se modificaron.

| Función | Contrato real | Gateway Telegram |
|---|---|---|
| Chats e historial | `/api/sessions`, `/api/session?session_id=`, `/api/session/new` | Listar, seleccionar, crear; historial queda en Hermes |
| Bots | Desktop Bot Mode deriva roster de perfiles y abre `Bot Chat`; `profile.yaml` contiene display_name | `/bots` abre Bot Chat; preserva perfil de interfaz, conserva propietario del chat separado |
| Perfiles | `/api/profiles`, POST `/api/profile/switch` con cookie firmada | `/profiles`; cambio explícito. Cookies por petición, sin cambiar perfil global |
| Personalidades | `/api/personalities`, `/api/personality/set` | Resolución por nombre en lenguaje natural; no se presentan como bots independientes |
| Modelos y providers | `/api/models`, `/api/session/update` | Lista paginada; selección por sesión, sin exponer claves |
| Tools | Nativo `/v1/toolsets`; WebUI `/api/session/toolsets` | Inventario, heredar perfil o restringir toolset; ejecución por Hermes |
| MCP | `/api/mcp/tools` | Consulta inventario conocido; no significa que un inventario vacío desactive MCP |
| Búsqueda | `/api/sessions/search?q=&content=1&depth=0` | Búsqueda real de conversaciones |
| Fotos e imágenes | `/api/upload`, `attachments`, native image_url o vision tool según configuración | Photo y Document, caption, neutral sin caption, álbum |
| Archivos | `/api/upload` devuelve ruta inbox; composer WebUI añade `[Attached files: ...]` | Archivo original más instrucción; formatos dependen de tools de Hermes |
| PDF y código | Original upload + tools Hermes | Contenido comprobado con fixtures y PDF real del OWNER |
| Office / ZIP / genéricos | Mismo upload; lectura/conversión por Hermes/tools | Transportados como archivo; no se promete parsing universal, ni extracción automática de ZIP |
| Voz / audio | WebUI `/api/transcribe` ofrece proveedor local | faster-whisper local medium por defecto; conserva audio original, texto al router |
| Streaming | POST `/api/chat/start`, GET `/api/chat/stream?stream_id=` | SSE, edición cada ≥1.5s, typing, eventos de tools reales |
| Aprobaciones | `/api/approval/respond`, eventos approval | Botones permitir una vez/denegar sólo OWNER |
| Clarificación | `/api/clarify/respond` | Opciones de evento; sin opciones, responder desde Web UI |
| Renombrar / archivar / eliminar | `/api/session/rename`, `/archive`, `/delete` | Eliminación con confirmación de ID capturado y callback de un uso |
| Regeneración | `/api/chat/start` con regenerate y regeneration_revision | `/regen`; rechazado honestamente si backend runner no lo soporta |
| Branching | `/api/session/branch` devuelve session_id | `/branch` |
| Ajustes | `/api/settings` | Allowlist sin secretos; toggles de visibilidad reales, compartidos con Web UI |
| Outputs | `/api/file/raw?session_id=&path=` con controles de Hermes | Enlaces locales Markdown/MEDIA se resuelven a bytes y envían como foto/audio/documento |
| Exportación | `/api/session/export?format=json` | `/export` como documento |

No se implementó una segunda base de conversaciones. SQLite guarda navegación, perfil UI, bot/propietario, mappings de IDs, callbacks con caducidad, deduplicación y contadores.

Límites: Telegram Bot API cloud descarga hasta 20 MB y permite salidas hasta 50 MB. Audio hasta 7200s configurables. Documentos complejos requieren tools y dependencias del perfil Hermes. La compatibilidad de visión depende del modelo y `agent.image_input_mode`. No se abrieron puertos ni túneles.

Las selecciones de bot abren el Bot Chat propiedad del agente, como Desktop; el perfil de interfaz permanece. Los mensajes pertenecen a ese chat real, no a una copia bajo el perfil UI.

Actualización Bot Chats canónicos: selección e historial por API nativa `/api/sessions` con `title=Bot Chat&include_hidden=true`; mensajes por `/api/sessions/{id}/chat/stream`. Archivos originales al inbox local del perfil e imágenes como image_url. No existe regeneración nativa ni selector de toolsets por sesión en esta integración; se usan tools del perfil. Exportación nativa limitada a la ventana de 200 mensajes consultada. Se verificaron respuesta de Little K y salida a chat normal conservando `default`.
