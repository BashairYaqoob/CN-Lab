import socket
hostname=socket.gethostname()
ip_address=socket.gethostbyname(hostname)
print(f"hostname:{hostname}")
print(f"IP_ADDRESS:{ip_address}")
