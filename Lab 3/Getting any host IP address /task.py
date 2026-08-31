import socket

hostnames=["www.google.com", "www.facebook.com"]

for i in hostnames:
    ip_address=socket.gethostbyname(i)
    print(f"hostname:{hostnames}")
    print(f"IP_ADDRESS:{ip_address}")
