import os
import paramiko

HOST = "10.72.18.159"
USER = "manthan"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

key_path = os.path.expanduser("~/.ssh/id_ed25519")
password = os.environ.get("GPU_HOST_PASSWORD")

if os.path.exists(key_path):
    client.connect(HOST, username=USER, key_filename=key_path)
elif password:
    client.connect(HOST, username=USER, password=password)
else:
    raise RuntimeError("Need ~/.ssh/id_ed25519 or env var GPU_HOST_PASSWORD")

stdin, stdout, stderr = ssh.exec_command(f"docker exec {container} tail -n 25 /workspace/server.log")
print(stdout.read().decode())
ssh.close()
