import pathlib
#import libvirt
import shutil
import logging


class Group:
    def __init__(self, name: str, global_group_dir: pathlib.Path, global_templates_dir: pathlib.Path):
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.vm_templates = []
        self.path = global_group_dir / name
        self.snapshot_dir = self.path / "snapshots"
        self.vm_template_dir = self.path / "vm_templates"
        self.global_templates_dir = global_templates_dir

        if self.vm_template_dir.exists():
            self.vm_templates = self.vm_template_dir.iterdir()


    def create(self):
        if self.path.exists():
            raise FileExistsError(f"Cannot create existing group {self.name}")

        self.path.mkdir()
        self.snapshot_dir.mkdir()
        self.vm_template_dir.mkdir()


    def delete(self):
        if not self.path.exists():
            raise FileNotFoundError(f"Cannot delete nonexistent group {self.name}")

        shutil.rmtree(self.path)


    def add_vm_template(self, template_name: str):
        if template_name not in self.global_templates_dir.iterdir():
            raise FileNotFoundError(f"Cannot add nonexistent template {template_name}")

        # This is a stylistic choice. QCOW2 files can be *heavy* and are difficult to modify; I'm declaring them immutable
        # Instead, modify files and executables per VM template instead of the disk image
        src = self.global_templates_dir / template_name
        dst = self.vm_template_dir / template_name
        for path in src.rglob('*'):
            relative = path.relative_to(src)
            target = dst / relative

            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif path.is_file():
                if path.match("*qcow2"):
                    target.symlink_to(path.resolve())
                else:
                    shutil.copy2(path, target)


    def delete_vm_template(self, template_name: str):
        if template_name not in self.vm_template_dir.iterdir():
            raise FileNotFoundError(f"VM template {template_name} not added to this group.")

        shutil.rmtree(self.vm_template_dir / template_name)





