# Dev image for cadfix: CadQuery (OpenCascade) + manifold3d + our package.
#   docker build -t cadfix-dev .
#   docker run --rm cadfix-dev                      # runs pytest -q
#   docker run --rm -v "$PWD":/app cadfix-dev ...   # live code, no rebuild needed

# Base pinned by digest (python:3.11-slim = Debian 13 trixie, Python 3.11.18 at time of pinning)
# so a rebuild months later gets the same OS and Python.
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

# Shared libs the cadquery-ocp / vtk wheels link against but slim lacks
# (found with ldd on every .so in site-packages):
#   libgl1     -> libGL.so.1     (OCP imports fail without it)
#   libx11-6   -> libX11.so.6    (vtk)
#   libexpat1  -> libexpat.so.1  (vtk)
# Nothing else is needed: still-unresolved refs are optional plugins we never load
# (casadi commercial solvers / MATLAB bridge, numba TBB/OpenMP thread pools).
# No X server or display: everything runs headless.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libx11-6 libexpat1 \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

# Dependencies first, in their own layer: code edits do not re-download ~2 GB of wheels.
# --retries: large wheels (vtk, cadquery-ocp) time out on PyPI now and then.
COPY requirements.lock .
RUN pip install --retries 5 -r requirements.lock

# Our package, editable, so a bind mount of the repo at /app is picked up without rebuilding.
COPY pyproject.toml .
COPY cadfix ./cadfix
COPY scenarios ./scenarios
COPY tests ./tests
RUN pip install --no-deps -e .

CMD ["pytest", "-q"]
