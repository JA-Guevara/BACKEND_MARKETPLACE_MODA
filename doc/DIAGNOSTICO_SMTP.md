# Diagnostico de correo SMTP

## Resultado local — 16/09/2026

Se probo la configuracion efectiva del backend sin mostrar credenciales ni enviar mensajes:

- Conexion a smtp.gmail.com:587: correcta.
- STARTTLS y certificado: correctos.
- Autenticacion: rechazada, codigo 534; respuesta identificada como `Application-specific password required`.
- Envio y entrega: no probados porque la autenticacion fallo.

Accion: generar una contrasena de aplicacion en la cuenta de Google utilizada en SMTP_USERNAME y colocarla en SMTP_PASSWORD. Requiere verificacion en dos pasos y que las politicas de la cuenta institucional lo permitan. No utilizar la contrasena habitual ni compartirla en el chat.

Gestion: https://myaccount.google.com/apppasswords
Ayuda: https://support.google.com/accounts/answer/185833?hl=es

Esta prueba es local: no valida las variables ni la salida de red de Railway. Cambiar el .env local no modifica el servidor. Si corresponde, actualizar por separado las variables del backend desplegado y reiniciar el proceso para recargar Settings.

La primera conexion dentro del entorno restringido produjo PermissionError 10013. Al ejecutar la misma prueba con acceso de red se pudo conectar y obtener el rechazo real de autenticacion; no confundir ambos resultados.

## Ejecutar desde la carpeta del backend (PowerShell)

Solo conexion, TLS y autenticacion; no envia mensajes:

```powershell
.\.venv\Scripts\python.exe scripts/test_smtp.py
```

Envio optativo de un unico mensaje a una direccion elegida:

```powershell
.\.venv\Scripts\python.exe scripts/test_smtp.py --send-to tu-correo@dominio.com
```

Desde un servidor con Python y dependencias instaladas: `python scripts/test_smtp.py`. El script toma las variables del proceso y el .env de la raiz del backend; las variables del proceso prevalecen.

Codigos de salida: 0 correcto, 1 fallo de conexion/SMTP, 2 configuracion incompleta o incompatible. La aceptacion SMTP de un mensaje no garantiza su entrega en la bandeja de entrada: revisar spam y posibles rebotes.

El remitente actual de la aplicacion usa SMTP con STARTTLS; no soporta implicitamente SMTP_SSL por configurar el puerto 465. Para esta configuracion Gmail se utiliza puerto 587 y SMTP_USE_TLS=true.

## Archivos y verificaciones

- `scripts/test_smtp.py`: diagnostico por etapas, credenciales ocultas, sin envio salvo `--send-to`.
- `tests/unit/test_smtp_diagnostic.py`: pruebas aisladas, sin red, de autenticacion, errores, ausencia de secretos, configuracion y envio explicito.
- `src/auth/infrastructure/email/smtp_sender.py`: el remitente actual captura errores de SMTP y retorna False, por lo que no muestra la causa concreta. No se cambio su comportamiento en esta tarea.

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/unit/test_smtp_diagnostic.py -q -p no:cacheprovider
```

Pendiente: repetir autenticacion con la nueva contrasena; despues probar envio a una direccion elegida y, por separado, el entorno desplegado. No se modificaron contrasenas ni variables del usuario.
