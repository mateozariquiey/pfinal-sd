#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
#include <pthread.h>

#define MAX_USER_LENGTH 256
#define MAX_MESSAGE_LENGTH 256
#define MAX_IP_LENGTH INET_ADDRSTRLEN
#define MAX_PORT_LENGTH 16
#define BACKLOG 128

#define RC_OK 0
#define RC_USER_ERROR 1
#define RC_ERROR 2
#define RC_CONNECT_ERROR 3

/* Mensaje almacenado en el servidor hasta que el destinatario se conecte. */
typedef struct message {
  unsigned int id;
  char sender[MAX_USER_LENGTH];
  char text[MAX_MESSAGE_LENGTH];
  struct message *next;
} message_t;

/* Informacion asociada a cada usuario registrado en el sistema. */
typedef struct user {
  char name[MAX_USER_LENGTH];
  int connected;
  char ip[MAX_IP_LENGTH];
  int port;
  unsigned int last_id;
  message_t *pending_head;
  message_t *pending_tail;
  struct user *next;
} user_t;

/* Datos que se pasan al hilo que atiende una peticion del cliente. */
typedef struct request_info {
  int socket;
  char ip[MAX_IP_LENGTH];
} request_info_t;

/* Lista global de usuarios protegida con mutex porque el servidor es multihilo. */
static user_t *users = NULL;
static pthread_mutex_t mutex_users = PTHREAD_MUTEX_INITIALIZER;
static volatile sig_atomic_t keep_running = 1;
static int server_socket = -1;

/* Cierra el socket principal para desbloquear accept al recibir Ctrl+C. */
static void sigint_handler(int sig) {
  (void)sig;
  keep_running = 0;
  if (server_socket >= 0) {
    close(server_socket);
    server_socket = -1;
  }
}

/* Envia exactamente la longitud indicada por el socket. */
static int send_all(int socket, const void *buffer, size_t length) {
  size_t bytes_sent = 0;
  const char *ptr = (const char *)buffer;

  while (bytes_sent < length) {
    ssize_t res = send(socket, ptr + bytes_sent, length - bytes_sent, 0);
    if (res <= 0) {
      return -1;
    }
    bytes_sent += (size_t)res;
  }

  return 0;
}

/* Recibe exactamente la longitud indicada del socket. */
static int recv_all(int socket, void *buffer, size_t length) {
  size_t bytes_received = 0;
  char *ptr = (char *)buffer;

  while (bytes_received < length) {
    ssize_t res = recv(socket, ptr + bytes_received,
                       length - bytes_received, 0);
    if (res <= 0) {
      return -1;
    }
    bytes_received += (size_t)res;
  }

  return 0;
}

/* En el protocolo los codigos de resultado se devuelven como un unico byte. */
static int send_byte(int socket, unsigned char value) {
  return send_all(socket, &value, sizeof(value));
}

/* Recibe una cadena terminada en '\0', tal y como especifica el enunciado. */
static int recv_string(int socket, char *buffer, size_t max_length) {
  size_t pos = 0;
  char c;

  if (max_length == 0) {
    return -1;
  }

  while (1) {
    if (recv_all(socket, &c, sizeof(c)) < 0) {
      return -1;
    }

    if (c == '\0') {
      buffer[pos] = '\0';
      return 0;
    }

    if (pos + 1 >= max_length) {
      return -1;
    }

    buffer[pos] = c;
    pos++;
  }
}

/* Envia una cadena incluyendo el caracter final '\0'. */
static int send_string(int socket, const char *str) {
  if (str == NULL) {
    str = "";
  }

  return send_all(socket, str, strlen(str) + 1);
}

/* Busca un usuario por nombre en la lista de registrados. */
static user_t *find_user(const char *name) {
  user_t *current = users;

  while (current != NULL) {
    if (strcmp(current->name, name) == 0) {
      return current;
    }
    current = current->next;
  }

  return NULL;
}

/* Libera la lista de mensajes pendientes de un usuario. */
static void delete_messages(message_t *message) {
  while (message != NULL) {
    message_t *next = message->next;
    free(message);
    message = next;
  }
}

/* Libera toda la estructura mantenida por el servidor al finalizar. */
static void free_all_users(void) {
  user_t *current = users;

  while (current != NULL) {
    user_t *next = current->next;
    delete_messages(current->pending_head);
    free(current);
    current = next;
  }

  users = NULL;
}

