from enum import Enum
import argparse
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

    # ****************** ATRIBUTOS *******************
    _server = None
    _port = -1
    _user = None
    _listen_socket = None
    _listen_thread = None
    _stop_event = threading.Event()

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

    # Abre una conexion TCP con el servidor de mensajeria
    @staticmethod
    def _connect_server():
        return socket.create_connection((client._server, client._port), timeout=5)

    # Comprueba el tamano maximo de mensaje indicado en el enunciado
    @staticmethod
    def _message_is_valid(message):
        return len(message.encode("utf-8")) <= 255

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

        if client._listen_thread is not None and threading.current_thread() != client._listen_thread:
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
        elif operation == "SEND MESS ACK":
            msg_id = client._recv_string(sock)
            print(f"c> SEND MESSAGE {msg_id} OK")

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
    def users():
        if client._user is None:
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
                    users = []
                    for _ in range(count):
                        users.append(client._recv_string(sock))
        except Exception:
            print("c> CONNECTED USERS FAIL")
            return client.RC.ERROR

        if result == 0:
            print(f"c> CONNECTED USERS ({count} users connected) OK")
            for user in users:
                print(f"  {user}")
            return client.RC.OK
        if result == 1:
            print("c> CONNECTED USERS FAIL, USER IS NOT CONNECTED")
            return client.RC.USER_ERROR

        print("c> CONNECTED USERS FAIL")
        return client.RC.ERROR

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
        _ = (user, file, message)
        print("c> SENDATTACH FAIL")
        return client.RC.ERROR

    @staticmethod
    def shell():

        while True:
            try:
                command = input("c> ")
                line = command.split(" ")
                if len(line) > 0:

                    line[0] = line[0].upper()

                    if line[0] == "REGISTER":
                        if len(line) == 2:
                            client.register(line[1])
                        else:
                            print("Syntax error. Usage: REGISTER <userName>")

                    elif line[0] == "UNREGISTER":
                        if len(line) == 2:
                            client.unregister(line[1])
                        else:
                            print("Syntax error. Usage: UNREGISTER <userName>")

                    elif line[0] == "CONNECT":
                        if len(line) == 2:
                            client.connect(line[1])
                        else:
                            print("Syntax error. Usage: CONNECT <userName>")

                    elif line[0] == "DISCONNECT":
                        if len(line) == 2:
                            client.disconnect(line[1])
                        else:
                            print("Syntax error. Usage: DISCONNECT <userName>")

                    elif line[0] == "USERS":
                        if len(line) == 1:
                            client.users()
                        else:
                            print("Syntax error. Usage: USERS")

                    elif line[0] == "SEND":
                        if len(line) >= 3:
                            message = " ".join(line[2:])
                            client.send(line[1], message)
                        else:
                            print("Syntax error. Usage: SEND <userName> <message>")

                    elif line[0] == "SENDATTACH":
                        if len(line) >= 4:
                            message = " ".join(line[3:])
                            client.sendAttach(line[1], line[2], message)
                        else:
                            print("Syntax error. Usage: SENDATTACH <userName> <filename> <message>")

                    elif line[0] == "QUIT":
                        if len(line) == 1:
                            if client._user is not None:
                                client._stop_listener()
                                client._user = None
                            break
                        else:
                            print("Syntax error. Use: QUIT")
                    else:
                        print("Error: command " + line[0] + " not valid.")
            except EOFError:
                if client._user is not None:
                    client._stop_listener()
                    client._user = None
                break
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
        print("+++ FINISHED +++")


if __name__ == "__main__":
    client.main(sys.argv[1:])
