FROM python:3.8-slim
ENV PYTHONUNBUFFERED 1
RUN apt-get update -y \
        && apt-get install -y git \
        && pip install pipenv
WORKDIR /app/
COPY ./Pipfile.lock ./Pipfile /app/
RUN pipenv install --system --deploy --ignore-pipfile
COPY ./ /app/
ENTRYPOINT ["python3", "/app/app.py"]
