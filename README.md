# Practica final - Parte 1

Implementacion de la primera parte del servicio de mensajeria distribuida.

## Compilacion

```bash
make
```

Esto genera el ejecutable `server`.

## Ejecucion

En una terminal, arrancar el servidor:

```bash
./server -p 8888
```

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
QUIT
```

`SENDATTACH` pertenece a la segunda parte de la practica y en esta entrega se
deja sin funcionalidad.

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

## Pruebas recomendadas

- Registrar un usuario nuevo y repetir el registro para comprobar `USERNAME IN USE`.
- Conectar un usuario no registrado.
- Enviar mensajes entre dos usuarios conectados.
- Enviar un mensaje a un usuario registrado pero desconectado y comprobar que se entrega al reconectar.
- Consultar `USERS` desde un usuario conectado y desde un cliente sin conexion activa.
- Desconectar y dar de baja usuarios.
