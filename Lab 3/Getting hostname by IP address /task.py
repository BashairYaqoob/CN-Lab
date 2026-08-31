import socket
hname=socket.gethostbyaddr('172.16.5.43')
hname1=socket.gethostbyaddr('8.8.8.8')
print(f"IP_ADDRESS:{hname}")
print(f"IP_ADDRESS:{hname1}")
