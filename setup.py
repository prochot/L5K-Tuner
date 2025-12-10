from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="L5KTuner",
    version="0.1.0",
    author="Alex Prochot",
    description="GUI tool for inspecting, filtering, and exporting Rockwell Logix L5K files, adjusted for import into AVEVA Edge",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/prochot/L5KTuner",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Intended Audience :: Developers",
    ],
    python_requires=">=3.12",
    entry_points={
        "console_scripts": [
            "l5k-tuner=L5KTuner.main:main",
        ],
    },
)
