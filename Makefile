# UI Parity Agent - common tasks. Everything runs offline by default (MockLLM, local demo sites).
PYTHON ?= $(shell command -v python3 || command -v python)
PIP_FLAGS ?=
REPORT ?=

.PHONY: setup demo test eval app clean docker-build docker-run

setup:  ## install Python deps + Playwright Chromium (set SKIP_BROWSER_INSTALL=1 if Chromium is already installed)
	$(PYTHON) -m pip install $(PIP_FLAGS) -r requirements.txt
	@if [ -z "$(SKIP_BROWSER_INSTALL)" ]; then $(PYTHON) -m playwright install chromium; fi

demo:  ## audit the bundled Nimbus Wireless web + app demo sites -> reports/<timestamp>/
	$(PYTHON) -m parity_agent run --demo

test:  ## offline test suite
	$(PYTHON) -m pytest -q

eval:  ## precision/recall vs demo_sites/PLANTED_DIFFERENCES.yaml (REPORT=reports/<ts> to score an existing run)
	$(PYTHON) -m parity_agent eval --min-recall 0.9 $(if $(REPORT),--report $(REPORT),)

app:  ## Streamlit UI
	$(PYTHON) -m streamlit run app.py

clean:
	rm -rf reports .pytest_cache **/__pycache__

docker-build:
	docker build -t ui-parity-agent .

docker-run:
	docker run --rm -p 8501:8501 --env-file .env ui-parity-agent
