from setuptools import setup, find_packages

setup(
    name = "PostDrive",
    version = "0.1.0",
    description = "后处理工具",
    author = "JJ",
    packages = find_packages(),
    install_requires = [],
    options = {
        'bdist_wheel': {
            'python_tag': 'cp311',  # 或者 'cp38', 'cp39' 等
        }
    },
)