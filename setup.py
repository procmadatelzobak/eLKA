from setuptools import setup, find_packages

setup(
    name='elka',
    version='0.1.0',
    packages=find_packages(),
    install_requires=[
        'PyYAML',
        'python-dotenv',
        'PyGithub',
        'google-generativeai',
        'requests',
    ],
    entry_points={
        'console_scripts': [
            'elka = elka.main:main',
        ],
    },
)
