import importlib.util
import os

class AlgorithmRegistry:
    def __init__(self):
        self.methods = {}

    def scan_and_load(self, algorithms_dir: str):
        if not os.path.isdir(algorithms_dir):
            return
        for filename in sorted(os.listdir(algorithms_dir)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            filepath = os.path.join(algorithms_dir, filename)
            spec = importlib.util.spec_from_file_location(filename[:-3], filepath)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            name = getattr(module, "NAME", None)
            if name is None:
                continue
            self.methods[name] = {
                "name": name,
                "description": getattr(module, "DESCRIPTION", ""),
                "defaults": getattr(module, "DEFAULTS", {}),
                "execute": module.execute,
            }

    def get(self, method_name: str):
        return self.methods.get(method_name)

    def list_methods(self) -> list:
        return [{"name": m["name"], "description": m["description"],
                 "defaults": m["defaults"]} for m in self.methods.values()]
