CC = gcc
CFLAGS = -Wall -Wextra -pthread -g -I/usr/include/tirpc
RPCGEN_CFLAGS = -Wall -Wextra -g -I/usr/include/tirpc -Wno-unused-parameter -Wno-unused-variable -Wno-cast-function-type
LDLIBS_RPC = -ltirpc -lnsl -lpthread
RPCGEN = rpcgen

RPC_GEN_FILES = logRPC.h logRPC_clnt.c logRPC_svc.c logRPC_xdr.c

all: server logRPC_server

server: server.c logRPC_client.c logRPC_clnt.c logRPC_xdr.c logRPC.h logRPC_client.h
	$(CC) $(RPCGEN_CFLAGS) -pthread -o server server.c logRPC_client.c logRPC_clnt.c logRPC_xdr.c $(LDLIBS_RPC)

logRPC_server: logRPC_server.c logRPC_svc.c logRPC_xdr.c logRPC.h
	$(CC) $(RPCGEN_CFLAGS) -o logRPC_server logRPC_server.c logRPC_svc.c logRPC_xdr.c $(LDLIBS_RPC)

$(RPC_GEN_FILES) &: logRPC.x
	rm -f $(RPC_GEN_FILES)
	$(RPCGEN) -NM logRPC.x

rpcgen: $(RPC_GEN_FILES)

clean:
	rm -f server logRPC_server

.PHONY: all clean rpcgen
