from setuptools import setup, find_packages

setup(
    name='autoPDFtagger',
    version='0.2.0',
    packages=find_packages(),
    description='autoPDFtagger is a Python tool designed for efficient home-office organization, focusing on digitizing and organizing both digital and paper-based documents. By automating the tagging of PDF files, including image-rich documents and scans of varying quality, it aims to streamline the organization of digital archives.',
    author='Ulrich Zorn',
    author_email='uli_z@posteo.de',
    url='https://github.com/Uli-Z/autoPDFtagger',
    install_requires=[
        "PyMuPDF==1.23.6",
        "openai>=1.27.0,<2",
        "pytz==2022.7",
        "tenacity==8.2.3",
        "tiktoken>=0.4.0,<1",
        "litellm>=1.40.0",
        "pdfminer.six>=20221105",
    ],
    entry_points={
        'console_scripts': [
            'autoPDFtagger = autoPDFtagger.main:main',
        ],
    },
)
