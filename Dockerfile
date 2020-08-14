FROM python:3.7-slim

COPY requirements.txt /requirements.txt

RUN pip install -r /requirements.txt

COPY . /opt/test-runner

WORKDIR /opt/test-runner

ENTRYPOINT [ "sh", "bin/run.sh" ]
