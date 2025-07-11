import click
import pathlib
import shutil
import subprocess
import logging
import yaml

# Backend classes
from classes import VMTemplate, Group as BackendGroup, get_editor

# Definitions here used only for installation, except for CONFIG_FILE
# Later runs will load definitions from the config file

CONFIG_FILE = pathlib.Path("/etc/mockmox/config.yaml")
if CONFIG_FILE.exists():
    try:
        config = yaml.safe_load(CONFIG_FILE.read_text())
    except yaml.YAMLError as E:
        raise yaml.YAMLError(f"Config file {CONFIG_FILE} has invalid YAML syntax. Edit or reinstall to fix.\n{E}")
    except PermissionError as E:
        raise PermissionError(f"Config file {CONFIG_FILE} cannot be read. Add read permissions to fix.\n{E}")
else:
    config = {}

# If config has directories key with base_dir key, use that value. Else, use the final value
BASE_DIR = pathlib.Path(config.get("directories", {}).get("base_dir", "/opt/mockmox"))
GROUP_DIR = BASE_DIR / "groups"
VM_TEMPLATE_DIR = BASE_DIR / "vms"
INSTANCE_DIR = BASE_DIR / "instances"
SUSPENDED_DIR = BASE_DIR / "suspended"
DEFAULT_DIR = BASE_DIR / "defaults"

SCRIPT_LOCATION = pathlib.Path(config.get("directories", {}).get("base_dir", "/bin/mockmox"))

VM_DEFAULT_DISK_SIZE = config.get("defaults", {}).get("vm_disk_size", 64) # GB
VM_DEFAULT_CPUS = config.get("defaults", {}).get("vm_cpus", 4)
VM_DEFAULT_MEMORY = config.get("defaults", {}).get("vm_memory", 8192) # MB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(message)s"
)


@click.group()
@click.option('--libvirtd', default="qemu:///system", help="Libvirtd hypervisor connection string.")
@click.option('--config', type=click.Path(), default=CONFIG_FILE, help="Path to config file.")
@click.option('--verbose', is_flag=True, help="Enable verbose output.")
@click.pass_context
def cli(ctx, libvirtd, config, verbose):
    """Mockmox: VM and group management framework."""
    ctx.ensure_object(dict)
    ctx.obj['LIBVIRTD'] = libvirtd
    ctx.obj['CONFIG'] = config
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)


# ====================
# VM commands
# ====================
@cli.group()
def vm():
    """Manage VM templates."""


@vm.command()
@click.argument('name')
@click.option('--os-variant', required=True, help="See valid choices with 'virt-install --os-variant list'")
@click.option('-s', '--size', default=VM_DEFAULT_DISK_SIZE, help="Disk size in GB (default: %(default)s)")
@click.option('-c', '--cpus', default=VM_DEFAULT_CPUS, help="Number of CPUs (default: %(default)s)")
@click.option('-m', '--memory', default=VM_DEFAULT_MEMORY, help="Memory size in MB (default: %(default)s)")
@click.option('--existing-qcow2', type=click.Path(), help="Use existing disk image")
@click.option('-i', '--iso', type=click.Path(), help="Path to installation ISO")
def create(name, os_variant, size, cpus, memory, existing_qcow2, iso):
    """Create a new VM template."""
    vm = VMTemplate(name, VM_TEMPLATE_DIR)
    existing_disk = pathlib.Path(existing_qcow2) if existing_qcow2 else None
    iso_path = pathlib.Path(iso) if iso else None
    vm.create(os_variant, size, cpus, memory, existing_disk, iso_path)
    click.echo(f"VM '{name}' created.")


@vm.command()
@click.argument('name')
def delete(name):
    """Delete a VM template."""
    vm = VMTemplate(name, VM_TEMPLATE_DIR, delete=True)
    vm.delete()
    click.echo(f"Deleted VM '{name}'.")


@vm.command()
@click.argument('name')
def edit(name):
    """Edit a VM template's configuration."""
    vm = VMTemplate(name, VM_TEMPLATE_DIR)
    vm.edit()


@vm.command('list-files')
@click.argument('name')
@click.option('-u', '--user', type=click.Choice(['user', 'root']), required=True, help="List user or root files.")
@click.option('-t', '--type', type=click.Choice(['file', 'executable']), required=True, help="File or executable?")
def list_files(name, user, type):
    """List files/scripts owned by a VM template."""
    vm = VMTemplate(name, VM_TEMPLATE_DIR)
    files = vm.list_files(user, type)
    click.echo(files)