/* Borra los datos de conexion de un usuario sin eliminar su registro. */
static void mark_disconnected(user_t *user) {
  if (user == NULL) {
    return;
  }

  user->connected = 0;
  user->ip[0] = '\0';
  user->port = 0;
}

/* Calcula el siguiente identificador de mensaje del remitente. */
static unsigned int next_message_id(user_t *sender) {
  sender->last_id++;
  if (sender->last_id == 0) {
    sender->last_id = 1;
  }

  return sender->last_id;
}

/* Inserta un mensaje al final de la cola de pendientes del destinatario. */
static int append_message(user_t *receiver, const char *sender,
                          unsigned int id, const char *text) {
  message_t *message = calloc(1, sizeof(message_t));

  if (message == NULL) {
    return -1;
  }

  message->id = id;
  snprintf(message->sender, sizeof(message->sender), "%s", sender);
  snprintf(message->text, sizeof(message->text), "%s", text);

  if (receiver->pending_tail == NULL) {
    receiver->pending_head = message;
    receiver->pending_tail = message;
  } else {
    receiver->pending_tail->next = message;
    receiver->pending_tail = message;
  }

  return 0;
}

/* Abre una conexion TCP con el hilo de escucha de un cliente conectado. */
static int connect_to_client(const char *ip, int port) {
  struct addrinfo hints;
  struct addrinfo *res;
  char port_str[MAX_PORT_LENGTH];
  int sock;

  snprintf(port_str, sizeof(port_str), "%d", port);
  memset(&hints, 0, sizeof(hints));
  hints.ai_family = AF_INET;
  hints.ai_socktype = SOCK_STREAM;

  if (getaddrinfo(ip, port_str, &hints, &res) != 0) {
    return -1;
  }

  sock = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
  if (sock < 0) {
    freeaddrinfo(res);
    return -1;
  }

  if (connect(sock, res->ai_addr, res->ai_addrlen) < 0) {
    close(sock);
    freeaddrinfo(res);
    return -1;
  }

  freeaddrinfo(res);
  return sock;
}

/* Envia un mensaje pendiente al cliente destinatario siguiendo el protocolo. */
static int send_message_to_client(user_t *receiver, message_t *message) {
  char id_str[32];
  int sock = connect_to_client(receiver->ip, receiver->port);

  if (sock < 0) {
    return -1;
  }

  snprintf(id_str, sizeof(id_str), "%u", message->id);
  if (send_string(sock, "SEND MESSAGE") < 0 ||
      send_string(sock, message->sender) < 0 ||
      send_string(sock, id_str) < 0 ||
      send_string(sock, message->text) < 0) {
    close(sock);
    return -1;
  }

  close(sock);
  return 0;
}

/* Notifica al remitente que un mensaje suyo se ha entregado correctamente. */
static int send_ack_to_client(user_t *sender, unsigned int id) {
  char id_str[32];
  int sock = connect_to_client(sender->ip, sender->port);

  if (sock < 0) {
    return -1;
  }

  snprintf(id_str, sizeof(id_str), "%u", id);
  if (send_string(sock, "SEND MESS ACK") < 0 ||
      send_string(sock, id_str) < 0) {
    close(sock);
    return -1;
  }

  close(sock);
  return 0;
}

/* Envia los mensajes pendientes de un usuario conectado.
 * Esta funcion se invoca siempre con el mutex de usuarios bloqueado. */
static void deliver_pending_messages(user_t *receiver) {
  while (receiver != NULL && receiver->connected &&
         receiver->pending_head != NULL) {
    message_t *message = receiver->pending_head;

    if (send_message_to_client(receiver, message) < 0) {
      mark_disconnected(receiver);
      return;
    }

    receiver->pending_head = message->next;
    if (receiver->pending_head == NULL) {
      receiver->pending_tail = NULL;
    }

    printf("s> SEND MESSAGE %u FROM %s TO %s\n", message->id,
           message->sender, receiver->name);
    fflush(stdout);

    user_t *sender = find_user(message->sender);
    if (sender != NULL && sender->connected) {
      if (send_ack_to_client(sender, message->id) < 0) {
        mark_disconnected(sender);
      }
    }

    free(message);
  }
}

