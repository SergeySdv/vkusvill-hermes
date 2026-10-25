import json
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def command(arguments, *, check=True):
    try:
        return subprocess.run(
            arguments, capture_output=True, text=True, check=check, timeout=120
        ).stdout
    except subprocess.CalledProcessError as error:
        if "compose" in arguments:
            operation = arguments[6]
            if operation in ("config", "run", "up", "exec", "restart", "stop", "logs", "down"):
                print(json.dumps({"failed_operation": operation, "exit_code": error.returncode}))
            if operation == "run" and "validate" in arguments:
                print(error.stderr)
        raise


def main():
    project = "vv-isolation-" + secrets.token_hex(5)
    services = {}
    volumes = {}
    for number in (1, 2):
        services[f"auth{number}"] = {
            "image": "vv-auth-candidate",
            "read_only": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "mem_limit": "256m",
            "pids_limit": 64,
            "entrypoint": ["/opt/vv/.venv/bin/python", "/fixture.py"],
            "environment": {
                "FIXTURE_ORIGIN": f"https://connect{number}.test",
                "FIXTURE_OWNER": str(number),
            },
            "volumes": [
                f"state{number}:/state",
                f"client{number}:/client",
                f"{ROOT}/e2e/broker_container_fixture.py:/fixture.py:ro",
            ],
            "networks": {f"bridge{number}": {"aliases": ["vv-auth"]}, f"ingress{number}": {}},
        }
        services[f"agent{number}"] = {
            "image": "vv-auth-candidate",
            "user": "0:0",
            "read_only": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "entrypoint": ["/opt/vv/.venv/bin/python", "-c", "import time; time.sleep(600)"],
            "volumes": [f"client{number}:/client:ro"],
            "networks": [f"bridge{number}"],
        }
        volumes.update({f"state{number}": {}, f"client{number}": {}})
    with tempfile.TemporaryDirectory(prefix=project) as temporary:
        directory = Path(temporary)
        original = (ROOT / "deploy/broker/Caddyfile").read_text()
        site = original[original.index("{$VV_AUTH_DOMAIN}") :]
        caddyfile = directory / "Caddyfile"
        caddyfile.write_text(
            "{\n admin off\n servers {\n strict_sni_host on\n }\n}\n"
            + "\n".join(
                site.replace("{$VV_AUTH_DOMAIN}", f"connect{number}.test")
                .replace("vv-auth:8080", f"auth{number}:8080")
                .replace("request_body {", "tls internal\n    request_body {")
                for number in (1, 2)
            )
        )
        services["caddy"] = {
            "image": os.environ.get("VV_CADDY_TEST_IMAGE", "caddy:2.11.7-alpine"),
            "read_only": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "volumes": [f"{caddyfile}:/etc/caddy/Caddyfile:ro"],
            "tmpfs": ["/data:mode=1777", "/config:mode=1777", "/tmp:mode=1777"],
            "networks": {
                "public": {"aliases": ["connect1.test", "connect2.test"]},
                "ingress1": {},
                "ingress2": {},
            },
        }
        services["probe"] = {
            "image": "vv-auth-candidate",
            "read_only": True,
            "entrypoint": ["/opt/vv/.venv/bin/python", "-c", "import time; time.sleep(600)"],
            "networks": ["public"],
        }
        config = directory / "compose.json"
        config.write_text(
            json.dumps(
                {
                    "services": services,
                    "volumes": volumes,
                    "networks": {
                        name: {"internal": True}
                        for name in ("public", "bridge1", "bridge2", "ingress1", "ingress2")
                    },
                }
            )
        )
        compose = ["docker", "compose", "-p", project, "-f", str(config)]
        try:
            command(compose + ["config", "--quiet"])
            for number in (1, 2):
                command(
                    compose
                    + [
                        "run",
                        "--rm",
                        "--no-deps",
                        "--user",
                        "0",
                        "--cap-add",
                        "CHOWN",
                        "--cap-add",
                        "FOWNER",
                        "--entrypoint",
                        "/opt/vv/.venv/bin/python",
                        f"auth{number}",
                        "-c",
                        "import os; [(os.chown(path,10001,10001),os.chmod(path,0o700)) "
                        "for path in ['/state','/client']]",
                    ]
                )
            command(
                compose
                + [
                    "run",
                    "--rm",
                    "--no-deps",
                    "--entrypoint",
                    "caddy",
                    "caddy",
                    "validate",
                    "--config",
                    "/etc/caddy/Caddyfile",
                ]
            )
            command(compose + ["up", "-d", "--pull", "never"])

            def execute(service, program):
                return command(
                    compose + ["exec", "-T", service, "/opt/vv/.venv/bin/python", "-c", program]
                )

            for _ in range(60):
                try:
                    execute(
                        "auth1",
                        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ready').close()",
                    )
                    execute(
                        "auth2",
                        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ready').close()",
                    )
                    break
                except subprocess.CalledProcessError:
                    time.sleep(0.2)
            else:
                raise AssertionError("Fixture readiness failed")
            credentials = []
            for number in (1, 2):
                credentials.append(
                    json.loads(
                        execute(
                            f"auth{number}",
                            "from pathlib import Path; "
                            "print(Path('/client/bridge.json').read_text())",
                        )
                    )["bridge_key"]
                )
            contexts = []
            for number in (1, 2):
                credential = credentials[number - 1]
                program = (
                    "import json,httpx,pathlib,socket; "
                    f"headers={{'Authorization':'Bearer '+{credential!r}}}; "
                    "response=httpx.get('http://vv-auth:8080/bridge/status',"
                    "headers=headers,trust_env=False); "
                    "assert response.status_code==200; print(json.dumps(response.json()['data'])); "
                    "assert not pathlib.Path('/state').exists(); "
                    "assert not pathlib.Path('/run/secrets/broker.json').exists(); "
                    "assert not pathlib.Path('/var/run/docker.sock').exists(); "
                    "response=httpx.get('http://vv-auth:8080/bridge/status',"
                    f"headers={{'Authorization':'Bearer '+{credentials[2 - number]!r}}},"
                    "trust_env=False); "
                    "assert response.status_code==401; "
                    f"\ntry: socket.gethostbyname('auth{3 - number}')"
                    "\nexcept socket.gaierror: pass"
                    "\nelse: raise AssertionError('Foreign network reachable')"
                )
                contexts.append(json.loads(execute(f"agent{number}", program))["context"])
            assert contexts[0] != contexts[1]
            inspect = json.loads(
                command(["docker", "inspect", command(compose + ["ps", "-q", "caddy"]).strip()])
            )[0]
            assert not inspect["HostConfig"]["PortBindings"]
            certificate = command(
                compose
                + ["exec", "-T", "caddy", "cat", "/data/caddy/pki/authorities/local/root.crt"]
            )
            paths = [
                "/bridge",
                "/bridge/status",
                "/bridge/call",
                "/%62ridge/status",
                "/bridge%2fstatus",
                "/api/../bridge/status",
                "/ready",
                "/health",
                "/unknown",
            ]
            execute(
                "probe",
                "import ssl,httpx; "
                + f"context=ssl.create_default_context(cadata={certificate!r}); "
                + f"headers={{'Authorization':'Bearer '+{credentials[0]!r}}}; "
                + "client=httpx.Client(verify=context,trust_env=False,follow_redirects=False); "
                + "assert client.get('http://connect1.test/').status_code==308, 'redirect'; "
                + "assert client.get('https://connect1.test/').status_code==200, 'public-page'; "
                + "assert client.get('https://connect1.test/',"
                "headers={'Host':'unknown.test'}).status_code!=200, 'unknown-host'; "
                + f"\nfor path in {paths!r}:\n for method in ('GET','POST','PUT','OPTIONS'):\n"
                "  assert client.request(method,'https://connect1.test'+path,"
                "headers=headers).status_code==404\n"
                + "assert client.post('https://connect1.test/api/session',"
                "headers={'Origin':'https://connect1.test'},"
                "json={'init_data':'x'*40000}).status_code in (400,413,503)",
            )
            command(compose + ["restart", "auth1"])
            time.sleep(1)
            command(compose + ["up", "-d", "--no-deps", "--force-recreate", "auth1"])
            time.sleep(1)
            status = json.loads(
                execute(
                    "agent1",
                    "import httpx,json; print(json.dumps(httpx.get('http://vv-auth:8080/bridge/status',headers="
                    + repr({"Authorization": "Bearer " + credentials[0]})
                    + ",trust_env=False).json()['data']))",
                )
            )
            assert status["context"] == contexts[0]
            command(compose + ["stop", "auth1"])
            execute(
                "probe",
                "import httpx,ssl; "
                + f"context=ssl.create_default_context(cadata={certificate!r}); "
                + "response=httpx.get('https://connect1.test/oauth/callback?"
                "code=LOG-CANARY-CODE&state=LOG-CANARY-STATE',verify=context,trust_env=False); "
                "assert response.status_code==503; assert 'LOG-CANARY' not in response.text",
            )
            logs = command(compose + ["logs", "--no-color"])
            for value in (
                *credentials,
                "SYNTHETIC-SECRET-CANARY",
                "SYNTHETIC-ACCESS-CANARY",
                "SYNTHETIC-REFRESH-CANARY",
                "LOG-CANARY",
            ):
                assert value not in logs, "Secret canary in container logs"
            print(
                json.dumps(
                    {
                        "passed": True,
                        "mode": "synthetic_container_isolation",
                        "instances": 2,
                        "tls_verified": True,
                        "restart_recreate": True,
                        "production_changed": False,
                    }
                )
            )
        finally:
            command(compose + ["down", "--volumes", "--remove-orphans"], check=False)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        raise SystemExit(
            "Container gate failed; command output suppressed (synthetic credentials)."
        ) from None
