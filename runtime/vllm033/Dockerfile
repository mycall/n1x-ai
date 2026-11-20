FROM vllm/vllm-openai@sha256:e3481489818d3e563cae517b84ab959cc8b69f85a9fbb771c189140131ffc65c
COPY native/n1x_dflash_capture.py vllm033/install.py vllm033/n1x_w4.py /opt/n1x-033/
RUN python3 /opt/n1x-033/install.py
