# Hosting Koala on Azure

## Recommended architecture

Keep the current Django-served frontend and REST API together on one origin.
Use managed hosting, PostgreSQL, and a managed customer identity provider.
There is no need for a separate frontend host, Kubernetes, or a virtual machine.

This is a proposed deployment architecture, not an already configured deployment.
The repository currently uses SQLite and local Django authentication.

```text
Browser -- HTTPS --> Azure App Service
                     Django frontend + REST API
                       |
                       +--> Azure Database for PostgreSQL
                       |    Restaurants, reviews, local users, profiles, sessions
                       |
                       +--> Azure Key Vault
                       |    Secrets accessed using managed identity
                       |
                       +--> Azure Monitor / Application Insights
                            Logs, errors, request telemetry, alerts

Sign-in:
Browser <--> Microsoft Entra External ID
               |
               +--> App Service authentication callback
                    Map verified identity to local user; start Django session
```

The callback above is a Django application route hosted on App Service, not an
assumption that App Service's built-in authentication is configured.

## Azure services

| Component | Purpose | Needed initially? |
| --- | --- | --- |
| Azure subscription and resource group | Billing/access boundary and grouping for app resources. | Yes. |
| Azure App Service on Linux | Runs Django, including the HTML frontend, static assets, and REST API. | Yes, for this architecture. |
| App Service plan | Provides the compute capacity and determines supported scaling/features. | Yes; the web app needs a plan. |
| Azure Database for PostgreSQL Flexible Server | Durable relational storage for restaurant data, reviews, local users, profiles, identity mappings, and Django sessions. | Yes, replacing SQLite in production. |
| Microsoft Entra External ID external tenant | Customer signup, sign-in, email verification, password reset, and optional MFA/social login. | Yes, for the proposed managed customer-login design. |
| App Service managed identity | Lets the application access authorised Azure resources without embedding Azure credentials. | Recommended from the start. |
| Azure Key Vault | Stores Django's secret key, the identity-provider client secret, and database credentials if password authentication is used. | Recommended from the start; not a hard hosting dependency. |
| Azure Monitor, Application Insights, and a Log Analytics workspace | Production diagnostics, request/error telemetry, and alerts. Requires Python instrumentation and configuration. | Recommended before public launch. |
| Virtual Network, App Service VNet integration, and private DNS | Allow the application to reach a privately networked database. | Recommended production network design; not required for a restricted public database endpoint. |

Entra External ID is a separate identity-directory configuration, not a database
table or an ordinary resource deployed inside the app's resource group. Keep
customer identities separate from the workforce identities used to administer
Azure. Azure AD B2C is no longer available for purchase by new customers; use
External ID for a new customer identity deployment.

## Application hosting

- Choose a supported Python runtime on Linux App Service.
- Run Django through a production WSGI server such as Gunicorn, using
  `config.wsgi:application`, not Django's development server.
- Configure production static-file handling, for example WhiteNoise, and
  `collectstatic`. App Service hosting alone does not make Django development
  static-file serving suitable for production.
- Start with one app instance and a suitable paid plan. Select a tier supporting
  VNet integration if using the private database design.
- Use the default App Service HTTPS hostname initially. A custom domain and
  certificate can be added later.

The current frontend does not need Azure Static Web Apps or its own deployment.

## Database and networking

Use PostgreSQL for application data and shared database-backed Django sessions.
Do not treat App Service's local filesystem as the production database or as a
durable upload store.

Before switching from SQLite:

1. Add a PostgreSQL driver and environment-based Django database configuration.
2. Apply the Django migrations to PostgreSQL.
3. If preserving prototype data, plan and test an explicit data transfer.
   Running migrations creates the schema; it does not copy SQLite data.
4. Configure encrypted connections, backups, retention, and a tested restore
   procedure. Give the runtime database account only the permissions it needs;
   use a separate migration identity/account if separating schema privileges.

For private database access, provision App Service VNet integration, the
appropriate database networking/subnets, and private DNS. Depending on the
PostgreSQL networking mode, this uses delegated-subnet private access or private
endpoints; do not assume both are required. The deployment migration runner must
also have database connectivity.

A simpler alternative is a public database endpoint restricted to the required
app outbound addresses, with TLS enforced. Do not enable unrestricted public
database access. Account for outbound-address changes when changing the hosting
plan or scaling.

PostGIS is optional: add it only if geographical queries such as radius/distance
search become a requirement. Country/city filtering does not require it.

## Customer accounts and login

Configure an External ID external tenant with:

- A web application registration and its credentials.
- A signup/sign-in user flow, associated with the application.
- Email/password or another supported sign-in method.
- Exact HTTPS callback and applicable logout URLs for each environment.
- MFA and account-recovery policies appropriate to the app.

In Django, implement the authorization-code flow with a maintained authentication
library. Map the verified issuer and subject to a local Django user, with a unique
constraint on that identity pair. Store profile data locally and leave password
management to the provider.

