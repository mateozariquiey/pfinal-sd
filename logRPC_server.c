#include <stdio.h>
#include <string.h>

#include "logRPC.h"

/* Servicio remoto que imprime la operacion recibida */
bool_t log_operation_1_svc(log_request req, int *result,
                           struct svc_req *rqstp) {
  (void)rqstp;

  if (strcmp(req.operation, "SENDATTACH") == 0 &&
      req.file_name != NULL && req.file_name[0] != '\0') {
    printf("%s\t%s\t%s\n", req.user, req.operation, req.file_name);
  } else {
    printf("%s\t%s\n", req.user, req.operation);
  }
  fflush(stdout);

  *result = 0;
  return TRUE;
}

/* Libera la memoria dinamica asociada a los resultados RPC */
int logrpc_prog_1_freeresult(SVCXPRT *transp, xdrproc_t xdr_result,
                             caddr_t result) {
  (void)transp;
  xdr_free(xdr_result, result);
  return 1;
}
