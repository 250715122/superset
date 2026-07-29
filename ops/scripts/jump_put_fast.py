"""jump_put.py faster variant: bigger chunks (paramiko window flow-control keeps it safe).

Usage: python jump_put_fast.py <localfile> <prod_remote_path>
"""
import base64
import hashlib
import sys
import time

import paramiko

JHOST = "jumpserver.poweroak.ltd"
JPORT = 2222
JUSER = "guote@poweroak.net"
JPASS = "qq250715122"

LOCAL = sys.argv[1]
PROD_PATH = sys.argv[2]
PROD_B64 = PROD_PATH + ".b64"


def drain(chan, seconds, echo=True):
    end = time.time() + seconds
    buf = b""
    while time.time() < end:
        while chan.recv_ready():
            buf += chan.recv(65536)
        time.sleep(0.1)
    if echo:
        sys.stdout.buffer.write(buf)
        sys.stdout.flush()
    return buf.decode("utf-8", "replace")


def wait_for(chan, sub, timeout=30):
    end = time.time() + timeout
    acc = ""
    while time.time() < end:
        if chan.recv_ready():
            acc += chan.recv(65536).decode("utf-8", "replace")
            if sub in acc:
                return acc
        else:
            time.sleep(0.15)
    return acc


data = open(LOCAL, "rb").read()
local_sha = hashlib.sha256(data).hexdigest()
b64 = base64.b64encode(data).decode("ascii")
lines = [b64[i:i + 76] for i in range(0, len(b64), 76)]
payload = "\n".join(lines) + "\n"
print(f"LOCAL sha256={local_sha} bytes={len(data)}")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(JHOST, port=JPORT, username=JUSER, password=JPASS,
               look_for_keys=False, allow_agent=False, timeout=20)
chan = client.invoke_shell(width=200, height=50)
drain(chan, 3, echo=False)

chan.send("/Flink\n")
time.sleep(3)
drain(chan, 1, echo=False)
chan.send("1\n")
wait_for(chan, "StarRocks-01", timeout=25)
time.sleep(2)
drain(chan, 1, echo=False)

recv_cmd = f'ssh -o StrictHostKeyChecking=no 10.100.19.1 "cat > {PROD_B64}"\n'
print(f"[RECEIVER] {recv_cmd.strip()}")
chan.send(recv_cmd)
time.sleep(3)
drain(chan, 1, echo=False)

CHUNK = 2048
t0 = time.time()
sent = 0
for i in range(0, len(payload), CHUNK):
    chan.send(payload[i:i + CHUNK])
    sent += min(CHUNK, len(payload) - i)
    time.sleep(0.02)
    while chan.recv_ready():
        chan.recv(65536)
print(f"[STREAMED] {sent} chars in {time.time()-t0:.1f}s")
chan.send("\x04")
time.sleep(3)
drain(chan, 2, echo=False)

verify = (f'ssh -o StrictHostKeyChecking=no 10.100.19.1 '
          f'"wc -c {PROD_B64}; base64 -d {PROD_B64} > {PROD_PATH} && rm -f {PROD_B64} '
          f'&& sha256sum {PROD_PATH}"\n')
chan.send(verify)
out = wait_for(chan, local_sha, timeout=40)
ok = local_sha in out
print(f"REMOTE_SHA_MATCH={ok}")
if not ok:
    print(out[-800:])
chan.close()
client.close()
sys.exit(0 if ok else 1)
