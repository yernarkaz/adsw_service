import os, pip


def __read(fname):
    try:
        return open(os.path.join(os.path.dirname(__file__), fname)).read()
    except IOError:
        return ''

def install(package):
    pip.main(['install', package])


install_requires = __read('requirements.txt').split('\n')

for package in install_requires:
    install(package)

