#include <stdlib.h>
#include <string.h>

#include "logRPC.h"
#include "logRPC_client.h"

/* Crea un manejador RPC usando la IP definida en LOG_RPC_IP */
static CLIENT *create_log_rpc_client(void) {
  char *host = getenv("LOG_RPC_IP");

  if (host == NULL || host[0] == '\0') {
    return NULL;
  }

  return clnt_create(host, LOGRPC_PROG, LOGRPC_VERS, "tcp");
}

/* Envia al servidor RPC la operacion recibida por el servidor de mensajeria */
void log_remote_operation(const char *user, const char *operation,
                          const char *file_name) {
  CLIENT *clnt;
  enum clnt_stat retval;
  log_request req;
  int result = -1;

  clnt = create_log_rpc_client();
  if (clnt == NULL) {
    return;
  }

  req.user = (char *)(user != NULL ? user : "");
  req.operation = (char *)(operation != NULL ? operation : "");
  req.file_name = (char *)(file_name != NULL ? file_name : "");

  retval = log_operation_1(req, &result, clnt);
  (void)retval;
  (void)result;

  clnt_destroy(clnt);
}
