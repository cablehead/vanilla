import sys
import re

from setuptools.command.test import test as TestCommand
from setuptools import setup
from setuptools import find_packages


metadata = dict(
    re.findall("__([a-z]+)__ = '([^']+)'", open('vanilla/meta.py').read()))

requirements = [
    x.strip() for x
    in open('requirements.txt').readlines() if not x.startswith('#')]


description = "Straightforward concurrency for Python " \
    "http://vanillapy.readthedocs.org/"


class PyTest(TestCommand):
    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        import pytest
        errno = pytest.main(self.test_args)
        sys.exit(errno)


setup(
    name='vanilla',
    version=metadata['version'],
    author='Andy Gayton',
    author_email='andy@thecablelounge.com',
    install_requires=requirements,
    packages=find_packages(),
    url='https://github.com/cablehead/vanilla',
    license='MIT',
    description=description,
    long_description=open('README.rst').read(),
    tests_require=['pytest'],
    cmdclass={'test': PyTest},
)
