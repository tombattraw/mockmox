import os
import pathlib
#import libvirt
import yaml
import shutil
import subprocess
import logging


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(message)s"
)


class VMTemplate:
    def __init__(self, name: str, vm_template_dir: pathlib.Path, delete: bool = False):
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

        # executables and files aren't mandatory
        self.user_executables = self.user_executable_dir.iterdir() if self.user_executable_dir.exists() else []
        self.root_executables = self.root_executable_dir.iterdir() if self.root_executable_dir.exists() else []
        self.user_files = self.user_files_dir.iterdir() if self.user_files_dir.exists() else []
        self.root_files = self.root_files_dir.iterdir() if self.root_files_dir.exists() else []


    def delete(self):
        if not self.path.exists():
            raise FileNotFoundError(f"Cannot delete nonexistent template {self.name}")
        shutil.rmtree(self.path)


    def create(self, disk_size: int,
               cpus: int,
               memory: int,
               os_variant: str = '',
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
        self.user_executable_dir.mkdir()
        self.root_executable_dir.mkdir()
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


    def edit(self):
        tmp_file = self.config_file.parent / f"{self.config_file.name}.tmp"

        shutil.copyfile(self.config_file, tmp_file)

        subprocess.run([get_editor(), tmp_file])

        try:
            yaml.safe_load(tmp_file.read_text())
        except yaml.YAMLError as E:
            tmp_file.unlink()
            raise yaml.YAMLError(f"YAML error in config file; unable to apply\n{E}")

        tmp_file.replace(self.config_file)
        print(f"Configuration changes applied to {self.config_file}")


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
    def __init__(self, name: str, group_dir: pathlib.Path):
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.vm_templates = []
        self.path = group_dir / name
        self.snapshot_dir = self.path / "snapshots"
        self.vm_template_dir = self.path / "vm_templates"






    def delete(self):
        if not self.path.exists():
            raise AttributeError(f"Cannot delete nonexistent template {self.name}")
        shutil.rmtree(self.path)




def get_editor():
    editor = os.environ.get('EDITOR')
    if editor: return editor
    editor = os.environ.get('VISUAL')
    if editor: return editor

    for fallback in ['nano', 'vim', 'vi']:
        if shutil.which(fallback):
            return fallback
    raise RuntimeError("No editor found. Set the EDITOR environment variable.")