@vm.command('add-file')
@click.argument('name')
@click.argument('source_file', type=click.Path(exists=True))
@click.option('-u', '--user', type=click.Choice(['user', 'root']), required=True, help="Owner of the file.")
@click.option('-t', '--type', type=click.Choice(['file', 'executable']), required=True, help="File type.")
def add_file(name, source_file, user, type):
    """Add a file or executable to a VM template."""
    vm = VMTemplate(name, VM_TEMPLATE_DIR)
    vm.add_file(pathlib.Path(source_file), user, type)
    click.echo(f"Added {type} '{source_file}' to VM '{name}' as {user}.")


@vm.command('remove-file')
@click.argument('name')
@click.argument('source_file', type=click.Path())
@click.option('-u', '--user', type=click.Choice(['user', 'root']), required=True)
@click.option('-t', '--type', type=click.Choice(['file', 'executable']), required=True)
def remove_file(name, source_file, user, type):
    """Remove a file or executable from a VM template."""
    vm = VMTemplate(name, VM_TEMPLATE_DIR)
    vm.remove_file(pathlib.Path(source_file), user, type)
    click.echo(f"Removed {type} '{source_file}' from VM '{name}' as {user}.")


# ====================
# Group commands
# ====================
@cli.group()
def group():
    """Manage groups of VM templates."""


@group.command()
@click.argument('name')
def create(name):
    """Create a new group."""
    grp = BackendGroup(name, GROUP_DIR)
    grp.path.mkdir(parents=True, exist_ok=False)
    grp.snapshot_dir.mkdir()
    grp.vm_template_dir.mkdir()
    click.echo(f"Group '{name}' created.")


@group.command()
@click.argument('name')
def delete(name):
    """Delete a group."""
    grp = BackendGroup(name, GROUP_DIR)
    grp.delete()
    click.echo(f"Deleted group '{name}'.")


@group.command()
@click.argument('vm_name')
@click.argument('group_name')
def add(vm_name, group_name):
    """Add a VM template to a group."""
    grp = BackendGroup(group_name, GROUP_DIR)
    vm_path = VM_TEMPLATE_DIR / vm_name
    dest = grp.vm_template_dir / vm_name
    shutil.copytree(vm_path, dest)
    click.echo(f"Added VM '{vm_name}' to group '{group_name}'.")


@group.command()
@click.argument('vm_name')
@click.argument('group_name')
def remove(vm_name, group_name):
    """Remove a VM template from a group."""
    grp = BackendGroup(group_name, GROUP_DIR)
    dest = grp.vm_template_dir / vm_name
    shutil.rmtree(dest)
    click.echo(f"Removed VM '{vm_name}' from group '{group_name}'.")


@group.command()
@click.argument('name')
def instantiate(name):
    """Start a group (create an instance)."""
    click.echo(f"Instantiated group '{name}'.")


@group.command()
@click.argument('name')
def edit(name):
    """Edit a group's configuration."""
    grp = BackendGroup(name, GROUP_DIR)
    config_file = grp.path / "config.yaml"
    if not config_file.exists():
        config_file.write_text("# Group configuration\n")
    subprocess.run([get_editor(), str(config_file)])


# ====================
# Instance commands
# ====================
@cli.group()
def instance():
    """Manage running instances."""


@instance.command()
@click.argument('name')
@click.option('--vm', help="Specific VM to stop.")
def stop(name, vm):
    """Stop an instance or a specific VM."""
    click.echo(f"Stopping instance '{name}', target: {vm or 'all VMs'}")


@instance.command()
@click.argument('name')
@click.option('--vm', help="Specific VM to suspend.")
def suspend(name, vm):
    """Suspend an instance or a specific VM."""
    click.echo(f"Suspending instance '{name}', target: {vm or 'all VMs'}")


@instance.command()
@click.argument('name')
@click.option('--vm', help="Specific VM to resume.")
def resume(name, vm):
    """Resume a suspended instance or a specific VM."""
    click.echo(f"Resuming instance '{name}', target: {vm or 'all VMs'}")


@instance.command()
@click.argument('name')
@click.argument('snapshot_name')
@click.option('--vm', help="Specific VM to snapshot.")
def snapshot(name, snapshot_name, vm):
    """Take a snapshot of an instance or specific VM."""
    click.echo(f"Snapshotting instance '{name}' as '{snapshot_name}', target: {vm or 'all VMs'}")


@instance.command()
@click.argument('instance_name')
@click.argument('vm_name')
def ssh(instance_name, vm_name):
    """SSH into a VM in a running instance."""
    click.echo(f"SSH into VM '{vm_name}' in instance '{instance_name}'.")


# ====================
# List command
# ====================
@cli.command()
@click.argument('type', type=click.Choice(['instances', 'suspended', 'vm_templates', 'groups']))
def list(type):
    """List resources."""
    click.echo(f"Listing {type}...")


if __name__ == "__main__":
    cli()
