# A/B comparative evaluation (paired Candidate A vs Candidate B).
#
#   make comparison-demo
#   make comparison-demo-safety
#   make comparison-test

.PHONY: comparison-demo comparison-demo-safety comparison-test comparison-dashboard

comparison-demo:
	python3 -m scripts.run_comparison --config configs/comparisons/demo_offline.yaml

comparison-demo-safety:
	python3 -m scripts.run_comparison --config configs/comparisons/demo_safety_fail.yaml

comparison-test:
	pytest -v tests/comparison

comparison-dashboard:
	streamlit run scripts/comparison_dashboard.py
