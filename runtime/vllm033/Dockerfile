FROM vllm/vllm-openai@sha256:e3481489818d3e563cae517b84ab959cc8b69f85a9fbb771c189140131ffc65c AS runtime
COPY native/n1x_dflash_capture.py vllm033/install.py vllm033/n1x_w4.py /opt/n1x-033/
RUN python3 /opt/n1x-033/install.py
COPY vllm033/ple_prefetch.cpp vllm033/n1x_prefetch.py /opt/n1x-033/
RUN site=$(python3 -c "import sysconfig;print(sysconfig.get_path('purelib'))") && \
    cp /opt/n1x-033/n1x_prefetch.py "$site/" && \
    g++ -O3 -Wall -Wextra -shared -fPIC -I/usr/local/cuda/include /opt/n1x-033/ple_prefetch.cpp \
    -L/usr/local/cuda/lib64 -lcudart -o "$site/libn1x_ple.so"

FROM runtime
COPY vllm033/dflash-graph.patch /opt/n1x-033/
# Backport vllm-project/vllm#64059 to the exact 0.33 source.
RUN cd "$(python3 -c "import sysconfig;print(sysconfig.get_path('purelib'))")" && \
    echo "27368c98791397625603ba45782119e4d306880841900a9d07587a6d6757d3ee  vllm/v1/worker/gpu/spec_decode/dflash/speculator.py" | sha256sum -c - && \
    patch --fuzz=0 -p1 < /opt/n1x-033/dflash-graph.patch