static void handle_register(int client_sock) {
  char user_name[MAX_USER_LENGTH];
  unsigned char result = RC_ERROR;

  /* REGISTER recibe solo el nombre de usuario. */
  if (recv_string(client_sock, user_name, sizeof(user_name)) < 0) {
    send_byte(client_sock, result);
    return;
  }

  pthread_mutex_lock(&mutex_users);
  /* Si el nombre no existe, se crea el usuario desconectado y sin mensajes. */
  if (find_user(user_name) != NULL) {
    result = RC_USER_ERROR;
  } else {
    user_t *new_user = calloc(1, sizeof(user_t));
    if (new_user != NULL) {
      snprintf(new_user->name, sizeof(new_user->name), "%s", user_name);
      new_user->connected = 0;
      new_user->last_id = 0;
      new_user->next = users;
      users = new_user;
      result = RC_OK;
    }
  }

  if (result == RC_OK) {
    printf("s> REGISTER %s OK\n", user_name);
  } else {
    printf("s> REGISTER %s FAIL\n", user_name);
  }
  fflush(stdout);
  pthread_mutex_unlock(&mutex_users);

  send_byte(client_sock, result);
}

static void handle_unregister(int client_sock) {
  char user_name[MAX_USER_LENGTH];
  unsigned char result = RC_ERROR;

  /* UNREGISTER elimina al usuario y todos sus mensajes no entregados. */
  if (recv_string(client_sock, user_name, sizeof(user_name)) < 0) {
    send_byte(client_sock, result);
    return;
  }

  pthread_mutex_lock(&mutex_users);
  user_t *previous = NULL;
  user_t *current = users;

  while (current != NULL && strcmp(current->name, user_name) != 0) {
    previous = current;
    current = current->next;
  }

  if (current == NULL) {
    result = RC_USER_ERROR;
  } else {
    if (previous == NULL) {
      users = current->next;
    } else {
      previous->next = current->next;
    }

    delete_messages(current->pending_head);
    free(current);
    result = RC_OK;
  }

  if (result == RC_OK) {
    printf("s> UNREGISTER %s OK\n", user_name);
  } else {
    printf("s> UNREGISTER %s FAIL\n", user_name);
  }
  fflush(stdout);
  pthread_mutex_unlock(&mutex_users);

  send_byte(client_sock, result);
}

static void handle_connect(int client_sock, const char *client_ip) {
  char user_name[MAX_USER_LENGTH];
  char port_str[MAX_PORT_LENGTH];
  int port;
  unsigned char result = RC_CONNECT_ERROR;

  /* CONNECT recibe el usuario y el puerto donde escucha el cliente. */
  if (recv_string(client_sock, user_name, sizeof(user_name)) < 0 ||
      recv_string(client_sock, port_str, sizeof(port_str)) < 0) {
    send_byte(client_sock, result);
    return;
  }

  port = atoi(port_str);

  pthread_mutex_lock(&mutex_users);
  user_t *user = find_user(user_name);
  /* La IP se obtiene de accept; el cliente solo envia su puerto. */
  if (user == NULL) {
    result = RC_USER_ERROR;
  } else if (user->connected) {
    result = RC_ERROR;
  } else if (port <= 0 || port > 65535) {
    result = RC_CONNECT_ERROR;
  } else {
    user->connected = 1;
    snprintf(user->ip, sizeof(user->ip), "%s", client_ip);
    user->port = port;
    result = RC_OK;
  }

  if (result == RC_OK) {
    printf("s> CONNECT %s OK\n", user_name);
  } else {
    printf("s> CONNECT %s FAIL\n", user_name);
  }
  fflush(stdout);
  pthread_mutex_unlock(&mutex_users);

  if (send_byte(client_sock, result) < 0) {
    return;
  }

  if (result == RC_OK) {
    /* Al conectarse se intentan entregar todos sus mensajes pendientes. */
    pthread_mutex_lock(&mutex_users);
    user = find_user(user_name);
    if (user != NULL && user->connected) {
      deliver_pending_messages(user);
    }
    pthread_mutex_unlock(&mutex_users);
  }
}

static void handle_disconnect(int client_sock, const char *client_ip) {
  char user_name[MAX_USER_LENGTH];
  unsigned char result = RC_CONNECT_ERROR;

  /* DISCONNECT solo se acepta desde la misma IP de la conexion activa. */
  if (recv_string(client_sock, user_name, sizeof(user_name)) < 0) {
    send_byte(client_sock, result);
    return;
  }

  pthread_mutex_lock(&mutex_users);
  user_t *user = find_user(user_name);

  if (user == NULL) {
    result = RC_USER_ERROR;
  } else if (!user->connected) {
    result = RC_ERROR;
  } else if (strcmp(user->ip, client_ip) != 0) {
    result = RC_CONNECT_ERROR;
  } else {
    mark_disconnected(user);
    result = RC_OK;
  }

  if (result == RC_OK) {
    printf("s> DISCONNECT %s OK\n", user_name);
  } else {
    printf("s> DISCONNECT %s FAIL\n", user_name);
  }
  fflush(stdout);
  pthread_mutex_unlock(&mutex_users);

  send_byte(client_sock, result);
}

