.PHONY: test test-mac test-ubuntu smoke-mac eval-stub ablation-stub lint format clean-results

# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

PYTHON ?= python

test-mac:
	$(PYTHON) -m pytest tests/mac/ -v

test-ubuntu:
	$(PYTHON) -m pytest tests/ubuntu/ -v

test: test-mac

# ------------------------------------------------------------------
# Mac smoke scripts (each phase's smoke runs against stub backends)
# ------------------------------------------------------------------

smoke-mac:
	python scripts/smoke_phase0.py
	python scripts/smoke_phase1.py
	python scripts/smoke_phase2_mac.py
	python scripts/smoke_phase3_mac.py
	python scripts/smoke_phase4_mac.py
	python scripts/smoke_phase5_mac.py
	python scripts/smoke_phase6_mac.py
	python scripts/smoke_phase7_mac.py

# ------------------------------------------------------------------
# Evaluation
# ------------------------------------------------------------------

eval-stub:
	python scripts/run_evaluation.py \
		--table table_2 \
		--conditions cap_v pragmabot \
		--n_trials 3 \
		--output_dir results/stub_run \
		--stub

ablation-stub:
	python scripts/run_ablation.py \
		--sweep memory.top_k 1 3 5 \
		--tasks table_2 \
		--n_trials 2 \
		--output_dir results/ablation_top_k \
		--stub

# ------------------------------------------------------------------
# Code quality
# ------------------------------------------------------------------

lint:
	python -m flake8 pragmabot/src/ --max-line-length=100 || true

format:
	python -m black pragmabot/src/ scripts/ tests/ || true

# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------

clean-results:
	rm -rf results/stub_run results/ablation_top_k
