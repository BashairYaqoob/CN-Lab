import socket

s = socket.socket()

s.connect(('localhost', 9991))

print(s.recv(1024).decode())

s.close()
