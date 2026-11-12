PYTHON ?= python3

.PHONY: check data verify-data crosscheck tsm zip clean

# Offline checks: loads the addon in Lua 5.1 with a fake client, solver scenarios, data vs pinned research/.
check:
	$(PYTHON) tools/check.py

# Regenerate ForeverCrafter/Data/*.lua from research/ (offline, deterministic).
data:
	$(PYTHON) tools/gen_data.py

# Exit 1 if ForeverCrafter/Data/*.lua is stale against research/.
verify-data:
	$(PYTHON) tools/gen_data.py verify

# Sample recipes against the Wowhead Forever tooltips (network): writes research/crosscheck_<date>.txt.
crosscheck:
	$(PYTHON) tools/crosscheck_wowhead.py

# Refresh ForeverCrafter/Data/Sales.lua from TradeSkillMaster's public region CSVs (network; the data changes daily).
tsm:
	$(PYTHON) tools/gen_data.py tsm

# dist/ForeverCrafter-v<version>.zip (unzip into the AddOns folder).
zip: check
	$(PYTHON) -c "import sys; sys.path.insert(0, 'tools'); import check; print('built', check.build_zip())"

clean:
	rm -rf dist tools/__pycache__
