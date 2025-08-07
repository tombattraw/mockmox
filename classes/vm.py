from vm_template import VMTemplate
import libvirt
import pathlib

class VM(VMTemplate):
    def __init__(self, id: int, name: str, vm_template_dir: pathlib.Path, connection: libvirt.virConnect):
        super().__init__(name, vm_template_dir, connection)
        self.domain = f"{self.name}_{id}"


    def get_IP(self, instance_id: str):
        domain = self.connection.lookupByName(instance_id)

        ifaces = domain.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
        ips = []
        for iface_name, val in ifaces.items():
            if val['addrs']:
                for addr in val['addrs']:
                    ips.append(addr['addr'])

        return ips

    def stop(self):
        pass

    def suspend(self):
        pass

    def resume(self):
        pass

    def snapshot(self):
        pass

    def rollback(self):
        pass