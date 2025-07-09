import os
import argparse
import pathlib
#import libvirt
import yaml
import sys
import shutil
import subprocess
import logging


BASE_DIR = pathlib.Path("/opt/mockmox")
CONFIG_FILE = pathlib.Path("/etc/mockmox/config.yaml")

GROUP_DIR = BASE_DIR / "groups"
VM_TEMPLATE_DIR = BASE_DIR / "vms"
INSTANCE_DIR = BASE_DIR / "instances"
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
    def __init__(self, name: str, delete: bool = False):
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.path = VM_TEMPLATE_DIR / name
        self.config_file = self.path / f"{self.name}_config.yaml"
        self.config = {}
        self.disk = self.path / f"{self.name}.qcow2"

        self.user_script_dir = self.path / "user_scripts"
        self.root_script_dir = self.path / "root_scripts"
        self.user_files_dir = self.path / "user_files"
        self.root_files_dir = self.path / "root_files"

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

        # Scripts and files aren't mandatory
        self.user_scripts = self.user_script_dir.iterdir() if self.user_script_dir.exists() else []
        self.root_scripts = self.root_script_dir.iterdir() if self.root_script_dir.exists() else []
        self.user_files = self.user_files_dir.iterdir() if self.user_files_dir.exists() else []
        self.root_files = self.root_files_dir.iterdir() if self.root_files_dir.exists() else []


    def delete(self):
        if not self.path.exists():
            raise FileNotFoundError(f"Cannot delete nonexistent template {self.name}")
        shutil.rmtree(self.path)


    def create(self, os_variant: str = '',
                 disk_size: int = VM_DEFAULT_DISK_SIZE,
                 cpus: int = VM_DEFAULT_CPUS,
                 memory: int = VM_DEFAULT_MEMORY,
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
        self.user_script_dir.mkdir()
        self.root_script_dir.mkdir()
        self.user_files_dir.mkdir()
        self.root_files_dir.mkdir()

        if not existing_disk_image:
            subprocess.run(f"qemu-img create -f qcow2 {self.disk} {disk_size}".split(), capture_output=False, check=True)
            cmd = f"virt-install --name {self.name} --vcpus {cpus} --memory {memory} --os-variant {os_variant} --controller=scsi,model=virtio-scsi --disk path={self.disk},bus=scsi --cdrom={iso} --noreboot"
            try:
                subprocess.run(cmd.split(), check=True)
            except subprocess.CalledProcessError as E:
                shutil.rmtree(self.path)
                raise subprocess.CalledProcessError(returncode=1, cmd=cmd.split(), output=f"VM template creation {self.name} failed.\n{E}")
        else:
            shutil.copyfile(existing_disk_image, self.disk)
            cmd = f"virt-install --name {self.name} --vcpus {cpus} --memory {memory} --os-variant {os_variant} --controller=scsi,model=virtio-scsi --disk path={existing_disk_image},bus=scsi --import --noautoconsole --noreboot"
            try:
                subprocess.run(cmd.split(), check=True)
            except subprocess.CalledProcessError as E:
                shutil.rmtree(self.path)
                raise subprocess.CalledProcessError(returncode=1, cmd=cmd.split(), output=f"VM template creation {self.name} failed.\n{E}")


    def _build_and_verify_path(self, user: str, file_type: str, file: pathlib.Path = None) -> pathlib.Path:
        # Used to resolve file names to the intended destination with appropriate error checking
        # Returns the validated path
        if user not in ["user", "root"]:
            raise ValueError(f"User {user} is invalid. Valid choices are \"user\" or \"root\"")
        if file_type not in ["script", "file"]:
            raise ValueError(f"File type {file_type} is invalid. Valid choices are \"script\" or \"file\"")

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

        shutil.copyfile(source_file, path)


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


    def start(self):
        pass # to implement

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


class Group:
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.vm_templates = []
        self.path = GROUP_DIR / name
        self.snapshot_dir = self.path / "snapshots"
        self.vm_template_dir = self.path / "vm_templates"






    def delete(self):
        if not self.path.exists():
            raise AttributeError(f"Cannot delete nonexistent template {self.name}")
        shutil.rmtree(self.path)


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
    vm_sp = sp.add_parser("vm").add_subparsers(dest="action", metavar="vm_template", help="VM template management actions", required=True)

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
    group_sp = sp.add_parser("group").add_subparsers(dest="action", help="Group management actions", required=True)

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

    group_start = group_sp.add_parser("instantiate")
    group_start.add_argument("name", help="Group to start. Becomes an \"instance\"")

    group_edit = group_sp.add_parser("edit", help="Edit a group's configuration")
    group_edit.add_argument("name", help="Name of group to edit")


    # ===== List =====
    list_args = sp.add_parser("list")
    list_args.add_argument("type", choices=["instances", "suspended", "vm_templates", "groups"],
                           help="Type of resources to list")

    # ==== Instance ====
    instance_sp = sp.add_parser("instance", help="Manage running instances")
    instance_action_sp = instance_sp.add_subparsers(dest="action", help="Action to perform on instances", required=True)

    instance_stop = instance_action_sp.add_parser("stop", help="Stop a running instance")
    instance_stop.add_argument("name", help="Name of the running instance to stop")
    instance_stop.add_argument("-v", "--vm", required=False, help="Individual VM to shut down")

    instance_suspend = instance_action_sp.add_parser("suspend", help="Suspend a running instance")
    instance_suspend.add_argument("name", help="Name of the running instance to suspend")
    instance_suspend.add_argument("-v", "--vm", required=False, help="Individual VM to suspend")

    instance_resume = instance_action_sp.add_parser("resume", help="Resume a suspended instance")
    instance_resume.add_argument("name", help="Name of the running instance to resume")
    instance_resume.add_argument("-v", "--vm", required=False, help="Individual VM to resume")

    instance_snapshot = instance_action_sp.add_parser("snapshot", help="Snapshot a running instance")
    instance_snapshot.add_argument("name", help="Name of the running instance to snapshot")
    instance_snapshot.add_argument("snapshot_name", help="Name of the snapshot")
    instance_snapshot.add_argument("-v", "--vm", required=False, help="Individual VM to snapshot")

    instance_ssh = instance_action_sp.add_parser("ssh", help="SSH into a VM within a running instance")
    instance_ssh.add_argument("instance_name", help="Name of the running instance")
    instance_ssh.add_argument("vm_name", help="Name of the VM in the instance to SSH into")


    # ===== Enforce subcommand =====
    if len(sys.argv) == 1:
        arg_def.print_help(sys.stderr)
        sys.exit(1)

    ABBREVIATIONS = {
        "i": "instance",
        "g": "group",
        "v": "vm",
        "l": "list",
        "s": "snapshot",
        "a": "add",
        "rm": "remove",
        "inst": "instantiate",
        "vt": "vm_templates"
    }

    # Replace abbreviated commands
    expanded_argv = [
        ABBREVIATIONS.get(arg, arg) for arg in sys.argv[1:]
    ]

    args = arg_def.parse_args(expanded_argv)

    import pprint; pprint.pprint(args)