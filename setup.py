from fabric import Connection, Config
from fabric.transfer import Transfer
from invoke.watchers import Responder
from invoke.exceptions import UnexpectedExit
from time import sleep
from func_timeout import func_timeout
from func_timeout.exceptions import FunctionTimedOut
from paramiko.ssh_exception import NoValidConnectionsError
import socket
from config import net_xml
import configparser
import re
from netaddr import IPAddress
import yaml

class SetupFail(BaseException):
    def __init__(self, message) -> None:
        self.message = message
        super().__init__(self.message)

def setup():
    ip_addr = config_parser.get('remote_pc', 'ip_addr')
    username = config_parser.get('remote_pc', 'username')
    password_file = config_parser.get('remote_pc', 'password_file')
    file = open(password_file, 'r', encoding='utf-8')
    password = file.read()
    file.close()
    config = Config(overrides={'sudo': {'password': password}})
    apt_watch = Responder(pattern=r'Do you want to continue\?.*', response='y\n')
    c = Connection(f'{username}@{ip_addr}', config=config, connect_timeout=10)
    t = Transfer(c)
    c.open()

    # initial setup
    c.sudo('hwclock --hctosys') # sets the vm's time to now if it's wrong
    c.sudo('apt-get update')
    sleep(1) # avoids problems with locks
    c.sudo('apt-get install libvirt-daemon libvirt-clients libvirt-daemon-system qemu-kvm libvirt-clients docker.io python3-pip make gcc g++ lksctp-tools iproute2 libsctp-dev nfs-kernel-server python3.8-venv genisoimage', watchers=[apt_watch])
    # installing docker
    setup_docker(c)
    # setting up libvirt
    c.run('git clone https://github.com/KedArch/SOSKR5G')
    net_xml.upload(t, 'net.xml')
    c.sudo('virsh net-define net.xml')
    c.sudo('virsh net-autostart internal')
    c.sudo('virsh net-start internal')
    c.run('rm net.xml')
    # building and uploading docker images
    upload_docker_images(c)
    create_virtual_machines(c)
    virsh_internal_network = config_parser.get('network', 'virsh_internal_network')
    network_mask = config_parser.get('network', 'network_mask')
    mask = IPAddress(network_mask).netmask_bits()
    c.sudo(f'echo "/srv/nfs    	{virsh_internal_network}/{mask}(rw,sync,no_subtree_check)" > tempexports')
    c.sudo('mv tempexports /etc/exports')
    c.sudo('mkdir --parents /srv/nfs/mongo')
    c.sudo('systemctl restart nfs-kernel-server')
    install_kubespray(c)
    deploy_pods(c)
    print('complete')


def setup_docker(c: Connection):
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
        except (socket.timeout, NoValidConnectionsError):
            print('.', end='')
    try:
        c.run('docker run hello-world')
    except Exception as e:
        raise SetupFail(f"Failed to install Docker, reason: {e}")


def upload_docker_images(c: Connection):
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
                file = c.run('cat Dockerfile')
                data = file.stdout
                for key, value in config_parser.items('docker_images'):
                    if value: data = re.sub(r'#ENV '+key.upper()+r'=.*', f'ENV {key.upper()}={value}', data)
                c.run(f'echo "{data}" > Dockerfile')

                if image != 'baza': c.run(f'sed -i s\'/FROM /FROM {virsh_internal_ip_address}:5000\\//\' Dockerfile')
                c.run(f'sed -i s\'/COPY --from=builder/COPY --from={virsh_internal_ip_address}:5000\\/builder/\' Dockerfile')

            c.run(f'docker build --tag {virsh_internal_ip_address}:5000/{image}:latest {image}')
            c.run(f'docker push {virsh_internal_ip_address}:5000/{image}:latest')
        c.run('mv builder/open5gs open5gs')
        c.run(f'docker build --tag {virsh_internal_ip_address}:5000/webui:latest -f open5gs/docker/webui/Dockerfile open5gs')
        c.run(f'docker push {virsh_internal_ip_address}:5000/webui:latest')


