FROM google/cloud-sdk:latest

RUN apt-get update -y

RUN apt-get install python3.7 -y

COPY . /app

WORKDIR /app

RUN apt install python3-pip -y
RUN python3 -m pip install --upgrade pip

RUN python3 -m pip install -r requirements.txt

EXPOSE 5000

CMD ["uvicorn", "app:app", "--proxy-headers", "--host", "0.0.0.0", "--port", "5000"]
