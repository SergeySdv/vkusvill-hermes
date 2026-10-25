ARG BASE_IMAGE=vv-auth-candidate
FROM ${BASE_IMAGE}
COPY caddy /usr/local/bin/caddy
ENV XDG_DATA_HOME=/data XDG_CONFIG_HOME=/config
ENTRYPOINT ["/usr/local/bin/caddy"]
CMD ["run", "--config", "/etc/caddy/Caddyfile"]
