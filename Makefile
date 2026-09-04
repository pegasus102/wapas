verify-results:
	python3 scripts/verify_readme.py

dash:
	streamlit run dashboard/app.py --server.address 0.0.0.0

live-demo:
	python3 scripts/live_demo.py --n 10

live-batch:
	python3 scripts/run_batch.py --live

all: clean test batch verify verify-results