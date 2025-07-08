import os
import argparse
import pathlib
import libvirt
from virtinst import cli
import yaml
import sys
import shutil
import subprocess
import logging


BASE_DIR = pathlib.Path("/opt/mockmox")
CONFIG_FILE = pathlib.Path("/etc/mockmox/config.yaml")

GROUP_DIR = BASE_DIR / "groups"
VM_TEMPLATE_DIR = BASE_DIR / "vms"
ACTIVE_DIR = BASE_DIR / "active"
SUSPENDED_DIR = BASE_DIR / "suspended"
DEFAULT_DIR = BASE_DIR / "defaults"

SCRIPT_LOCATION = pathlib.Path("/bin/mockmox")

VM_DEFAULT_DISK_SIZE = 64   # given in GB
VM_DEFAULT_CPUS = 4
VM_DEFAULT_MEMORY = 8192    # given in MB


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(message)s"
)


class VMTemplate:
    def __init__(self, name: str, action: str,
                 os_variant: str = '',
                 disk_size: int = VM_DEFAULT_DISK_SIZE,
                 cpus: int = VM_DEFAULT_CPUS,
                 memory: int = VM_DEFAULT_MEMORY,
                 existing_disk_image: pathlib.Path = None,
                 iso: pathlib.Path = None):
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.path = VM_TEMPLATE_DIR / name
        self.disk = self.path / f"{self.name}.qcow2"
        self.user_script_dir = self.path / "user_scripts"
        self.root_script_dir = self.path / "root_scripts"
        self.files_dir = self.path / "files"
        self.config = self.path / f"{self.name}_config.yaml"

        match action:
            case "load":
                if not (self.path.exists() and self.disk.exists()):
                    raise FileNotFoundError(f"VM template {self.name} is missing critical components and cannot start. Repair or delete and recreate the template.")

                # Scripts and files aren't mandatory
                self.user_scripts = self.user_script_dir.iterdir() if self.user_script_dir.exists() else []
                self.root_scripts = self.root_script_dir.iterdir() if self.root_script_dir.exists() else []
                self.files = self.files_dir.iterdir() if self.files_dir.exists() else []

            case "delete":
                if not self.path.exists():
                    raise FileNotFoundError(f"VM template {self.name} does not exist.")

                shutil.rmtree(self.path)

            case 'create':
                if self.path.exists():
                    raise FileExistsError(f"VM template {self.name} already exists. Delete it first to recreate it.")

                if not (iso or existing_disk_image):
                    raise ValueError("An ISO or existing disk image is required when creating a VM")

                if iso:
                    if not iso.exists():
                        raise FileNotFoundError(f"ISO {iso} does not exist.")
                if existing_disk_image:
                    if not existing_disk_image.exists():
                        raise FileNotFoundError(f"Disk iamge {existing_disk_image} does not exist.")

                self.path.mkdir()
                self.user_script_dir.mkdir()
                self.root_script_dir.mkdir()
                self.files_dir.mkdir()

                if not existing_disk_image:
                    subprocess.run(f"qemu-img create -f qcow2 {self.disk} {disk_size}", capture_output=False)
                    subprocess.run(f"virt-install --name {name} --vcpus {cpus} --memory {memory} --os-variant {os_variant} --controller=scsi,model=virtio-scsi --disk path={self.disk},bus=scsi --cdrom={iso} --noreboot")
                else:
                    shutil.copyfile(existing_disk_image, self.disk)






class Group:
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.vm_templates = []
        self.path = GROUP_DIR / name

        if self.path.exists():
            self.vm_templates = GROUP_DIR




def load_state():
    pass




def get_editor():
    editor = os.environ.get('EDITOR')
    if editor: return editor
    editor = os.environ.get('VISUAL')
    if editor: return editor

    for fallback in ['nano', 'vim', 'vi']:
        if shutil.which(fallback):
            return fallback
    raise RuntimeError("No editor found. Set the EDITOR environment variable.")


def edit_resource(resource_type, name):
    config_path = BASE_DIR / resource_type / name / "config.yaml"
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"No such {resource_type}: {name}")

    tmp_file = config_path.parent / f"{config_path.name}.tmp"
    shutil.copyfile(config_path, tmp_file)
    subprocess.run([get_editor(), tmp_file], check=True)

    try:
        yaml.safe_load(tmp_file.read_text())
    except yaml.YAMLError as E:
        print(f"YAML error in config file; unable to apply\n{E}")
        tmp_file.unlink()
        sys.exit(1)

    tmp_file.replace(config_path)
    print(f"Configuration changes applied to {name} in {config_path}")





