net_xml_template = "<network>\n\
  <name>internal</name>\n\
  <bridge name='virbr1' stp='on' delay='0'/>\n\
  <ip address='virsh_internal_ip_address' netmask='network_mask'>\n\
    <dhcp>\n\
      <range start='dhcp_start' end='dhcp_end'/>\n\
    </dhcp>\n\
  </ip>\n\
</network>\n"