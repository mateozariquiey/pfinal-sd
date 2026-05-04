import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer


def normalize_message(message):
    return " ".join(message.split())


class NormalizeHandler(BaseHTTPRequestHandler):

    # Atiende peticiones POST /normalize
    def do_POST(self):
        if self.path != "/normalize":
            self.send_response(404)
            self.end_headers()
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            message = self.rfile.read(length).decode("utf-8")
            normalized = normalize_message(message).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(normalized)))
            self.end_headers()
            self.wfile.write(normalized)
        except Exception:
            self.send_response(500)
            self.end_headers()

    def log_message(self, format, *args):
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", type=int, default=8000, help="Web service port")
    args = parser.parse_args()

    server = HTTPServer(("127.0.0.1", args.p), NormalizeHandler)
    print(f"ws> init service 127.0.0.1:{args.p}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
