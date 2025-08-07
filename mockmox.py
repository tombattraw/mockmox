#!/usr/bin/env python3
import os
import click
import pathlib
import shutil
import subprocess
import logging
import sys
import libvirt

# Backend classes
from classes.common import get_editor
from classes.group import Group
from classes.vm_template import VMTemplate
from classes.config import load_config, DEFAULT_CONFIG_FILE, DEFAULT_SOCKET

# Yes, globals suck. Unfortunately, I'm not dealing with loading this in every subordinate function
# And, because click is aggressively unhelpful when you need to load variables first...
# here comes the ugliest hack you'll ever see:
try:
    idx = sys.argv.index('--config-file')
    config_file = pathlib.Path(sys.argv[idx + 1])
except (ValueError, IndexError):
    config_file = DEFAULT_CONFIG_FILE

try:
    idx = sys.argv.index('--libvirtd-connection')
    libvirtd_connection = sys.argv[idx + 1]
except (ValueError, IndexError):
    libvirtd_connection = DEFAULT_SOCKET

CONFIG = load_config(config_file, libvirtd_connection)
CONNECTION = libvirt.open(CONFIG["libvirtd_connection"])


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(message)s"
)

@click.group()
@click.option('--libvirtd-connection', default="qemu:///system", help="Libvirtd hypervisor connection string.")
@click.option('--config-file', type=click.Path(), default=DEFAULT_CONFIG_FILE, help="Path to config file.")
@click.option('--verbose', is_flag=True, help="Enable verbose output.")
@click.pass_context
def cli(ctx, libvirtd_connection, config_file, verbose):
    """Mockmox: VM and group management framework."""
    ctx.ensure_object(dict)
    ctx.obj['LIBVIRTD_CONNECTION'] = libvirtd_connection
    ctx.obj['CONFIG_FILE'] = config_file
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
@click.option('-s', '--size', default=CONFIG['vm_default_disk_size'], help=f"Disk size in GB (default: {CONFIG['vm_default_disk_size']})")
@click.option('-c', '--cpus', default=CONFIG['vm_default_cpus'], help=f"Number of CPUs (default: {CONFIG['vm_default_cpus']})")
@click.option('-m', '--memory', default=CONFIG['vm_default_memory'], help=f"Memory size in MB (default: {CONFIG['vm_default_memory']}")
@click.option('--existing-qcow2', type=click.Path(), help=f"Use existing disk image")
@click.option('-i', '--iso', type=click.Path(), help="Path to installation ISO")
def create(name, size, cpus, memory, existing_qcow2, iso):
    """Create a new VM template."""
    vm = VMTemplate(name, CONFIG['vm_template_dir'], CONNECTION)
    existing_disk = pathlib.Path(existing_qcow2) if existing_qcow2 else None
    iso_path = pathlib.Path(iso) if iso else None
    vm.create(
        disk_size=size,
        cpus=cpus,
        memory=memory,
        existing_disk_image=existing_disk,
        iso=iso_path)

    connection.close()

    click.echo(f"VM '{name}' created.")


@vm.command()
@click.argument('name')
@click.argument('--acknowledge', type=bool)
def delete(name, acknowledge):
    """Delete a VM template."""
    vm = VMTemplate(name, CONFIG['vm_template_dir'], delete=True)
    vm.delete(CONFIG['vm_group_dir'], acknowledge)
    click.echo(f"Deleted VM '{name}'.")


@vm.command()
@click.argument('name')
def edit(name):
    """Edit a VM template's configuration."""
    vm = VMTemplate(name, CONFIG['vm_template_dir'])
    vm.edit()


@vm.command('list-files')
@click.argument('name')
@click.option('-u', '--user', type=click.Choice(['user', 'root']), required=True, help="List user or root files.")
@click.option('-t', '--type', type=click.Choice(['file', 'executable']), required=True, help="File or executable?")
def list_files(name, user, type):
    """List files/scripts owned by a VM template."""
    vm = VMTemplate(name, CONFIG['vm_template_dir'])
    files = vm.list_files(user, type)
    click.echo(files)