static void handle_users(int client_sock) {
  char user_name[MAX_USER_LENGTH];
  unsigned char result = RC_ERROR;

  /* USERS requiere que el solicitante este registrado y conectado. */
  if (recv_string(client_sock, user_name, sizeof(user_name)) < 0) {
    send_byte(client_sock, result);
    return;
  }

  pthread_mutex_lock(&mutex_users);
  user_t *requester = find_user(user_name);

  if (requester == NULL) {
    result = RC_ERROR;
  } else if (!requester->connected) {
    result = RC_USER_ERROR;
  } else {
    result = RC_OK;
  }

  if (result != RC_OK) {
    printf("s> CONNECTEDUSERS FAIL\n");
    fflush(stdout);
    pthread_mutex_unlock(&mutex_users);
    send_byte(client_sock, result);
    return;
  }

  int count = 0;
  user_t *current = users;
  char count_str[32];

  /* Primero se envia el numero de usuarios conectados. */
  while (current != NULL) {
    if (current->connected) {
      count++;
    }
    current = current->next;
  }

  snprintf(count_str, sizeof(count_str), "%d", count);
  if (send_byte(client_sock, result) < 0 ||
      send_string(client_sock, count_str) < 0) {
    pthread_mutex_unlock(&mutex_users);
    return;
  }

  current = users;
  /* Despues se envia una cadena por cada usuario conectado. */
  while (current != NULL) {
    if (current->connected) {
      if (send_string(client_sock, current->name) < 0) {
        pthread_mutex_unlock(&mutex_users);
        return;
      }
    }
    current = current->next;
  }

  printf("s> CONNECTEDUSERS OK\n");
  fflush(stdout);
  pthread_mutex_unlock(&mutex_users);
}

static void handle_send(int client_sock) {
  char sender_name[MAX_USER_LENGTH];
  char receiver_name[MAX_USER_LENGTH];
  char text[MAX_MESSAGE_LENGTH];
  unsigned int id = 0;
  int receiver_connected = 0;
  unsigned char result = RC_ERROR;

  /* SEND recibe remitente, destinatario y texto del mensaje. */
  if (recv_string(client_sock, sender_name, sizeof(sender_name)) < 0 ||
      recv_string(client_sock, receiver_name, sizeof(receiver_name)) < 0 ||
      recv_string(client_sock, text, sizeof(text)) < 0) {
    send_byte(client_sock, result);
    return;
  }

  pthread_mutex_lock(&mutex_users);
  user_t *sender = find_user(sender_name);
  user_t *receiver = find_user(receiver_name);

  if (sender == NULL || receiver == NULL) {
    result = RC_USER_ERROR;
  } else {
    /* Siempre se almacena antes de responder al remitente. */
    id = next_message_id(sender);
    if (append_message(receiver, sender_name, id, text) == 0) {
      result = RC_OK;
      receiver_connected = receiver->connected;
    }
  }

  if (result == RC_OK && !receiver_connected) {
    printf("s> MESSAGE %u FROM %s TO %s STORED\n", id, sender_name,
           receiver_name);
    fflush(stdout);
  }
  pthread_mutex_unlock(&mutex_users);

  if (send_byte(client_sock, result) < 0) {
    return;
  }

  if (result == RC_OK) {
    char id_str[32];
    snprintf(id_str, sizeof(id_str), "%u", id);
    if (send_string(client_sock, id_str) < 0) {
      return;
    }

    if (receiver_connected) {
      /* Si el destinatario esta conectado, se intenta entregar inmediatamente. */
      pthread_mutex_lock(&mutex_users);
      receiver = find_user(receiver_name);
      if (receiver != NULL && receiver->connected) {
        deliver_pending_messages(receiver);
      }
      pthread_mutex_unlock(&mutex_users);
    }
  }
}

