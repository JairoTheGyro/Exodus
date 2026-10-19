FROM node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6
RUN apt-get update && apt-get install -y --no-install-recommends git python3 ca-certificates ripgrep \
    && rm -rf /var/lib/apt/lists/*
RUN npm install --global --allow-scripts=@deepseek-ai/dsh-subprocess-local,koffi,node-pty,@google/genai,protobufjs @deepseek-ai/dsh@0.2.1-rc.2 && npm cache clean --force
RUN mkdir -p /workspace /home/node/.dsh && chown -R node:node /workspace /home/node/.dsh
COPY supervisor.mjs workshop-runner.mjs workshop-tools.mjs /opt/exodus/
ENV DSH_HOME=/home/node/.dsh
USER node
WORKDIR /workspace
EXPOSE 3080
CMD ["node", "/opt/exodus/supervisor.mjs"]
