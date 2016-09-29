#!/usr/bin/env python

from setuptools import setup

# setup the project
setup(
    name="django-flash",
    version="0.0.1",
    author="HackerEarth",
    author_email="support@hackerearth.com",
    description="A cache framework for Django",
    license="MIT",
    packages= [
        'flash',
    ],
    zip_safe=False,
)
