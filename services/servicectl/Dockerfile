# Exodus service manager helper: Docker CLI (with the compose plugin) plus the
# Python standard library. See servicectl.py for the allow-listed actions.
FROM docker:27.5-cli
RUN apk add --no-cache python3
COPY servicectl.py /opt/servicectl/servicectl.py
EXPOSE 8095
CMD ["python3", "/opt/servicectl/servicectl.py"]
