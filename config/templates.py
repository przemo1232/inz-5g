net_xml_template = "<network>\n\
  <name>internal</name>\n\
  <bridge name='virbr1' stp='on' delay='0'/>\n\
  <ip address='virsh_internal_ip_address' netmask='network_mask'>\n\
    <dhcp>\n\
      <range start='dhcp_start' end='dhcp_end'/>\n\
    </dhcp>\n\
  </ip>\n\
</network>\n"

setup_sh_template = "#!/usr/bin/env bash\n\
git clone https://github.com/KedArch/open5gs\n\
git -C open5gs checkout v2.6.0\n\
for I in baza builder amf ausf bsf nrf nssf pcf scp smf udm udr upf; do\n\
  docker build --tag virsh_internal_ip_address:5000/$I:${1:-latest} $I\n\
  docker image push virsh_internal_ip_address:5000/$I:${1:-latest}\n\
done\n\
docker build --tag virsh_internal_ip_address:5000/webui:${1:-latest} -f open5gs/docker/webui/Dockerfile open5gs\n\
docker image push virsh_internal_ip_address:5000/webui:${1:-latest}\n"