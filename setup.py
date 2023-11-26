from fabric import Connection, Config
from fabric.transfer import Transfer
from invoke.watchers import Responder
from invoke.exceptions import UnexpectedExit
from time import sleep
from func_timeout import func_timeout
from func_timeout.exceptions import FunctionTimedOut
import socket
from config import net_xml
import configparser

def setup():
    file = open('../password.txt', 'r', encoding='utf-8')
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
    net_xml.upload(t, 'net.xml')
    c.sudo('virsh net-define net.xml')
    c.sudo('virsh net-autostart internal')
    c.sudo('virsh net-start internal')
    c.run('rm net.xml')
    setup_docker(c)
    print('complete')


def setup_docker(c: Connection):
    config_parser = configparser.ConfigParser()
    configFilePath = 'config/config.cfg'
    config_parser.read(configFilePath)
    virsh_internal_ip_address = config_parser.get('network', 'virsh_internal_ip_address')
    c.run('echo {\\"insecure-registries\\":[\\"'+virsh_internal_ip_address+':5000\\"]} >> docker_daemon.json')
    c.sudo('mv docker_daemon.json /etc/docker/daemon.json')
    c.sudo('service docker restart')
    c.run('docker run -d -p 5000:5000 --name open5gs registry:latest')
    with c.cd('SOSKR5G/Docker/'):
        with c.cd('builder/'):
            c.run('git clone https://github.com/KedArch/open5gs')
            with c.cd('open5gs/'):
                c.run('git checkout v2.6.0')
        for image in 'baza builder amf ausf bsf nrf nssf pcf scp smf udm udr upf'.split():
            with c.cd(f'{image}/'):
                if image != 'baza': c.run(f'sed -i s\'/FROM /FROM {virsh_internal_ip_address}:5000\\//\' Dockerfile')
                c.run(f'sed -i s\'/COPY --from=builder/COPY --from={virsh_internal_ip_address}:5000\\/builder/\' Dockerfile')
            print(image)
            c.run(f'docker build --tag {virsh_internal_ip_address}:5000/{image}:latest {image}')
            c.run(f'docker push {virsh_internal_ip_address}:5000/{image}:latest')
        c.run('mv builder/open5gs open5gs')
        # c.run(f'docker build --tag {virsh_internal_ip_address}:5000/webui:latest -f open5gs/docker/webui/Dockerfile open5gs')
        # c.run(f'docker push {virsh_internal_ip_address}:5000/webui:latest')

setup()