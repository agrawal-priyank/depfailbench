FROM python:3.12-slim

WORKDIR /workspace
COPY . /workspace
RUN python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip install --no-cache-dir --no-deps .

ENTRYPOINT ["depfailbench"]
CMD ["validate-references", "--repetitions", "3", "--output", "/workspace/results/reference_validation.jsonl"]
