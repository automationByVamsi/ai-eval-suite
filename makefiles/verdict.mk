# VERDICT — reliability multi-run + baseline regression (wraps existing KA cases).

.PHONY: verdict-baseline verdict-demo verdict-check verdict-judges verdict-dashboard

# Freeze current sanity traces as the trusted baseline (Layer-1, fast/offline)
verdict-baseline:
	DEMO_MODE=cache python3 -m scripts.run_verdict --n 5 --save-baseline --no-compare

# Show usefulness: same cases, simulated upstream drop → regression vs baseline
verdict-demo:
	DEMO_MODE=cache python3 -m scripts.run_verdict --n 5 --save-baseline --no-compare
	DEMO_MODE=cache python3 -m scripts.run_verdict --n 5 --simulate-regression

# Re-check current build against last baseline (no simulation)
verdict-check:
	DEMO_MODE=cache python3 -m scripts.run_verdict --n 5

# Optional: include CORTEX judge resampling (needs network + creds)
verdict-judges:
	DEMO_MODE=cache python3 -m scripts.run_verdict --n 3 --judges --save-baseline

# Streamlit UI for outputs/verdict/runs/*.json
verdict-dashboard:
	streamlit run scripts/verdict_dashboard.py
