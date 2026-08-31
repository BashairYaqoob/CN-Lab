# Task: You are required to design and implement a network application based on the Client-Server architecture that enables 
# real-time text messaging between a server and connected clients over a TCP network. The server must bind to 
# a specified port and continuously listen for incoming connections, spawning a dedicated thread for each client to handle 
# multi-client communication concurrently. The system should support full-duplex communication, allowing users to send and 
# receive text messages continuously without blocking the main execution loop. On the client side, the application must 
# provide an interactive prompt for entering text messages and immediately transmitting them over the socket connection. 
# Explain the design, socket setup procedures, and multi-threading mechanisms required to build this system, 
# and write the complete program code for both the client and server components. 
# (Note: Solve this task using the concepts mentioned in the manual.)

import socket
import threading

HOST = 'localhost'
PORT = 9991


# Function to handle each connected client
def handle_client(client_socket, address):
    print("Connected with:", address)

    while True:
        try:
            # Receive message from client
            message = client_socket.recv(1024).decode()

            # If client disconnects
            if not message:
                break

            print("Message from", address, ":", message)

            # Send response back to client
            response = "Server received: " + message
            client_socket.send(response.encode())

        except:
            break

    print("Client disconnected:", address)
    client_socket.close()


# Create TCP socket
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

print("Socket created")

# Bind socket to IP address and port
server_socket.bind((HOST, PORT))

print("Server is running on port", PORT)

# Listen for incoming connections
server_socket.listen(5)

print("Waiting for clients...")


# Continuously accept clients
while True:
    client_socket, address = server_socket.accept()

    # Create a separate thread for each client
    client_thread = threading.Thread(
        target=handle_client,
        args=(client_socket, address)
    )

    client_thread.start()

    print("Active threads:", threading.active_count())
