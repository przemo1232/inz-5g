from fabric import Connection, Config
from fabric.transfer import Transfer
from invoke.watchers import Responder
from invoke.exceptions import UnexpectedExit
from time import sleep
from func_timeout import func_timeout
from func_timeout.exceptions import FunctionTimedOut
import socket
from config import net_xml

def setup():
    file = open('password.txt', 'r', encoding='utf-8')
    password = file.read()
    file.close()
    config = Config(overrides={'sudo': {'password': password}})
    aptWatch = Responder(pattern=r'Do you want to continue\?.*', response='y\n')
    c = Connection('user@10.147.20.99', config=config, connect_timeout=10)
    t = Transfer(c)
    c.open()

    # initial setup
    c.sudo('hwclock --hctosys') # sets the vm's time to now if it's wrong
    print('init')
    c.sudo('apt-get update')
    print('update')
    sleep(1) # avoids problems with locks
    c.sudo('apt-get install libvirt-daemon libvirt-clients libvirt-daemon-system qemu-kvm libvirt-clients docker.io python3-pip make gcc g++ lksctp-tools iproute2 libsctp-dev nfs-kernel-server python3.8-venv', watchers=[aptWatch])
    print('install')

    # installing docker
    groups = c.run('cat /etc/group | grep docker')
    if not groups.tail('stdout'):
        c.sudo('groupadd docker')
    c.sudo('apt-get update')
    c.sudo('usermod -aG docker user')
    print('update2')
    try:
        func_timeout(1, lambda c: c.sudo('reboot'), args=[c])
    except (FunctionTimedOut, UnexpectedExit):
        pass
    print('rebooting', end='')
    rebooted = False
    while not rebooted:
        try:
            sleep(10)
            c.close()
            c.open()
            print('\nreconnected')
            rebooted = True
        except (socket.timeout):
            print('.', end='')
    try:
        c.run('docker run hello-world')
    except Exception as e:
        print(f"Failed to install Docker, reason: {e}")
        return
    
    # setting up libvirt
    c.run('git clone https://github.com/KedArch/SOSKR5G')
    net_xml.upload(t, 'SOSKR5G/test/net.xml')
    with c.cd('SOSKR5G/test'):
        try:
            c.run('bash net.sh')
        except UnexpectedExit:
            pass

setup()