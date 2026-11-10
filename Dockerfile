ARG BASE_IMAGE=python:3.15.2-alpine
FROM ${BASE_IMAGE}
LABEL edu.netlab.owner="autonomous-netlab"
RUN apk add --no-cache bash curl iproute2 iputils git
WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["sleep", "infinity"]
