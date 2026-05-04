CC = gcc
CFLAGS = -Wall -Wextra -pthread -g

all: server

server: server.c
	$(CC) $(CFLAGS) -o server server.c

clean:
	rm -f server

.PHONY: all clean
