FROM gitpod/workspace-python

RUN pyenv update && \
    pyenv install 3.9.9 && \
    pyenv global 3.9.9
