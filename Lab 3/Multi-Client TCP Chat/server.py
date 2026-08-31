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
