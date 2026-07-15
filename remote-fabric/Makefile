.PHONY: test check

PYTHON ?= python3

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

check:
	$(PYTHON) -m compileall -q src tests
	$(PYTHON) -m py_compile bin/fabric
	bash -n bootstrap/*.sh
	$(PYTHON) -m json.tool inventory/hosts.json >/dev/null
	$(PYTHON) -m json.tool config/deployments.json >/dev/null
	$(PYTHON) -m json.tool config/secret-manifest.example.json >/dev/null
	$(PYTHON) -m json.tool config/repositories.example.json >/dev/null
	@if command -v pwsh >/dev/null 2>&1; then pwsh -NoProfile -Command "[void][scriptblock]::Create((Get-Content -Raw bootstrap/windows-wsl.ps1))"; else echo 'pwsh unavailable: parser check deferred to Windows CI'; fi
