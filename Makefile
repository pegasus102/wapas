.PHONY: install test batch verify verify-results all clean

install:
	pip install -r requirements.txt --break-system-packages || pip install -r requirements.txt

test:
	python3 -m pytest tests/ -v

batch:
	python3 scripts/run_batch.py

verify:
	python3 scripts/verify_ledger.py

verify-results:
	python3 scripts/verify_readme.py

all: clean test batch verify verify-results
	@echo ""
	@echo "=== ALL GREEN: tests passed, batch ran, ledger verified, results reproducible ==="

clean:
	rm -rf out/*.jsonl out/*.md out/*.json out_verify_tmp cache/diagnosis_cache.json
	find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
