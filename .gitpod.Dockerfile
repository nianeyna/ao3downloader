FROM gitpod/workspace-full

RUN pyenv update && \
    pyenv install 3.9.9 && \
    pyenv global 3.9.9 && \
    python3 -m pip install --no-cache-dir --upgrade pip
