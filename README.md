# Practica final

Implementacion del servicio de mensajeria distribuida.

Incluye:

- Parte 1: registro, conexion, desconexion, usuarios conectados y envio de mensajes.
- Parte 2: envio de mensajes con fichero adjunto, transferencia de ficheros cliente-cliente, servicio web de normalizacion y servidor RPC de registro de operaciones.

## Compilacion

```bash
make
```

Esto genera:

```text
server
logRPC_server
```

Si se modifica `logRPC.x`, se pueden regenerar los stubs RPC con:

```bash
make rpcgen
```

## Ejecucion

### Servicio RPC

Antes de ejecutar el servidor RPC, `rpcbind` debe estar activo:

```bash
sudo systemctl start rpcbind
```

Arrancar el servidor RPC:

```bash
./logRPC_server
```

### Servicio web

En otra terminal, arrancar el servicio web local:

```bash
python3 web_service.py -p 8000
```

El cliente usa por defecto `127.0.0.1:8000`. Se puede cambiar con:

```bash
export WS_HOST=127.0.0.1
export WS_PORT=8000
```

### Servidor de mensajeria

En otra terminal, arrancar el servidor:

```bash
LOG_RPC_IP=127.0.0.1 ./server -p 8888
```

Si no se quiere usar RPC, se puede ejecutar sin `LOG_RPC_IP` y el servidor de
mensajeria seguira funcionando:

```bash
./server -p 8888
```

### Clientes

En otra terminal, arrancar un cliente:

```bash
python3 client.py -s 127.0.0.1 -p 8888
```

Para probar comunicacion entre usuarios, abrir dos clientes distintos contra el
mismo servidor.

## Comandos disponibles en el cliente

```text
REGISTER <userName>
UNREGISTER <userName>
CONNECT <userName>
DISCONNECT <userName>
USERS
SEND <userName> <message>
SENDATTACH <userName> <fileName> <message>
GETFILE <userName> <fileName> <localFileName>
QUIT
```

## Ejemplo de prueba

Cliente 1:

```text
c> REGISTER ana
c> CONNECT ana
```

Cliente 2:

```text
c> REGISTER bob
c> CONNECT bob
c> SEND ana hola ana
```

El cliente de `ana` recibira:

```text
s> MESSAGE 1 FROM bob
  hola ana
  END
```

El cliente de `bob` recibira la confirmacion:

```text
c> SEND MESSAGE 1 OK
```

## Ejemplo con fichero adjunto

Cliente 1:

```text
c> REGISTER ana
c> CONNECT ana
```

Cliente 2:

```text
c> REGISTER bob
c> CONNECT bob
c> USERS
c> SENDATTACH ana /tmp/datos.txt mensaje     con      fichero
```

El mensaje se normaliza usando el servicio web y el cliente de `ana` recibe:

```text
c> MESSAGE 1 FROM bob
  mensaje con fichero
  END
  FILE /tmp/datos.txt
```

Despues, `ana` puede recuperar el fichero directamente desde el cliente de
`bob`:

```text
c> GETFILE bob /tmp/datos.txt /tmp/copia_datos.txt
c> FILE TRANSFER OK
```

## Pruebas recomendadas

- Registrar un usuario nuevo y repetir el registro para comprobar `USERNAME IN USE`.
- Conectar un usuario no registrado.
- Enviar mensajes entre dos usuarios conectados.
- Enviar un mensaje a un usuario registrado pero desconectado y comprobar que se entrega al reconectar.
- Enviar `SENDATTACH` a un usuario conectado y comprobar el ACK con nombre de fichero.
- Enviar `SENDATTACH` a un usuario desconectado y comprobar que se entrega al reconectar.
- Transferir un fichero con `GETFILE` entre dos usuarios conectados.
- Pedir un fichero a un usuario desconectado.
- Enviar mensajes con espacios repetidos y comprobar la normalizacion.
- Comprobar que `logRPC_server` imprime las operaciones recibidas.
- Consultar `USERS` desde un usuario conectado y desde un cliente sin conexion activa.
- Desconectar y dar de baja usuarios.
