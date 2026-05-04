const MAX_USER_LENGTH = 256;
const MAX_OPERATION_LENGTH = 256;
const MAX_FILE_LENGTH = 256;

struct log_request {
  string user<MAX_USER_LENGTH>;
  string operation<MAX_OPERATION_LENGTH>;
  string file_name<MAX_FILE_LENGTH>;
};

program LOGRPC_PROG {
  version LOGRPC_VERS {
    int LOG_OPERATION(log_request req) = 1;
  } = 1;
} = 0x20000124;