After login, use a Django server-side session and secure cookies. Existing
`request.user`-based review ownership can remain. Keep CSRF protection for writes.
Do not identify accounts by email alone, automatically merge accounts with
matching emails, or accept user ownership IDs from the frontend.

Public display names belong in the local profile and should not expose email
addresses. Admin/moderator access must be explicitly granted, never inferred
from customer signup.

This design uses application-level OIDC login. App Service built-in authentication
("Easy Auth") is an alternative, not a second login layer to enable blindly;
using it still requires a deliberate Django identity/permissions integration.

## Secrets and production configuration

Enable the web app's system-assigned managed identity and grant it narrowly scoped
access to Key Vault secrets. Use App Service Key Vault references or an appropriate
SDK integration to supply secrets. Managed identity does not automatically grant
database access; passwordless PostgreSQL authentication requires separate setup.

Configure:

- A strong, persistent `DJANGO_SECRET_KEY`, without the development fallback.
- Identity-provider client ID, secret, authority, and exact redirect URI.
- PostgreSQL connection settings, including TLS.
- `DEBUG=False`, explicit `ALLOWED_HOSTS`, and any required trusted CSRF origins.
- HTTPS enforcement and secure session/CSRF cookies; HttpOnly session cookies.
- Trusted-proxy HTTPS handling appropriate to App Service's forwarding behaviour.
- An explicit API authentication policy; remove unnecessary Basic Authentication.
- Controlled admin access, dependency updates, and application abuse/rate controls.

Do not commit secrets, production database exports, or authentication tokens.
Keep credentials and tokens out of logs. Run Django's deployment checks against
the production configuration before launch.

## Deployment and operations

GitHub Actions can test and deploy the app to App Service; Azure DevOps is not
required. Prefer GitHub-to-Azure OIDC federation with narrowly scoped deployment
permissions over a long-lived Azure deployment secret.

A deployment should:

1. Run the existing tests and Django checks.
2. Build/install dependencies and collect static assets.
3. Run migrations once in a controlled step with database connectivity, rather
   than independently in every web worker.
4. Deploy/start the application and verify a health endpoint.
5. Smoke-test sign-in, callback/session handling, restaurant queries, review
   ownership, and review submission against the deployed environment.

Configure logs, exception/request telemetry, availability checks, and actionable
alerts. Never log passwords, tokens, cookies, or unnecessarily detailed personal
data. Define telemetry retention and access controls.

Keep development and production databases, credentials, and login configurations
separate. Use separate resources for a staging environment; deployment slots are
an option on supported App Service tiers, but slots must not accidentally share
production write credentials.

## Optional services: add only when needed

| Service | When it becomes useful |
| --- | --- |
| Azure Blob Storage | Restaurant/review photos or other user uploads. Use private storage and controlled access where appropriate. Not needed for the current text/score data. |
| Azure Front Door with WAF | Edge delivery, custom traffic/security rules, or multi-region routing. Not a prerequisite for the first deployment. |
| Azure Managed Redis | Shared caching or other Redis-specific workloads when measurements justify it. PostgreSQL-backed sessions avoid requiring Redis initially. |
| Azure Communication Services Email or another transactional email provider | App-generated notifications. Not needed merely to implement the identity provider's configured verification/reset flows. |
| Azure DNS | Hosting DNS for a custom domain, if not using another DNS provider. Domain registration is separate. |
| Azure Container Registry | If choosing custom-container deployment instead of App Service's built-in Python runtime. |

API Management, Azure AI Search, background job infrastructure, and a separate
frontend host are not required for the current application.

## Cost and initial deployment scope

The main baseline costs are the App Service plan and PostgreSQL server. Also
budget for identity usage/features, monitoring ingestion/retention, Key Vault
operations, backups/storage, and any paid networking features. Exact costs depend
on region, tier, usage, and availability requirements; check current pricing
rather than assuming a free production deployment.

For the first public deployment, provision the web app and plan, PostgreSQL,
External ID, Key Vault/managed identity, and monitoring. Add private networking
as described above and set budget alerts. High availability and multi-region
recovery are separate decisions based on acceptable downtime and data loss.

## References

- [Python on Azure App Service](https://learn.microsoft.com/en-us/azure/app-service/configure-language-python)
- [Deploy Django with PostgreSQL on App Service](https://learn.microsoft.com/en-us/azure/app-service/tutorial-python-postgresql-app-django)
- [Entra External ID for customer applications](https://learn.microsoft.com/en-us/entra/external-id/customers/overview-customers-ciam)
- [External ID web-app sign-in setup](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-web-app-sign-in)
- [App Service Key Vault references](https://learn.microsoft.com/en-us/azure/app-service/app-service-key-vault-references)
- [Azure pricing calculator](https://azure.microsoft.com/en-us/pricing/calculator/)
