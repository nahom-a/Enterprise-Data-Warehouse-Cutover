.PHONY: test parity generate clean help

help:
	@echo "Available commands:"
	@echo "  make test      Run the 144-test end-to-end parity validation suite"
	@echo "  make parity    Run the comprehensive proof & regression patch suite"
	@echo "  make generate  Regenerate all synthetic event windows and expected marts"
	@echo "  make clean     Remove temporary test artifacts and caches"

test:
	pytest tests/test_cutover.py -v

parity:
	python tests/proof/run_all.py

generate:
	python regenerate_all.py

clean:
	python -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('.pytest_cache')]"

