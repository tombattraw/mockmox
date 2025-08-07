import logging
import yaml
import pathlib
import shutil
import subprocess
import os
import uuid
import xml.etree.ElementTree as ET
import libvirt
import glob
from .common import get_editor


class VMTemplate:
    def __init__(self, name: str, vm_template_dir: pathlib.Path, connection: libvirt.virConnect, delete: bool = False):
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.path = vm_template_dir / name
        self.config_file = self.path / f"{self.name}_config.yaml"
        self.config = {}
        self.disk = self.path / f"{self.name}.qcow2"

        self.user_executable_dir = self.path / "user_executables"
        self.root_executable_dir = self.path / "root_executables"
        self.user_files_dir = self.path / "user_files"
        self.root_files_dir = self.path / "root_files"

        # SSH keys should be named by user
        self.ssh_key_dir = self.path / "ssh"
        self.ssh_keyfiles = self.ssh_key_dir.iterdir() if self.ssh_key_dir.exists() else []

        self.connection: libvirt.virConnect = connection

        # All state is maintained by the directory structure; having the path exist means that the template exists, even if it may be horribly corrupted
        # "delete" is used to skip checks and attempts to load configuration; otherwise, it would be impossible to delete a corrupted template through the object
        if self.path.exists() and not delete:
            if not self.disk.exists():
                raise FileNotFoundError(f"VM template {self.name} is missing its disk image.")
            if not self.config_file.exists():
                raise FileNotFoundError(f"VM template {self.name} is missing its config file.")

            try:
                self.config = yaml.safe_load(self.config_file.read_text())
            except yaml.YAMLError as E:
                raise yaml.YAMLError(f"VM template {self.name} has an invalid configuration file: {self.config_file}\n{E}")

        self.ip: str = ""
        self.ssh_port: int = self.config.get("ssh_port", 22)

        # Executables and files aren't mandatory
        self.user_executables = self.user_executable_dir.iterdir() if self.user_executable_dir.exists() else []
        self.root_executables = self.root_executable_dir.iterdir() if self.root_executable_dir.exists() else []
        self.user_files = self.user_files_dir.iterdir() if self.user_files_dir.exists() else []
        self.root_files = self.root_files_dir.iterdir() if self.root_files_dir.exists() else []


    def attach_iso(self, iso: pathlib.Path, connection: libvirt.virConnect):
        dom = connection.lookupByName(self.name)

        cdrom_xml = f"""
        <disk type='file' device='cdrom'>
          <driver name='qemu' type='raw'/>
          <source file='{iso.as_posix()}'/>
          <target dev='hdc' bus='ide'/>
          <readonly/>
        </disk>
        """

        # Attach CD-ROM
        dom.attachDeviceFlags(cdrom_xml, libvirt.VIR_DOMAIN_AFFECT_LIVE | libvirt.VIR_DOMAIN_AFFECT_CONFIG)


    def detach_iso(self, iso: pathlib.Path, connection: libvirt.virConnect):
        dom = connection.lookupByName(self.name)

        eject_xml = f"""
        <disk type='file' device='cdrom'>
          <driver name='qemu' type='raw'/>
          <source file='{iso.as_posix()}'/>
          <target dev='hdc' bus='ide'/>
          <readonly/>
        </disk>
        """

        dom.updateDeviceFlags(eject_xml, libvirt.VIR_DOMAIN_AFFECT_LIVE | libvirt.VIR_DOMAIN_AFFECT_CONFIG)


    def delete(self, group_dir, acknowledge):
        if not self.path.exists():
            raise FileNotFoundError(f"Cannot delete nonexistent template {self.name}")

        # First, check for existence in groups
        found_groups = []
        for group in group_dir.iterdir():
            group_vm_templates = (group / "vm_templates").iterdir()
            if self.name in group_vm_templates:
                found_groups.append(group.as_posix())

        if found_groups and not acknowledge:
            raise FileExistsError(f"The template exists in the following groups and must be deleted first: {'\n\t'.join(found_groups)}\nUse the \"--acknowledge\" flag to force deletion.")
        elif found_groups and acknowledge:
            for dir in [(group_dir / x / "vm_templates" / {self.name}) for x in found_groups]:
                shutil.rmtree(dir)

        shutil.rmtree(self.path)


    def create(self, disk_size: int,
               cpus: int,
               memory: int,
               graphics_type: str = 'spice',
               disk_type: str = 'virtio',
               net_interface_type: str = 'virtio',
               existing_disk_image: pathlib.Path = None,
               iso: pathlib.Path = None):

        if self.path.exists():
            raise FileExistsError(f"Cannot create existing template {self.name}")

        if not (iso or existing_disk_image):
            raise ValueError("An ISO or existing disk image is required when creating a VM")

        if iso:
            if not iso.exists():
                raise FileNotFoundError(f"ISO {iso} does not exist.")
        if existing_disk_image:
            if not existing_disk_image.exists():
                raise FileNotFoundError(f"Disk image {existing_disk_image} does not exist.")

        self.path.mkdir()
        self.ssh_key_dir.mkdir()
        self.user_executable_dir.mkdir()
        self.root_executable_dir.mkdir()
        self.user_files_dir.mkdir()
        self.root_files_dir.mkdir()

        if not existing_disk_image:
            subprocess.run(f"qemu-img create -f qcow2 {self.disk} {disk_size}".split(), capture_output=False, check=True)

        else:
            shutil.copy2(existing_disk_image, self.disk)

            domain = ET.Element('domain', type='kvm')
            ET.SubElement(domain, 'name').text = self.name
            ET.SubElement(domain, 'uuid').text = str(uuid.uuid4())
            ET.SubElement(domain, 'memory', unit='MiB').text = str(memory)
            ET.SubElement(domain, 'vcpu').text = str(cpus)

            devices = ET.SubElement(domain, 'devices')
            disk = ET.SubElement(devices, 'disk', type='file', device='disk')
            ET.SubElement(disk, 'source', file=self.disk.as_posix())
            ET.SubElement(disk, 'target', dev='vda', bus=disk_type)

            # Add network
            net = ET.SubElement(devices, 'interface', type='network')
            ET.SubElement(net, 'source', network='default')
            ET.SubElement(net, 'model', type=net_interface_type)

            # Add graphics (VNC)
            ET.SubElement(devices, 'graphics', type=graphics_type, port='-1', autoport='yes')

            xml_str = ET.tostring(domain, encoding='unicode')

            domain = self.connection.defineXML(xml_str)

            self.attach_iso(iso, self.connection)

            domain.create()
            input(f"VM template {self.name} booting. Connect with {graphics_type} to install, then, when done, press Enter here.")
            domain.shutdown()

            self.detach_iso(iso, self.connection)


    def _build_and_verify_path(self, user: str, file_type: str, file: pathlib.Path = None) -> pathlib.Path:
        # Used to resolve file names to the intended destination with appropriate error checking
        # Returns the validated path
        if user not in ["user", "root"]:
            raise ValueError(f"User {user} is invalid. Valid choices are \"user\" or \"root\"")
        if file_type not in ["executable", "file"]:
            raise ValueError(f"File type {file_type} is invalid. Valid choices are \"executable\" or \"file\"")

        # Can't check existence without breaking add_file logic; the rest is left to the top-level functions
        return (self.path / f"{user}_{file_type}s" / file.name) if file is not None else (self.path / f"{user}_{file_type}s")


    def add_file(self, source_file: pathlib.Path, user: str, file_type: str):
        if not source_file.exists():
            raise FileNotFoundError(f"File {source_file} does not exist.")

        path: pathlib.Path = self._build_and_verify_path(user, file_type, source_file)

        # Silently recreate missing parent directories.
        # The users shouldn't be getting their grubby fingers in my directory structure anyway...
        if not path.parent.exists():
            path.parent.mkdir()

        shutil.copy2(source_file, path)


    def remove_file(self, file: pathlib.Path, user: str, file_type: str):
        path: pathlib.Path = self._build_and_verify_path(user, file_type, file)

        if not path.exists():
            raise FileNotFoundError(f"File {path} does not exist.")

        path.unlink()


    def list_files(self, user: str, file_type: str) -> str:
        path: pathlib.Path = self._build_and_verify_path(user, file_type)

        if not path.exists():
            raise FileNotFoundError(f"The VM template {self.name} is corrupted and is missing {path}.")

        return '\n'.join([x.as_posix() for x in path.iterdir()])


    def edit(self):
        tmp_file = self.config_file.parent / f"{self.config_file.name}.tmp"

        shutil.copy2(self.config_file, tmp_file)

        subprocess.run([get_editor(), tmp_file])

        try:
            yaml.safe_load(tmp_file.read_text())
        except yaml.YAMLError as E:
            tmp_file.unlink()
            raise yaml.YAMLError(f"YAML error in config file; unable to apply\n{E}")

        tmp_file.replace(self.config_file)
        print(f"Configuration changes applied to {self.config_file}")


    def add_ssh_key(self, existing_key: pathlib.Path, user: str):
        if not existing_key.exists():
            raise FileNotFoundError(f"Key {existing_key} does not exist.")

        shutil.copy2(existing_key, self.ssh_key_dir / user)
        os.chmod(self.ssh_key_dir / user, 0o0600)


    def remove_ssh_key(self, user):
        if not user in [x.name for x in self.ssh_keyfiles]:
            raise ValueError(f"No key file could be found for {user}")

        (self.ssh_key_dir / user).unlink()


    def start(self, active_dir: pathlib.Path):
        # Start by getting new name
        taken_names = [pathlib.Path(x).name for x in glob.glob(f"{active_dir.as_posix()}/{self.name}_*")]
        for id in range(1000):
            if f"{self.name}_{id}" not in taken_names:
                break

        