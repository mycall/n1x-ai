FROM n1x-ai:magi-v5
ENV LMCACHE_TRACK_USAGE=false DO_NOT_TRACK=1 VLLM_NO_USAGE_STATS=1 HF_HUB_DISABLE_TELEMETRY=1
RUN --mount=type=secret,id=https_proxy \
    --mount=type=secret,id=http_proxy \
    HTTPS_PROXY="$(cat /run/secrets/https_proxy)" HTTP_PROXY="$(cat /run/secrets/http_proxy)" uv pip install --python /opt/venv/bin/python lmcache==0.5.6 \
      'torch==2.13.0' 'vllm==0.32.0' 'flashinfer-python==0.7.0.post1'
RUN python -c "import torch; import lmcache.cuda_ops; from lmcache.integration.vllm.lmcache_mp_connector import LMCacheMPConnector; print(torch.__version__)"
RUN uv pip freeze --python /opt/venv/bin/python > /opt/lmcache-runtime-packages.txt
COPY run_suite.py /suite/run_suite.py
COPY probe_ipc_roundtrip.py /suite/probe_ipc_roundtrip.py
ENTRYPOINT ["python", "-u", "/suite/run_suite.py"]
