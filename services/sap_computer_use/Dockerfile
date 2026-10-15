FROM python:3.12-slim-bookworm
WORKDIR /app
COPY services/sap_computer_use/cloud-requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && PLAYWRIGHT_BROWSERS_PATH=/ms-playwright python -m playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 browser \
    && chmod -R a+rX /ms-playwright
COPY domains/sap /app/domains/sap
COPY domains/__init__.py /app/domains/__init__.py
COPY services/sap_computer_use /app/services/sap_computer_use
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV SAP_BROWSER_EXECUTION_MODE=cloud SAP_COMPUTER_USE_GOLDEN_PATH=true SAP_COMPUTER_USE_DEMO_MODE=computer-use
USER browser
CMD ["python", "-m", "services.sap_computer_use.server"]