def create_virtual_machines(c: Connection):
    ssh_watch = Responder(pattern=r'Enter.*', response='\n')
    c.run('ssh-keygen', watchers=[ssh_watch])
    c.run('cp .ssh/id_rsa.pub SOSKR5G/test/pubkeys')
    master_nodes = int(config_parser.get('kubernetes', 'master_nodes'))
    worker_nodes = int(config_parser.get('kubernetes', 'worker_nodes'))
    dhcp_start = config_parser.get('network', 'dhcp_start').split('.')
    c.run(f"sed -i s'/192\.168\.39/{'.'.join(dhcp_start[0:3])}/' SOSKR5G/test/create_vm.sh")

    while True:
        for number in range(master_nodes):
            c.sudo(f'bash SOSKR5G/test/create_vm.sh master-{str(number)} {str(int(dhcp_start[3])+number)} 10G')
        for number in range(worker_nodes):
            c.sudo(f'bash SOSKR5G/test/create_vm.sh worker-{str(number)} {str(int(dhcp_start[3])+number+master_nodes)} 15G')
        sleep(5)
        output = c.sudo('virsh list')
        if output.stdout.find('paused') != -1:
            print('some machines are paused, retrying')
            for number in range(master_nodes):
                c.sudo(f'bash SOSKR5G/test/delete_vm.sh master-{str(number)}')
            for number in range(worker_nodes):
                c.sudo(f'bash SOSKR5G/test/delete_vm.sh worker-{str(number)}')
        else:
            return


def install_kubespray(c: Connection):
    c.run('git clone https://github.com/KedArch/SOSKR5G-kubespray')
    virsh_internal_ip_address = config_parser.get('network', 'virsh_internal_ip_address')
    master_nodes = int(config_parser.get('kubernetes', 'master_nodes'))
    worker_nodes = int(config_parser.get('kubernetes', 'worker_nodes'))
    dhcp_start = config_parser.get('network', 'dhcp_start').split('.')
    
    ini_data = {'all': '', 'kube_control_plane': '', 'etcd': '', 'kube_node': '', 'calico_rr': '\n', 'k8s_cluster:children': 'kube_control_plane\nkube_node\ncalico_rr'}
    yaml_data = {'all': {'hosts': {}, 'children': {'kube_control_plane': {'hosts': {}}, 'kube_node': {'hosts': {}}, 'etcd': {'hosts': {}}, 'k8s_cluster': {'children': {'kube_control_plane': None, 'kube_node': None}}, 'calico_rr': {'hosts': {}}}}}
    for number in range(master_nodes):
        ipaddr = f'{dhcp_start[0]}.{dhcp_start[1]}.{dhcp_start[2]}.{str(int(dhcp_start[3])+number)}'
        yaml_data['all']['hosts'].update({f'master-{number}': {'ansible_host': ipaddr, 'ip': ipaddr, 'access_ip': ipaddr}})
        yaml_data['all']['children']['kube_control_plane']['hosts'].update({f'master-{number}': None})
        yaml_data['all']['children']['etcd']['hosts'].update({f'master-{number}': None})
        ini_data['all'] += f'master-{number} ansible_host={ipaddr} ip={ipaddr} etcd_member_name=master-{number}\n'
        ini_data['kube_control_plane'] += f'master-{number}\n'
        ini_data['etcd'] += f'master-{number}\n'

    for number in range(worker_nodes):
        ipaddr = f'{dhcp_start[0]}.{dhcp_start[1]}.{dhcp_start[2]}.{str(int(dhcp_start[3])+number+master_nodes)}'
        yaml_data['all']['hosts'].update({f'worker-{number}': {'ansible_host': ipaddr, 'ip': ipaddr, 'access_ip': ipaddr}})
        yaml_data['all']['children']['kube_node']['hosts'].update({f'worker-{number}': None})
        ini_data['all'] += f'worker-{number} ansible_host={ipaddr} ip={ipaddr}\n'
        ini_data['kube_node'] += f'worker-{number}\n'

    yaml_str = yaml.safe_dump(yaml_data)
    ini_str = ''
    containerd_str = f'containerd_insecure_registries:\n  "{virsh_internal_ip_address}:5000": "http://{virsh_internal_ip_address}:5000"'
    for key, value in ini_data.items():
        ini_str += f'[{key}]\n{value}\n'
    venv_dir='kubespray-venv'
    kubespray_dir='SOSKR5G-kubespray'
    ansible_version='2.12'
    with c.cd('SOSKR5G-kubespray/inventory/5gcore/'):
        c.run(f'echo "{yaml_str}" > hosts.yaml')
        c.run(f'echo "{ini_str}" > inventory.ini')
        c.run(f'echo "{containerd_str}" > group_vars/all/containerd.yml')
    c.run(f'python3 -m venv {venv_dir}')
    with c.cd(kubespray_dir):
        with c.prefix(f'source ../{venv_dir}/bin/activate'):
            c.run(f'pip install -U -r requirements-{ansible_version}.txt')
            counter = 0
            step = 5
            while True:
                counter += step
                try:
                    sleep(step)
                    c.run('ansible-playbook -i inventory/5gcore/hosts.yaml cluster.yml -b -v --private-key=~/.ssh/id_rsa -u user')
                    break
                except UnexpectedExit:
                    if counter < 60:
                        print('waiting for machines to boot up')
                        continue
                    print('machines took too long to boot up')
                    raise


