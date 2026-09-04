.PHONY: all test batch verify verify-results clean dash live-demo live-batch

# Full from-scratch proof: wipe generated output, run the suite, regenerate
# the experiment, verify ledger integrity, diff results against README.
all: clean test batch verify verify-results

test:
	python3 -m pytest -q

batch:
	python3 scripts/run_batch.py

verify:
	python3 scripts/verify_ledger.py

verify-results:
	python3 scripts/verify_readme.py

# Wipes generated output ONLY. Never touches cache/ — the committed
# diagnosis cache is the official run's provenance (and in --live mode it
# holds paid-for API responses; wiping it would waste real money).
clean:
	rm -rf out
	find . -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true

dash:
	python3 -m streamlit run dashboard/app.py --server.address 0.0.0.0 --server.port 8501

live-demo:
	python3 scripts/live_demo.py --n 10

live-batch:
	python3 scripts/run_batch.py --live
