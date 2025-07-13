import pathlib
import datetime
import shutil
from vm_template import VMTemplate

class Instance:
    def __init__(self, group: pathlib.Path, instance_dir: pathlib.Path, vm_template_dir: pathlib.Path, name: str = None):
        self.group = group
        self.instance_dir = instance_dir
        self.vm_template_dir = vm_template_dir
        self.name = name
        self.path = None

    def start(self):
        self.name = f"{self.group.name}-{datetime.datetime.now().timestamp()}"
        self.path = self.instance_dir / self.name

        # Iterate until new name found
        while self.path.exists():
            self.name = f"{self.group.name}-{int(datetime.datetime.now().timestamp()) + 1}"
            self.path = self.instance_dir / self.name

        for path in self.group.rglob('*'):
            relative = path.relative_to(self.group)
            target = self.path / relative

            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif path.is_file():
                if path.match("*qcow2"):
                    target.symlink_to(path.resolve())
                else:
                    shutil.copy2(path, target)

        for vm in [VMTemplate(x.name, self.vm_template_dir) for x in (self.path / "vm_templates").iterdir()]:
            vm.start()

    def suspend(self):
        pass

    def resume(self):
        pass

    def stop(self):
        pass