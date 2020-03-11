FROM python:3.6.9-buster

COPY requirements.txt ./
RUN pip install -r requirements.txt

ADD . /worker
WORKDIR /worker

EXPOSE 5000
EXPOSE 8020

ENTRYPOINT ["python", "./initialise_server.py"]

CMD ["--help"]