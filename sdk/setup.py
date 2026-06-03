from setuptools import setup, find_packages

setup(
    name="llm-logger",
    version="0.1.0",
    description="Lightweight SDK for capturing LLM inference metadata",
    author="Aadit Singal",
    python_requires=">=3.9",
    packages=find_packages(),
    install_requires=[
        "requests>=2.28",
    ],
    extras_require={
        "anthropic": ["anthropic>=0.25"],
        "openai": ["openai>=1.0"],
        "all": ["anthropic>=0.25", "openai>=1.0"],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
