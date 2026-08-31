import socket
import threading

HOST = 'localhost'
PORT = 9991


# Function to continuously receive messages
def receive_messages():
    while True:
        try:
            message = client_socket.recv(1024).decode()

            if not message:
                break

            print("\nServer:", message)

        except:
            break


# Create TCP socket
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# Connect to server
client_socket.connect((HOST, PORT))

print("Connected to server")
print("Type your messages below.")
print("Type 'exit' to disconnect.")


# Create thread for receiving messages
receive_thread = threading.Thread(target=receive_messages)

# Start receiving thread
receive_thread.daemon = True
receive_thread.start()


# Main thread handles user input
while True:
    message = input("You: ")

    if message.lower() == 'exit':
        break

    # Send message to server
    client_socket.send(message.encode())


# Close connection
client_socket.close()

print("Disconnected from server")
:::