def deploy_pods(c: Connection):
    replicas = config_parser.get('kubernetes', 'replicas')
    virsh_internal_ip_address = config_parser.get('network', 'virsh_internal_ip_address')
    scalable_pods = ['amf.yaml', 'ausf.yaml', 'bsf.yaml', 'labelednrf.yaml', 'nrfedsmf.yaml', 'nrfedupf.yaml', 'nssf.yaml', 'pcf.yaml', 'scp.yaml', 'udm.yaml', 'udr.yaml']
    fixed_pods = ['mongo-add-admin.yaml', 'mongo-add-subscribers.yaml', 'mongo.yaml', 'pv.yaml', 'webui.yaml']
    kubectl = '$HOME/SOSKR5G-kubespray/inventory/5gcore/artifacts/kubectl.sh'
    c.run(f"sed -i s'/\/data\/db/\/db/' SOSKR5G/Kubernetes/mongo.yaml")
    c.run(f"sed -i s'/server: 192.168.39.1/server: {virsh_internal_ip_address}/' SOSKR5G/Kubernetes/pv.yaml")
    for pod in scalable_pods:
        print(pod)
        c.run(f"sed -i s'/replicas: 1/replicas: {replicas}/' SOSKR5G/Kubernetes/{pod}")
        c.run(f"sed -i s'/image: 192.168.39.1/image: {virsh_internal_ip_address}/' SOSKR5G/Kubernetes/{pod}")
        c.run(f"sed -i s'/\"192.168.39.1\" # logger server address/\"{virsh_internal_ip_address}\" # logger server address/' SOSKR5G/Kubernetes/{pod}")
        with c.cd('SOSKR5G/Kubernetes/'):
            c.run(f'{kubectl} create -f {pod}')
    for pod in fixed_pods:
        c.run(f"sed -i s'/image: 192.168.39.1/image: {virsh_internal_ip_address}/' SOSKR5G/Kubernetes/{pod}")
        c.run(f"sed -i s'/\"192.168.39.1\" # logger server address/\"{virsh_internal_ip_address}\" # logger server address/' SOSKR5G/Kubernetes/{pod}")
        with c.cd('SOSKR5G/Kubernetes/'):
            c.run(f'{kubectl} create -f {pod}')

config_parser = configparser.ConfigParser()
configFilePath = 'config/config.cfg'
config_parser.read(configFilePath)
setup()