@vm.command('add-file')
@click.argument('name')
@click.argument('source_file', type=click.Path(exists=True))
@click.option('-u', '--user', type=click.Choice(['user', 'root']), required=True, help="Owner of the file.")
@click.option('-t', '--type', type=click.Choice(['file', 'executable']), required=True, help="File type.")
def add_file(name, source_file, user, type):
    """Add a file or executable to a VM template."""
    vm = VMTemplate(name, CONFIG['vm_template_dir'])
    vm.add_file(pathlib.Path(source_file), user, type)
    click.echo(f"Added {type} '{source_file}' to VM '{name}' as {user}.")


@vm.command('remove-file')
@click.argument('name')
@click.argument('source_file', type=click.Path())
@click.option('-u', '--user', type=click.Choice(['user', 'root']), required=True)
@click.option('-t', '--type', type=click.Choice(['file', 'executable']), required=True)
def remove_file(name, source_file, user, type):
    """Remove a file or executable from a VM template."""
    vm = VMTemplate(name, CONFIG['vm_template_dir'])
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
    grp = Group(name, CONFIG['vm_group_dir'], CONFIG['vm_template_dir'])
    grp.path.mkdir(parents=True, exist_ok=False)
    grp.snapshot_dir.mkdir()
    grp.vm_template_dir.mkdir()
    click.echo(f"Group '{name}' created.")


@group.command()
@click.argument('name')
def delete(name):
    """Delete a group."""
    grp = Group(name, CONFIG['vm_group_dir'], CONFIG['vm_template_dir'])
    grp.delete()
    click.echo(f"Deleted group '{name}'.")


@group.command()
@click.argument('vm_name')
@click.argument('group_name')
def add(vm_name, group_name):
    """Add a VM template to a group."""
    grp = Group(group_name, CONFIG['vm_group_dir'], CONFIG['vm_template_dir'])
    vm_path = CONFIG['vm_template_dir'] / vm_name
    dest = grp.vm_template_dir / vm_name
    shutil.copytree(vm_path, dest)
    click.echo(f"Added VM '{vm_name}' to group '{group_name}'.")


@group.command()
@click.argument('vm_name')
@click.argument('group_name')
def remove(vm_name, group_name):
    """Remove a VM template from a group."""
    grp = Group(group_name, CONFIG['vm_group_dir'], CONFIG['vm_template_dir'])
    dest = grp.vm_template_dir / vm_name
    shutil.rmtree(dest)
    click.echo(f"Removed VM '{vm_name}' from group '{group_name}'.")


@group.command()
@click.argument('name')
def instantiate(name):
    """Start a group (create a set of instances)."""
    click.echo(f"Instantiated group '{name}'.")


@group.command()
@click.argument('name')
def edit(name):
    """Edit a group's configuration."""
    grp = Group(name, CONFIG['vm_group_dir'], CONFIG['vm_template_dir'])
    config_file = grp.path / "config.yaml"
    if not config_file.exists():
        config_file.write_text("# Group configuration\n")
    subprocess.run([get_editor(), str(config_file)])


# ====================
# Instance commands
# ====================
@cli.group()
def instance():
    """Manage running instances (running groups)"""


@instance.command()
@click.argument('name')
@click.option('--vm', help="Specific VM to stop.")
def stop(name, vm):
    """Stop an instance."""
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


@cli.command()
def install():
    """Install the script"""
    base_dir = pathlib.Path(CONFIG["directories"]["base_dir"])
    if not base_dir.parent.exists():
        raise FileNotFoundError(f"The parent directory of the base directory {base_dir}, specified in {config_file}, does not exist.")

    script_location = pathlib.Path(CONFIG["directories"]["script_location"])
    if not script_location.parent.exists():
        raise FileNotFoundError(
            f"The parent directory of the script location {script_location} specified in {config_file}, does not exist.")

    base_dir.mkdir()
    (base_dir / "groups").mkdir()
    (base_dir / "vm_templates").mkdir()
    (base_dir / "active").mkdir()
    (base_dir / "suspended").mkdir()
    (base_dir / "defaults").mkdir()

    shutil.copytree(pathlib.Path(__file__).parent, base_dir)
    os.symlink(base_dir / "mockmox.py", script_location)




if __name__ == "__main__":
    cli()
