import pathlib
import yaml
import libvirt

DEFAULT_CONFIG_FILE = pathlib.Path("/etc/mockmox/config.yaml")
DEFAULT_SOCKET = "qemu:///system"

def load_config(config_file: pathlib.Path, qemu_socket: str):
    if config_file.exists():
        try:
            config = yaml.safe_load(config_file.read_text())
        except yaml.YAMLError as E:
            raise yaml.YAMLError(f"Config file {config_file} has invalid YAML syntax. Edit or reinstall to fix.\n{E}")
        except PermissionError as E:
            raise PermissionError(f"Config file {config_file} cannot be read. Add read permissions to fix.\n{E}")
    else:
        config = {}

    # If config has directories key with base_dir key, use that value. Else, use the final value
    base_dir = pathlib.Path(config.get("directories", {}).get("base_dir", "/opt/mockmox"))
    config['group_dir'] = base_dir / "groups"
    config['vm_template_dir'] = base_dir / "vms_templates"
    config['instance_dir'] = base_dir / "instances"
    config['suspended_dir'] = base_dir / "suspended"
    config['default_dir'] = base_dir / "defaults"

    config['script_location'] = pathlib.Path(config.get("directories", {}).get("base_dir", "/bin/mockmox"))

    config['vm_default_disk_size'] = config.get("defaults", {}).get("vm_disk_size", 64) # GB
    config['vm_default_cpus'] = config.get("defaults", {}).get("vm_cpus", 4)
    config['vm_default_memory'] = config.get("defaults", {}).get("vm_memory", 8192) # MB

    if not qemu_socket:
        config['qemu_socket'] = config.get("defaults", {}).get("qemu_socket", DEFAULT_SOCKET)
    else:
        config['qemu_socket'] = qemu_socket

    return config
