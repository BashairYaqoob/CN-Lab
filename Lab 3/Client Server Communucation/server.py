import socket

s = socket.socket()
print("socket is created")

s.bind(('localhost', 9991))

s.listen(5)

while True:
    c, addr = s.accept()
    print("connection from", addr)

    c.send(bytes("Thanks for connecting...", "utf-8"))

    c.close()
