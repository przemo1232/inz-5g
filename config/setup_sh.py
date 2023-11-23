from fabric.transfer import Transfer
import configparser
from config.templates import setup_sh_template
import os

def upload(t: Transfer, path: str):
    config_parser = configparser.ConfigParser()
    configFilePath = 'config/config.cfg'
    config_parser.read(configFilePath)
    virsh_internal_ip_address = config_parser.get('network', 'virsh_internal_ip_address')
    virsh_internal_ip_address = config_parser.get('network', 'virsh_internal_ip_address')
    setup_sh = setup_sh_template
    setup_sh = setup_sh.replace('virsh_internal_ip_address', virsh_internal_ip_address)
    file = open('config/temp.sh', 'w', encoding='utf-8')
    file.write(setup_sh)
    file.close()
    t.put('config/temp.sh', path)
    os.remove('config/temp.sh')