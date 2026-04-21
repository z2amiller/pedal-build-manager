# Admin Authentication

All routes under `/admin/` are protected by HTTP Basic Auth. Set the `ADMIN_PASSWORD`
environment variable to the desired password before starting the server; if the variable
is unset, every request to an admin route returns `503 Service Unavailable` with a message
indicating that authentication is not configured. The username field in the Basic Auth
dialog is ignored — only the password is checked. Wrong or missing credentials return
`401 Unauthorized` with a `WWW-Authenticate: Basic` header so browsers prompt
automatically. See `deploy/Caddyfile.example` for a sample reverse-proxy configuration.
