from setuptools import setup, find_packages

setup(
    name="dmsai-shared",
    version="0.1.0",
    packages=find_packages(),
    install_requires=["sqlmodel", "aiosqlite"],
)
