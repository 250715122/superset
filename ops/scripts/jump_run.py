"""Run a prod-side command on 10.100.19.1 via JumpServer -> StarRocks-01.

Usage: python jump_run.py <cmdfile>
<cmdfile> contains ONE shell command (may span; will be joined by ' ')
to be executed as: ssh 10.100.19.1 "<cmd>"
The command MUST NOT contain unescaped double quotes; use single quotes.
Output between markers BEGIN_PROD_OUTPUT / END_PROD_OUTPUT is the result.
"""
import sys
import time
import paramiko

JHOST = "jumpserver.poweroak.ltd"
JPORT = 2222
JUSER = "guote@poweroak.net"
JPASS = "qq250715122"

with open(sys.argv[1], "r", encoding="utf-8") as f:
    cmd = f.read().strip()

wait_secs = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0


def drain(chan, seconds):
    end = time.time() + seconds
    buf = b""
    while time.time() < end:
        while chan.recv_ready():
            buf += chan.recv(65536)
        time.sleep(0.1)
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


client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(JHOST, port=JPORT, username=JUSER, password=JPASS,
               look_for_keys=False, allow_agent=False, timeout=20)
chan = client.invoke_shell(width=220, height=50)
drain(chan, 3)
chan.send("/Flink\n")
time.sleep(3)
drain(chan, 1)
chan.send("1\n")
r = wait_for(chan, "StarRocks-01:~$", timeout=25)
sys.stdout.write(r)
time.sleep(1)
drain(chan, 1)

# split markers with quotes so the command echo never matches the sentinel
full = f'ssh -o StrictHostKeyChecking=no 10.100.19.1 "echo BE""GIN_MARK; {cmd}; echo EN""D_MARK_RC=$?"\n'
print(f"\n[RUN] {full.strip()}\n")
chan.send(full)
r = wait_for(chan, "END_MARK_RC=", timeout=wait_secs)
sys.stdout.write(r)
drain(chan, 2)
chan.close()
client.close()
