import os
import subprocess
import argparse
import pathlib
import yaml
import sys
import shutil
import subprocess


BASE_DIR = pathlib.Path("/opt/mockmox")
GROUP_DIR = BASE_DIR / "groups"
VM_DIR = BASE_DIR / "vms"
ACTIVE_DIR = BASE_DIR / "active"
SUSPENDED_DIR = BASE_DIR / "suspended"

SCRIPT_LOCATION = pathlib.Path("/bin/mockmox")

VM_DEFAULT_DISK_SIZE = 64   # given in GB
VM_DEFAULT_CPUS = 4
VM_DEFAULT_MEMORY = 8192    # given in MB


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
    vm_create.add_argument("--existing-qcow2", help="Use existing disk image")
    vm_create.add_argument("-i", "--iso", help="Path to installation ISO")

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