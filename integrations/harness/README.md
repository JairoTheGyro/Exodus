# Exodus Code

Official source: https://github.com/deepseek-ai/deepseek-harness
Published package: @deepseek-ai/dsh 0.1.7-rc.2, MIT, developer preview.

Start from the Sovereign Hub directory:

```sh
docker compose -p sovereign-hub up -d --build --no-deps harness
```

Open Exodus → Tools → Code. Opening Code connects the current administrator's
model catalog; no provider keys need to be copied. Add models through Exodus,
then select a model under Exodus in Harness. Tool-calling models are required.
The coding files are in `data/code-projects` on the host, `/workspace` in Harness.
Harness settings and sessions live in the `harness-home` named Docker volume.

Keep both data locations when restarting or rebuilding. Do not use `down -v`.
Opening the bare local address may require using Open Code again to sign in.
Remote access and multiple independent users are not configured.

The supervisor updates only the `exodus` provider. Its conservative capacity
defaults are 8,192 context and 2,048 output tokens, with text input. The user can
use Harness's existing custom providers for advanced provider-specific options;
Exodus remains the source for the managed provider. No real model was connected
or charged during integration tests.

## Isolated verification

From Sovereign Hub, run the gateway and settings checks:

```sh
docker exec -i sovereign-hub-odysseus-1 python - < tests/code_integration.py
docker exec -i sovereign-hub-harness-1 node --input-type=module < tests/helpers/test_code_sync.mjs
```

For the full transport/tool test, run the fixture in one terminal:

```sh
docker exec -i sovereign-hub-odysseus-1 python - < tests/code_e2e_fixture.py
```

Then run in another terminal:

```sh
docker exec -i sovereign-hub-harness-1 node --input-type=module < tests/helpers/run_code_harness_e2e.mjs
```

Stop the fixture process afterwards. Port 7094 is a temporary container-only
fixture, never a published host service. The test creates and removes its own
Harness home and workspace under `/tmp`; it does not add a fake production model.

## Guided Workshop

AI Workshop uses this same installed Harness engine behind the scenes. Connect
a tool-capable model in Exodus, describe a small app in Workshop, review its
scope, and select Build my tool. The result still saves into Exodus's Library
and runs in its existing restricted preview. Advanced options keeps the earlier
basic builder and a route to the direct Code interface.

Each build uses a temporary headless profile and only a checked HTML submission
tool, with no shell or general filesystem tools. HTML structure and inline script
syntax checks support a repair loop; they do not establish correct behavior or
security. Builds stop after five minutes and can be cancelled. Cloud model
requests already sent may still be billed. Temporary files are cleaned up; saved
apps and entries remain managed by Exodus.

With the fixture server above running, check the full Workshop engine:

```sh
docker exec -i sovereign-hub-harness-1 node --input-type=module < tests/helpers/run_workshop_harness_e2e.mjs
docker exec -i sovereign-hub-harness-1 node --input-type=module < tests/helpers/test_workshop_tools.mjs
docker exec -i sovereign-hub-odysseus-1 python - < tests/workshop_integration.py
```
