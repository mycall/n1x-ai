ARG BASE_IMAGE=n1x-ai:magi-v5
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS benchbuild
WORKDIR /src
COPY Client/*.csproj Client/*.cs Client/vision-fixture.png Client/MatrixChart.html ./
RUN dotnet publish Client.csproj -o /app --no-self-contained
FROM ${BASE_IMAGE}
COPY --from=benchbuild /usr/share/dotnet/dotnet /opt/n1x-dotnet/dotnet
COPY --from=benchbuild /usr/share/dotnet/host /opt/n1x-dotnet/host
COPY --from=benchbuild /usr/share/dotnet/shared/Microsoft.NETCore.App /opt/n1x-dotnet/shared/Microsoft.NETCore.App
COPY --from=benchbuild /app /opt/n1x-client
USER root
ENV HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 VLLM_NO_USAGE_STATS=1 \
    TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2
COPY aiperf-constraints.txt /opt/aiperf-constraints.txt
RUN --mount=type=secret,id=https_proxy --mount=type=secret,id=http_proxy \
    export HTTPS_PROXY="$(cat /run/secrets/https_proxy 2>/dev/null)" HTTP_PROXY="$(cat /run/secrets/http_proxy 2>/dev/null)"; \
    uv venv --python /opt/venv/bin/python /opt/aiperf && \
    uv pip install --python /opt/aiperf/bin/python -c /opt/aiperf-constraints.txt aiperf==0.13.0 && \
    uv pip install --python /opt/venv/bin/python nltk==3.9.2 wonderwords==2.2.0 && \
    git clone https://github.com/NVIDIA/RULER.git /opt/RULER && \
    git -C /opt/RULER checkout c3f5e3b4f87f97e048793bb510a3a6b19a46bf3a && \
    python -m nltk.downloader punkt punkt_tab
WORKDIR /benchmarks
RUN --mount=type=secret,id=https_proxy --mount=type=secret,id=http_proxy \
    HTTPS_PROXY="$(cat /run/secrets/https_proxy 2>/dev/null)" HTTP_PROXY="$(cat /run/secrets/http_proxy 2>/dev/null)" \
    uv pip install --python /opt/venv/bin/python tenacity==9.1.4
COPY patch_aiperf.py /benchmarks/patch_aiperf.py
RUN /opt/aiperf/bin/python /benchmarks/patch_aiperf.py && \
    /opt/aiperf/bin/python -c "from aiperf.common.tokenizer import Tokenizer; assert Tokenizer._resolve_local_snapshot('/tmp', 'main') == '/tmp'"
ENTRYPOINT ["/opt/n1x-dotnet/dotnet", "/opt/n1x-client/Client.dll", "suite"]
