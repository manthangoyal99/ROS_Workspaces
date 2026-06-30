import os
import paramiko
import sys
import time

host = "10.72.18.159"
user = "manthan"
password = "REDACTED"
container = "foundationpose"

print("Connecting to SSH...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect(host, username=user, password=password, timeout=10)
except Exception as e:
    print(f"Failed to connect: {e}")
    sys.exit(1)

print("Connected. Copying script to /tmp...")
sftp = ssh.open_sftp()
sftp.put("/home/ravi/pragma_ws/src/pragmabot-repro/pragmabot/nodes/server_inference.py", "/tmp/server_inference.py")
sftp.close()

print("Copying script into container...")
stdin, stdout, stderr = ssh.exec_command(f"docker cp /tmp/server_inference.py {container}:/workspace/server_inference.py")
if stdout.channel.recv_exit_status() != 0:
    print("Error copying to container:", stderr.read().decode())

print("Killing old server process if running...")
ssh.exec_command(f"docker exec {container} pkill -f server_inference.py")
time.sleep(2)

print("Starting server...")
stdin, stdout, stderr = ssh.exec_command(f"docker exec -d {container} bash -c '/opt/conda/envs/my/bin/python /workspace/server_inference.py > /workspace/server.log 2>&1'")

print("Server started in background. Tailing logs for 10 seconds...")
for _ in range(10):
    stdin, stdout, stderr = ssh.exec_command(f"docker exec {container} tail -n 5 /workspace/server.log")
    logs = stdout.read().decode().strip()
    if logs:
        print(logs)
        if "waiting for clients" in logs:
            print("SERVER IS READY!")
            break
    time.sleep(1)

ssh.close()
print("Done.")