static void *handle_request(void *arg) {
  request_info_t *request = (request_info_t *)arg;
  int client_sock = request->socket;
  char client_ip[MAX_IP_LENGTH];
  char operation[MAX_USER_LENGTH];

  snprintf(client_ip, sizeof(client_ip), "%s", request->ip);
  free(request);

  if (recv_string(client_sock, operation, sizeof(operation)) < 0) {
    close(client_sock);
    return NULL;
  }

  /* Cada conexion contiene una unica operacion de protocolo. */
  if (strcmp(operation, "REGISTER") == 0) {
    handle_register(client_sock);
  } else if (strcmp(operation, "UNREGISTER") == 0) {
    handle_unregister(client_sock);
  } else if (strcmp(operation, "CONNECT") == 0) {
    handle_connect(client_sock, client_ip);
  } else if (strcmp(operation, "DISCONNECT") == 0) {
    handle_disconnect(client_sock, client_ip);
  } else if (strcmp(operation, "USERS") == 0) {
    handle_users(client_sock);
  } else if (strcmp(operation, "SEND") == 0) {
    handle_send(client_sock);
  } else {
    send_byte(client_sock, RC_ERROR);
  }

  close(client_sock);
  return NULL;
}

/* Comprueba los argumentos del servidor: ./server -p <port>. */
static int parse_port(int argc, char *argv[]) {
  int port;

  if (argc != 3 || strcmp(argv[1], "-p") != 0) {
    fprintf(stderr, "Uso: %s -p <port>\n", argv[0]);
    return -1;
  }

  port = atoi(argv[2]);
  if (port < 1024 || port > 65535) {
    fprintf(stderr, "Error: puerto fuera de rango\n");
    return -1;
  }

  return port;
}

int main(int argc, char *argv[]) {
  int port = parse_port(argc, argv);
  int opt = 1;
  struct sockaddr_in address;
  struct sigaction action;

  if (port < 0) {
    return -1;
  }

  /* SIGPIPE se ignora para que un cliente caido no termine el servidor. */
  signal(SIGPIPE, SIG_IGN);
  memset(&action, 0, sizeof(action));
  action.sa_handler = sigint_handler;
  sigaction(SIGINT, &action, NULL);

  server_socket = socket(AF_INET, SOCK_STREAM, 0);
  if (server_socket < 0) {
    perror("socket");
    return -1;
  }

  if (setsockopt(server_socket, SOL_SOCKET, SO_REUSEADDR, &opt,
                 sizeof(opt)) < 0) {
    perror("setsockopt");
    close(server_socket);
    return -1;
  }

  memset(&address, 0, sizeof(address));
  address.sin_family = AF_INET;
  address.sin_addr.s_addr = INADDR_ANY;
  address.sin_port = htons((uint16_t)port);

  if (bind(server_socket, (struct sockaddr *)&address, sizeof(address)) < 0) {
    perror("bind");
    close(server_socket);
    return -1;
  }

  if (listen(server_socket, BACKLOG) < 0) {
    perror("listen");
    close(server_socket);
    return -1;
  }

  printf("s> init server 0.0.0.0:%d\n", port);
  printf("s>\n");
  fflush(stdout);

  while (keep_running) {
    struct sockaddr_in client_addr;
    socklen_t addrlen = sizeof(client_addr);
    request_info_t *request = malloc(sizeof(request_info_t));

    if (request == NULL) {
      perror("malloc");
      continue;
    }

    request->socket =
        accept(server_socket, (struct sockaddr *)&client_addr, &addrlen);
    if (request->socket < 0) {
      free(request);
      if (!keep_running || errno == EBADF || errno == EINTR) {
        break;
      }
      perror("accept");
      continue;
    }

    if (inet_ntop(AF_INET, &client_addr.sin_addr, request->ip,
                  sizeof(request->ip)) == NULL) {
      snprintf(request->ip, sizeof(request->ip), "127.0.0.1");
    }

    /* Cada cliente se atiende en un hilo separado. */
    pthread_t thread;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);

    if (pthread_create(&thread, &attr, handle_request, request) != 0) {
      perror("pthread_create");
      close(request->socket);
      free(request);
    }
    pthread_attr_destroy(&attr);
  }

  /* Liberacion ordenada de memoria antes de terminar. */
  pthread_mutex_lock(&mutex_users);
  free_all_users();
  pthread_mutex_unlock(&mutex_users);
  pthread_mutex_destroy(&mutex_users);

  if (server_socket >= 0) {
    close(server_socket);
  }

  return 0;
}
