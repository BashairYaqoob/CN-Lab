from socket import *

import time

startTime = time.time()

if __name__ == "__main__":
    target = input("enter the hostname to be scanned: ")
    target_ip = gethostbyname(target)
    print("starting scan on host: ", target_ip)

    for i in range(50, 500):
        s = socket(AF_INET, SOCK_STREAM)

        conn = s.connect_ex((target_ip, i))

        if(conn == 0):
            print("port %d: OPEN" %(i,))
        s.close()

print("time taken in seconds: ", time.time()-startTime)
print("time in minutes: ", (time.time()-startTime)/60)
