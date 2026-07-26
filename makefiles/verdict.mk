# VERDICT — reliability multi-run + baseline regression (wraps existing KA cases).
# Capture live ADK outputs first (make test-ka-sanity / scripts.capture_traces).

.PHONY: verdict-baseline verdict-demo verdict-check verdict-judges verdict-dashboard

# Freeze current sanity outputs as the trusted baseline (Layer-1)
verdict-baseline:
	python3 -m scripts.run_verdict --n 5 --save-baseline --no-compare

# Show usefulness: same cases, simulated upstream drop → regression vs baseline
verdict-demo:
	python3 -m scripts.run_verdict --n 5 --save-baseline --no-compare
	python3 -m scripts.run_verdict --n 5 --simulate-regression

# Re-check current build against last baseline (no simulation)
verdict-check:
	python3 -m scripts.run_verdict --n 5

# Optional: include CORTEX judge resampling (needs network + creds)
verdict-judges:
	python3 -m scripts.run_verdict --n 3 --judges --save-baseline

# Streamlit UI for outputs/verdict/runs/*.json
verdict-dashboard:
	streamlit run scripts/verdict_dashboard.py
