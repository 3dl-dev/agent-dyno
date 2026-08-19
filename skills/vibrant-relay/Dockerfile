# A Vibrant relay = a stock strfry image + Python 3 (to run the write-policy) + the policy.
# The base is a parameter so the recipe adapts to whatever strfry image the target has;
# dockurr/strfry is a maintained Debian-based default (so apt-get can add python3).
ARG STRFRY_IMAGE=dockurr/strfry:latest
FROM ${STRFRY_IMAGE}

# The write-policy plugin runs INSIDE the container, so it needs a Python runtime here.
RUN (apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*) \
    || (apk add --no-cache python3) \
    || true

COPY vibrant_policy.py /app/vibrant_policy.py
COPY vibrant.strfry.conf /etc/strfry.conf
RUN chmod +x /app/vibrant_policy.py && mkdir -p /app/strfry-db

# Tunables (see vibrant_policy.py): PoW difficulty and per-kind size caps.
ENV VIBRANT_POW_BITS=20 \
    VIBRANT_MAX_AGG=8192 \
    VIBRANT_MAX_REPORT=262144

EXPOSE 7777
