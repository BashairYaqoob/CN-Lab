import socket

def find_service_name():
    protocol_name = 'tcp'
    for port in [80,25]:
        print("port %s => service name is: %s" %(port, socket.getservbyport(port, protocol_name)))

    print("port %s => service name: %s" %(53, socket.getservbyport(53, 'udp')))

if __name__ == "__main__":
    find_service_name()
