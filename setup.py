from setuptools import setup, find_packages

requires = [
    'requests-client',
]

setup(
    name='amocrm-api',
    version='0.0.1',
    description='http://github.com/vgavro/amocrm-api',
    long_description='http://github.com/vgavro/amocrm-api',
    license='BSD',
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    author='Victor Gavro',
    author_email='vgavro@gmail.com',
    url='http://github.com/vgavro/amocrm-api',
    keywords='',
    packages=find_packages(),
    install_requires=requires,
)
