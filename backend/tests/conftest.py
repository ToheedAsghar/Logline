# Registers every domain's models on Base.metadata before any test runs. Without
# this, a test file that only imports e.g. app.auth.models can trigger SQLAlchemy's
# configure_mappers() with other domains' classes (referenced via string-based
# relationship()) still unregistered, raising InvalidRequestError -- and once one
# mapper fails to configure, the failure is cached for the rest of the pytest run.
from app.db import base  # noqa: F401
