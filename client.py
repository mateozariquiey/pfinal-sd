from enum import Enum
import argparse
import http.client
import os
import socket
import sys
import threading


class client:

    # ******************** TIPOS *********************
    # Codigos internos que devuelven los metodos del cliente
    class RC(Enum):
        OK = 0
        ERROR = 1
        USER_ERROR = 2
        STOP = 3

    # ****************** ATRIBUTOS *******************
    _server = None
    _port = -1
    _user = None
    _listen_socket = None
    _listen_thread = None
    _stop_event = threading.Event()
    _connected_users = {}
    _ws_host = os.getenv("WS_HOST", "127.0.0.1")
    _ws_port = int(os.getenv("WS_PORT", "8000"))

    # ******************** SOCKETS *******************
    # Envia una cadena terminada en '\0', como indica el protocolo
    @staticmethod
    def _send_string(sock, value):
        if value is None:
            value = ""
        sock.sendall(value.encode("utf-8") + b"\0")

    # Recibe una cadena terminada en '\0'
    @staticmethod
    def _recv_string(sock, max_length=256):
        data = bytearray()

        while True:
            chunk = sock.recv(1)
            if chunk == b"":
                raise ConnectionError("connection closed")
            if chunk == b"\0":
                return data.decode("utf-8")
            data.extend(chunk)
            if len(data) >= max_length:
                raise ValueError("string too long")

    # Recibe el codigo de resultado de un byte devuelto por el servidor
    @staticmethod
    def _recv_code(sock):
        data = sock.recv(1)
        if len(data) != 1:
            raise ConnectionError("connection closed")
        return data[0]

    # Recibe exactamente el numero de bytes indicado
    @staticmethod
    def _recv_all(sock, size):
        data = bytearray()

        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if chunk == b"":
                raise ConnectionError("connection closed")
            data.extend(chunk)

        return bytes(data)

    # Abre una conexion TCP con el servidor de mensajeria
    @staticmethod
    def _connect_server():
        return socket.create_connection((client._server, client._port), timeout=5)

    # Comprueba el tamano maximo de mensaje indicado en el enunciado
    @staticmethod
    def _message_is_valid(message):
        return len(message.encode("utf-8")) <= 255

    # Comprueba el tamano maximo del nombre de fichero
    @staticmethod
    def _file_name_is_valid(file_name):
        return len(file_name.encode("utf-8")) <= 255

    # Normaliza el mensaje usando el servicio web local si esta disponible
    @staticmethod
    def _normalize_message(message):
        try:
            conn = http.client.HTTPConnection(
                client._ws_host, client._ws_port, timeout=2
            )
            body = message.encode("utf-8")
            conn.request(
                "POST",
                "/normalize",
                body=body,
                headers={"Content-Type": "text/plain; charset=utf-8"},
            )
            response = conn.getresponse()
            data = response.read()
            conn.close()

            if response.status == 200:
                return data.decode("utf-8")
        except Exception:
            pass

        return message

    # ******************** ESCUCHA *******************
    # Crea el socket donde este cliente recibe mensajes del servidor
    @staticmethod
    def _create_listener():
        listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listen_socket.bind(("", 0))
        listen_socket.listen(10)
        listen_socket.settimeout(0.5)
        return listen_socket

    # Arranca el hilo que escucha mensajes entrantes del servidor
    @staticmethod
    def _start_listener(listen_socket):
        client._stop_event.clear()
        client._listen_socket = listen_socket
        client._listen_thread = threading.Thread(
            target=client._listen_loop,
            args=(listen_socket,),
            daemon=True,
        )
        client._listen_thread.start()

    # Detiene el hilo de escucha y cierra su socket
    @staticmethod
    def _stop_listener():
        client._stop_event.set()

        if client._listen_socket is not None:
            try:
                client._listen_socket.close()
            except OSError:
                pass
            client._listen_socket = None

        if (
            client._listen_thread is not None
            and threading.current_thread() != client._listen_thread
        ):
            client._listen_thread.join(timeout=1)
        client._listen_thread = None

    # Acepta conexiones del servidor mientras el usuario esta conectado
    @staticmethod
    def _listen_loop(listen_socket):
        while not client._stop_event.is_set():
            try:
                conn, _ = listen_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                client._handle_server_message(conn)
            except Exception:
                pass
            finally:
                conn.close()

    # Procesa mensajes recibidos y confirmaciones de entrega
    @staticmethod
    def _handle_server_message(sock):
        operation = client._recv_string(sock)

        if operation == "SEND MESSAGE":
            sender = client._recv_string(sock)
            msg_id = client._recv_string(sock)
            message = client._recv_string(sock)
            print(f"s> MESSAGE {msg_id} FROM {sender}")
            print(f"  {message}")
            print("  END")
        elif operation == "SEND MESSAGE ATTACH":
            sender = client._recv_string(sock)
            msg_id = client._recv_string(sock)
            message = client._recv_string(sock)
            file_name = client._recv_string(sock)
            print(f"c> MESSAGE {msg_id} FROM {sender}")
            print(f"  {message}")
            print("  END")
            print(f"  FILE {file_name}")
        elif operation == "SEND MESS ACK":
            msg_id = client._recv_string(sock)
            print(f"c> SEND MESSAGE {msg_id} OK")
        elif operation == "SEND MESS ATTACH ACK":
            msg_id = client._recv_string(sock)
            file_name = client._recv_string(sock)
            print(f"c> SENDATTACH MESSAGE {msg_id} {file_name} OK")
        elif operation == "GET FILE":
            _ = client._recv_string(sock)
            file_name = client._recv_string(sock)
            client._send_file(sock, file_name)

    # Envia el contenido de un fichero a otro cliente
    @staticmethod
    def _send_file(sock, file_name):
        if not os.path.isfile(file_name):
            sock.sendall(bytes([1]))
            return

        try:
            size = os.path.getsize(file_name)
            with open(file_name, "rb") as file:
                sock.sendall(bytes([0]))
                client._send_string(sock, str(size))
                while True:
                    data = file.read(4096)
                    if data == b"":
                        break
                    sock.sendall(data)
        except Exception:
            try:
                sock.sendall(bytes([1]))
            except Exception:
                pass

    # Interpreta las cadenas usuario::IP::puerto devueltas por USERS
    @staticmethod
    def _parse_user_info(user_info):
        parts = user_info.split("::")
        if len(parts) != 3:
            return None

        try:
            port = int(parts[2])
        except ValueError:
            return None

        return parts[0], parts[1], port

    # ******************** METODOS *******************
    # Registra un usuario en el sistema
    @staticmethod
    def register(user):
        try:
            #  Cada operacion abre una nueva conexion con el servidor
            with client._connect_server() as sock:
                client._send_string(sock, "REGISTER")
                client._send_string(sock, user)
                result = client._recv_code(sock)
        except Exception:
            print("c> REGISTER FAIL")
            return client.RC.ERROR

        if result == 0:
            print("c> REGISTER OK")
            return client.RC.OK
        if result == 1:
            print("c> USERNAME IN USE")
            return client.RC.USER_ERROR

        print("c> REGISTER FAIL")
        return client.RC.ERROR

    # Da de baja un usuario registrado
    @staticmethod
    def unregister(user):
        try:
            #  Se envia la operacion y se espera su codigo de resultado
            with client._connect_server() as sock:
                client._send_string(sock, "UNREGISTER")
                client._send_string(sock, user)
                result = client._recv_code(sock)
        except Exception:
            print("c> UNREGISTER FAIL")
            return client.RC.ERROR

        if result == 0:
            print("c> UNREGISTER OK")
            if client._user == user:
                client._stop_listener()
                client._user = None
            return client.RC.OK
        if result == 1:
            print("c> USER DOES NOT EXIST")
            return client.RC.USER_ERROR

        print("c> UNREGISTER FAIL")
        return client.RC.ERROR

    # Conecta un usuario y crea su hilo de escucha
    @staticmethod
    def connect(user):
        if client._user is not None:
            print("c> USER ALREADY CONNECTED")
            return client.RC.USER_ERROR

        try:
            #  El hilo de escucha debe estar listo antes de avisar al servidor
            listen_socket = client._create_listener()
            listen_port = listen_socket.getsockname()[1]
            client._start_listener(listen_socket)

            with client._connect_server() as sock:
                client._send_string(sock, "CONNECT")
                client._send_string(sock, user)
                client._send_string(sock, str(listen_port))
                result = client._recv_code(sock)
        except Exception:
            client._stop_listener()
            print("c> CONNECT FAIL")
            return client.RC.ERROR

        if result == 0:
            client._user = user
            print("c> CONNECT OK")
            return client.RC.OK

        #  Si falla la conexion en el servidor, se cierra la escucha local
        client._stop_listener()
        if result == 1:
            print("c> CONNECT FAIL, USER DOES NOT EXIST")
            return client.RC.USER_ERROR
        if result == 2:
            print("c> USER ALREADY CONNECTED")
            return client.RC.USER_ERROR

        print("c> CONNECT FAIL")
        return client.RC.ERROR

    # Solicita la lista de usuarios conectados
    @staticmethod
    def _request_users(show_result):
        if client._user is None:
            if show_result:
                print("c> CONNECTED USERS FAIL, USER IS NOT CONNECTED")
            return client.RC.USER_ERROR

        try:
            #  El usuario conectado identifica la peticion USERS
            with client._connect_server() as sock:
                client._send_string(sock, "USERS")
                client._send_string(sock, client._user)
                result = client._recv_code(sock)

                if result == 0:
                    count = int(client._recv_string(sock))
                    users = {}
                    user_names = []
                    for _ in range(count):
                        user_info = client._recv_string(sock)
                        parsed = client._parse_user_info(user_info)
                        if parsed is not None:
                            user_name, user_ip, user_port = parsed
                            users[user_name] = (user_ip, user_port)
                            user_names.append(user_name)
        except Exception:
            if show_result:
                print("c> CONNECTED USERS FAIL")
            return client.RC.ERROR

        if result == 0:
            client._connected_users = users
            if show_result:
                print(f"c> CONNECTED USERS ({count} users connected) OK")
                for user in user_names:
                    print(f"  {user}")
            return client.RC.OK
        if result == 1:
            if show_result:
                print("c> CONNECTED USERS FAIL, USER IS NOT CONNECTED")
            return client.RC.USER_ERROR

        if show_result:
            print("c> CONNECTED USERS FAIL")
        return client.RC.ERROR

    @staticmethod
    def users():
        return client._request_users(True)

    # Desconecta un usuario y detiene su hilo de escucha
    @staticmethod
    def disconnect(user):
        try:
            #  Se avisa al servidor antes de cerrar la escucha local
            with client._connect_server() as sock:
                client._send_string(sock, "DISCONNECT")
                client._send_string(sock, user)
                result = client._recv_code(sock)
        except Exception:
            if client._user == user:
                client._stop_listener()
                client._user = None
            print("c> DISCONNECT FAIL")
            return client.RC.ERROR

        #  El enunciado pide parar la escucha local aunque falle DISCONNECT
        if client._user == user:
            client._stop_listener()
            client._user = None

        if result == 0:
            print("c> DISCONNECT OK")
            return client.RC.OK
        if result == 1:
            print("c> DISCONNECT FAIL, USER DOES NOT EXIST")
            return client.RC.USER_ERROR
        if result == 2:
            print("c> DISCONNECT FAIL, USER NOT CONNECTED")
            return client.RC.USER_ERROR

        print("c> DISCONNECT FAIL")
        return client.RC.ERROR

    # Envia un mensaje al usuario destino
    @staticmethod
    def send(user, message):
        message = client._normalize_message(message)
        if client._user is None or not client._message_is_valid(message):
            print("c> SEND FAIL")
            return client.RC.ERROR

        try:
            #  SEND incluye remitente, destinatario y texto del mensaje
            with client._connect_server() as sock:
                client._send_string(sock, "SEND")
                client._send_string(sock, client._user)
                client._send_string(sock, user)
                client._send_string(sock, message)
                result = client._recv_code(sock)

                if result == 0:
                    msg_id = client._recv_string(sock)
        except Exception:
            print("c> SEND FAIL")
            return client.RC.ERROR

        if result == 0:
            print(f"c> SEND OK - MESSAGE {msg_id}")
            return client.RC.OK
        if result == 1:
            print("c> SEND FAIL, USER DOES NOT EXIST")
            return client.RC.USER_ERROR

        print("c> SEND FAIL")
        return client.RC.ERROR

    @staticmethod
    def sendAttach(user, file, message):
        message = client._normalize_message(message)
        if (
            client._user is None
            or not client._message_is_valid(message)
            or not client._file_name_is_valid(file)
        ):
            print("c> SENDATTACH FAIL")
            return client.RC.ERROR

        try:
            #  SENDATTACH envia mensaje y nombre de fichero al servidor
            with client._connect_server() as sock:
                client._send_string(sock, "SENDATTACH")
                client._send_string(sock, client._user)
                client._send_string(sock, user)
                client._send_string(sock, message)
                client._send_string(sock, file)
                result = client._recv_code(sock)

                if result == 0:
                    msg_id = client._recv_string(sock)
        except Exception:
            print("c> SENDATTACH FAIL")
            return client.RC.ERROR

        if result == 0:
            print(f"c> SENDATTACH OK - MESSAGE {msg_id}")
            return client.RC.OK
        if result == 1:
            print("c> SENDATTACH FAIL, USER DOES NOT EXIST")
            return client.RC.USER_ERROR

        print("c> SENDATTACH FAIL")
        return client.RC.ERROR

    # Solicita un fichero directamente a otro cliente conectado
    @staticmethod
    def getFile(user, file_name, local_file_name):
        if client._user is None:
            print("c> FILE TRANSFER FAILED, user not connected.")
            return client.RC.USER_ERROR

        if user not in client._connected_users:
            client._request_users(False)

        if user not in client._connected_users:
            print("c> FILE TRANSFER FAILED, user not connected.")
            return client.RC.USER_ERROR

        user_ip, user_port = client._connected_users[user]

        try:
            #  La transferencia del contenido se realiza cliente a cliente
            with socket.create_connection((user_ip, user_port), timeout=5) as sock:
                client._send_string(sock, "GET FILE")
                client._send_string(sock, client._user)
                client._send_string(sock, file_name)

                result = client._recv_code(sock)
                if result != 0:
                    print("c> FILE TRANSFER FAILED")
                    return client.RC.ERROR

                size = int(client._recv_string(sock))
                data = client._recv_all(sock, size)

            with open(local_file_name, "wb") as file:
                file.write(data)
        except Exception:
            print("c> FILE TRANSFER FAILED")
            return client.RC.ERROR

        print("c> FILE TRANSFER OK")
        return client.RC.OK

    @staticmethod
    def quit():
        client._stop_listener()
        client._user = None
        return client.RC.STOP

    @staticmethod
    def _cmd_register(line):
        if len(line) != 2:
            print("Syntax error. Usage: REGISTER <userName>")
            return
        user = line[1]
        return client.register(user)

    @staticmethod
    def _cmd_unregister(line):
        if len(line) != 2:
            print("Syntax error. Usage: UNREGISTER <userName>")
            return
        user = line[1]
        return client.unregister(user)

    @staticmethod
    def _cmd_connect(line):
        if len(line) != 2:
            print("Syntax error. Usage: CONNECT <userName>")
            return
        user = line[1]
        return client.connect(user)

    @staticmethod
    def _cmd_disconnect(line):
        if len(line) != 2:
            print("Syntax error. Usage: DISCONNECT <userName>")
            return
        user = line[1]
        return client.disconnect(user)

    @staticmethod
    def _cmd_users(line):
        if len(line) != 1:
            print("Syntax error. Usage: USERS")
            return
        return client.users()

    @staticmethod
    def _cmd_send(line):
        if len(line) < 3:
            print("Syntax error. Usage: SEND <userName> <message>")
            return
        user = line[1]
        message = " ".join(line[2:])
        return client.send(user, message)

    @staticmethod
    def _cmd_sendAttach(line):
        if len(line) < 4:
            print("Syntax error. Usage: SENDATTACH <userName> <fileName> <message>")
            return
        user = line[1]
        file = line[2]
        message = " ".join(line[3:])
        return client.sendAttach(user, file, message)

    @staticmethod
    def _cmd_getFile(line):
        if len(line) != 4:
            print("Syntax error. Usage: GETFILE <userName> <fileName> <localFileName>")
        user = line[1]
        file = line[2]
        local_file = line[3]
        return client.getFile(user, file, local_file)

    @staticmethod
    def _cmd_quit(line):
        if len(line) != 1:
            print("Syntax error. Usage: QUIT")
            return
        return client.quit()

    @staticmethod
    def shell():

        commands = {
            "REGISTER": client._cmd_register,
            "UNREGISTER": client._cmd_unregister,
            "CONNECT": client._cmd_connect,
            "DISCONNECT": client._cmd_disconnect,
            "USERS": client._cmd_users,
            "SEND": client._cmd_send,
            "SENDATTACH": client._cmd_sendAttach,
            "GETFILE": client._cmd_getFile,
            "QUIT": client._cmd_quit,
        }

        keepAlive = True
        while keepAlive:
            try:
                command = input("c> ")
                line = command.split(" ")
                # validate empty  commands
                if len(line) <= 0:
                    print("Error: command " + line[0] + " not valid.")

                # simulate case-insensitivity in case user puts the command in lower case
                line[0] = line[0].upper()

                # Dispatcher
                if line[0] in commands:
                    # Handle command
                    result = commands[line[0]](line)
                    # Stop if needed
                    if result == client.RC.STOP:
                        keepAlive = False
                else:  # show error for invalid commands
                    print("Error: command " + line[0] + " not valid.")

            except (EOFError, KeyboardInterrupt):
                client.quit()
                keepAlive = False

            except Exception as e:
                print("Exception: " + str(e))

    @staticmethod
    def usage():
        print("Usage: python3 client.py -s <server> -p <port>")

    @staticmethod
    def parseArguments(argv):
        parser = argparse.ArgumentParser()
        parser.add_argument("-s", type=str, required=True, help="Server IP")
        parser.add_argument("-p", type=int, required=True, help="Server Port")
        args = parser.parse_args(argv)

        if args.s is None:
            parser.error("Usage: python3 client.py -s <server> -p <port>")
            return False

        if (args.p < 1024) or (args.p > 65535):
            parser.error("Error: Port must be in the range 1024 <= port <= 65535")
            return False

        client._server = args.s
        client._port = args.p

        return True

    @staticmethod
    def main(argv):
        if not client.parseArguments(argv):
            client.usage()
            return

        client.shell()
        print("\n+++ FINISHED +++")


if __name__ == "__main__":
    client.main(sys.argv[1:])
