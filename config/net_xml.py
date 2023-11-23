from fabric.transfer import Transfer
import configparser
from config.templates import net_xml_template
import os

def upload(t: Transfer, path: str):
    config_parser = configparser.ConfigParser()
    configFilePath = 'config/config.cfg'
    config_parser.read(configFilePath)
    virsh_internal_ip_address = config_parser.get('network', 'virsh_internal_ip_address')
    network_mask = config_parser.get('network', 'network_mask')
    dhcp_start = config_parser.get('network', 'dhcp_start')
    dhcp_end = config_parser.get('network', 'dhcp_end')
    net_xml = net_xml_template
    net_xml = net_xml.replace('virsh_internal_ip_address', virsh_internal_ip_address)
    net_xml = net_xml.replace('network_mask', network_mask)
    net_xml = net_xml.replace('dhcp_start', dhcp_start)
    net_xml = net_xml.replace('dhcp_end', dhcp_end)
    file = open('config/temp.xml', 'w', encoding='utf-8')
    file.write(net_xml)
    file.close()
    t.put('config/temp.xml', path)
    os.remove('config/temp.xml')