if __name__ == "__main__":
    arg_def = argparse.ArgumentParser(
        prog="mockmox.py",
        description="VM Management Framework")

    if CONFIG_FILE.exists():
        config = yaml.safe_load(CONFIG_FILE.read_text())
    else:
        config = {}

    arg_def.add_argument("-l", "--libvirtd",
                         default=config.get("libvirtd") if config.get("libvirtd") else "qemu:///system",
                         required=False,
                         help=f"The libvirtd hypervisor to connect to. Default is in the config file \"{CONFIG_FILE}\"")

    # Groups are logical collections of VMs, down to just one
    # VMs are only used as templates; they must be added to groups to start
    # Groups are started, suspended, and stopped together

    sp = arg_def.add_subparsers(dest="object")

    # ===== VMs =====
    vm_sp = sp.add_parser("vm").add_subparsers(dest="action")

    vm_create = vm_sp.add_parser("create")
    vm_create.add_argument("name", help="Name of VM template")
    vm_create.add_argument("--os-variant", required=True,
                           help="See valid choices with 'virt-install --os-variant list'")
    vm_create.add_argument("-s", "--size", type=int, default=VM_DEFAULT_DISK_SIZE,
                           help="Virtual disk size in GB (default: %(default)s)")
    vm_create.add_argument("-c", "--cpus", type=int, default=VM_DEFAULT_CPUS,
                           help="Number of CPUs (default: %(default)s)")
    vm_create.add_argument("-m", "--memory", type=int, default=VM_DEFAULT_MEMORY,
                           help="Memory size in MB (default: %(default)s)")
    vm_create.add_argument("--existing-qcow2", help="Use existing disk image", type=pathlib.Path, required=False)
    vm_create.add_argument("-i", "--iso", help="Path to installation ISO", type=pathlib.Path, required=False)

    vm_delete = vm_sp.add_parser("delete")
    vm_delete.add_argument("name", help="Name of VM template to delete")

    vm_edit = vm_sp.add_parser("edit", help="Edit a VM's configuration")
    vm_edit.add_argument("name", help="Name of VM to edit")

    # ===== Groups =====
    group_sp = sp.add_parser("group").add_subparsers(dest="action")

    group_create = group_sp.add_parser("create")
    group_create.add_argument("name", help="Name of group")

    group_delete = group_sp.add_parser("delete")
    group_delete.add_argument("name", help="Name of group to delete")

    group_add = group_sp.add_parser("add")
    group_add.add_argument("vm_name", help="VM template to add to group")
    group_add.add_argument("group_name", help="Group to add VM to")

    group_remove = group_sp.add_parser("remove")
    group_remove.add_argument("vm_name", help="VM template to remove from group")
    group_remove.add_argument("group_name", help="Group to remove VM from")

    group_start = group_sp.add_parser("start")
    group_start.add_argument("name", help="Group to start")

    group_stop = group_sp.add_parser("stop")
    group_stop.add_argument("name", help="Group to stop")

    group_suspend = group_sp.add_parser("suspend")
    group_suspend.add_argument("name", help="Group to suspend")

    group_resume = group_sp.add_parser("resume")
    group_resume.add_argument("name", help="Group to resume")

    group_edit = group_sp.add_parser("edit", help="Edit a group's configuration")
    group_edit.add_argument("name", help="Name of group to edit")

    # ===== List =====
    list_args = sp.add_parser("list")
    list_args.add_argument("type", choices=["active", "suspended", "vms", "groups"],
                           help="Type of resources to list")

    # ===== Snapshot =====
    snapshot_args = sp.add_parser("snapshot")
    snapshot_args.add_argument("name", help="Name of snapshot")
    snapshot_args.add_argument("-g", "--group", help="Snapshot a group")
    snapshot_args.add_argument("-v", "--vm", help="Snapshot a single VM")
    snapshot_args.add_argument("--live", action="store_true", help="Take live snapshot")

    # ===== Enforce subcommand =====
    if len(sys.argv) == 1:
        arg_def.print_help(sys.stderr)
        sys.exit(1)

    args = arg_def.parse_args()

    import pprint; pprint.pprint(args)